"""HTTP API.

    POST /documents                 upload a PDF -> pipeline -> stored result
    GET  /documents                 list
    GET  /documents/{id}            result, final values after review, extracted text
    POST /documents/{id}/review     {"values": {path: value}} -> edit log
    GET  /documents/{id}/edits      edit log of the latest review
    GET  /metrics                   quality measured from the edit log
    GET  /health

Run:  triage serve   (or: uvicorn triage.api:create_app --factory)

Settings come from the environment / .env:
    TRIAGE_DB       SQLite file, default triage.sqlite3
    TRIAGE_MAPPER   llm (default, LLM_* variables) | oracle (gold annotation, for a demo without a
                    model; works only for the synthetic invoices)
    TRIAGE_GOLD     gold file for the oracle, default data/gold.json

Processing is synchronous inside the request: no queue (see README, limitations).
"""

from __future__ import annotations

import io
import json
import os
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import openai
from fastapi import FastAPI, HTTPException, UploadFile
from pydantic import BaseModel

from triage.env import load_env_file
from triage.llm.client import ConfigError, LLMSettings, OpenAICompatibleClient
from triage.llm.mapper import LLMMapper, Mapper, MappingError
from triage.llm.oracle import OracleMapper
from triage.pdf_text import NotAPdfError, NoTextLayerError, extract_text
from triage.pipeline import process_text
from triage.policy import RiskPolicy
from triage.result import FieldResult, Flag
from triage.review import EditEntry, EditError, Value, build_edit_log, quality_metrics
from triage.storage import DocumentSummary, Repository, SQLiteRepository, StoredDocument

MAX_UPLOAD_BYTES = 20 * 1024 * 1024

MapperFactory = Callable[[str], Mapper]  # file name -> mapper


class UnknownDocumentError(LookupError):
    """The oracle has no gold annotation for this file."""


class DocumentOut(BaseModel):
    id: str
    filename: str
    uploaded_at: datetime
    reviewed_at: datetime | None
    mapper: str
    line_items_source: str
    fields: list[FieldResult]
    document_flags: list[Flag]
    final_values: dict[str, Value] | None
    text: str

    @classmethod
    def of(cls, doc: StoredDocument) -> DocumentOut:
        r = doc.result
        return cls(
            id=doc.id,
            filename=doc.filename,
            uploaded_at=doc.uploaded_at,
            reviewed_at=doc.reviewed_at,
            mapper=r.mapper,
            line_items_source=r.line_items_source,
            fields=r.fields,
            document_flags=r.document_flags,
            final_values=doc.final_values,
            text=r.text,
        )


class ReviewIn(BaseModel):
    values: dict[str, Any] = {}  # path -> final value; empty string or null clears the field


class ReviewOut(BaseModel):
    document_id: str
    reviewed_at: datetime
    corrected: list[str]
    confirmed: int
    accepted: int


def mapper_factory_from_env(env: Mapping[str, str] = os.environ) -> MapperFactory:
    kind = env.get("TRIAGE_MAPPER", "llm").strip()
    if kind == "oracle":
        gold_path = Path(env.get("TRIAGE_GOLD", "data/gold.json"))
        gold = json.loads(gold_path.read_text(encoding="utf-8"))["documents"]

        def oracle(filename: str) -> Mapper:
            if filename not in gold:
                raise UnknownDocumentError(
                    f"{filename} is not in {gold_path}; the oracle knows only the synthetic set"
                )
            return OracleMapper(gold[filename])

        return oracle
    if kind != "llm":
        raise ConfigError(f"TRIAGE_MAPPER must be llm or oracle, got {kind!r}")
    settings = LLMSettings.from_env(env)
    mapper = LLMMapper(OpenAICompatibleClient(settings), answer_format=settings.answer_format)
    return lambda filename: mapper


def create_app(
    repository: Repository | None = None,
    make_mapper: MapperFactory | None = None,
    policy: RiskPolicy | None = None,
) -> FastAPI:
    """Arguments are for tests; left out, everything is configured from the environment."""
    if repository is None or make_mapper is None or policy is None:
        load_env_file()
    repo: Repository = repository or SQLiteRepository(os.environ.get("TRIAGE_DB", "triage.sqlite3"))
    mapper_for: MapperFactory = make_mapper or mapper_factory_from_env()
    risk_policy = policy or RiskPolicy.load()

    app = FastAPI(title="invoice-triage", version="0.1.0")

    def get_or_404(document_id: str) -> StoredDocument:
        doc = repo.get_document(document_id)
        if doc is None:
            raise HTTPException(404, f"document {document_id} not found")
        return doc

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/documents", status_code=201)
    def upload(file: UploadFile) -> DocumentOut:
        data = file.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"file is larger than {MAX_UPLOAD_BYTES // 2**20} MB")
        if not data.startswith(b"%PDF-"):
            raise HTTPException(415, "only PDF files are accepted")
        filename = Path(file.filename or "upload.pdf").name
        try:
            text = extract_text(io.BytesIO(data), name=filename)
            result = process_text(text, mapper_for(filename), risk_policy, document=filename)
        except NotAPdfError as e:
            raise HTTPException(415, str(e)) from e
        except (NoTextLayerError, UnknownDocumentError) as e:
            raise HTTPException(422, str(e)) from e
        except MappingError as e:
            raise HTTPException(502, str(e)) from e
        except (openai.APIConnectionError, openai.APITimeoutError) as e:
            raise HTTPException(503, f"model server is not reachable: {e}") from e
        return DocumentOut.of(repo.add_document(filename, result))

    @app.get("/documents")
    def list_documents() -> list[DocumentSummary]:
        return repo.list_documents()

    @app.get("/documents/{document_id}")
    def get_document(document_id: str) -> DocumentOut:
        return DocumentOut.of(get_or_404(document_id))

    @app.post("/documents/{document_id}/review")
    def review(document_id: str, body: ReviewIn) -> ReviewOut:
        doc = get_or_404(document_id)
        try:
            entries = build_edit_log(doc.id, doc.result, body.values, doc.final_values)
        except EditError as e:
            raise HTTPException(422, {"fields": e.errors}) from e
        reviewed_at = repo.add_review(doc.id, entries)
        return ReviewOut(
            document_id=doc.id,
            reviewed_at=reviewed_at,
            corrected=[e.path for e in entries if e.action == "corrected"],
            confirmed=sum(e.action == "confirmed" for e in entries),
            accepted=sum(e.action == "accepted" for e in entries),
        )

    @app.get("/documents/{document_id}/edits")
    def edits(document_id: str) -> list[EditEntry]:
        get_or_404(document_id)
        return repo.edit_log(document_id)

    @app.get("/metrics")
    def metrics() -> dict[str, Any]:
        return quality_metrics(repo.edit_log())

    return app
