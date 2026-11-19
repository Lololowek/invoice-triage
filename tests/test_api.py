"""HTTP API with a temporary database. The mapper is the oracle, or a scripted fake model."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from triage.api import create_app, mapper_factory_from_env
from triage.llm.client import ConfigError
from triage.llm.mapper import LLMMapper, Mapper
from triage.llm.oracle import OracleMapper
from triage.policy import RiskPolicy
from triage.storage import SQLiteRepository

from .conftest import GOLD, INVOICES, ScriptedClient

UK = "inv_07_uk_software.pdf"


def oracle(filename: str) -> Mapper:
    return OracleMapper(GOLD[filename], inject=["hallucinate:contract_number=ДГ-2026/017"])


def make_client(tmp_path: Path, make_mapper: Callable[[str], Mapper] = oracle) -> TestClient:
    app = create_app(SQLiteRepository(tmp_path / "t.sqlite3"), make_mapper, RiskPolicy.load())
    return TestClient(app)


def upload(client: TestClient, name: str = UK, data: bytes | None = None) -> dict:  # type: ignore[type-arg]
    content = data if data is not None else (INVOICES / name).read_bytes()
    response = client.post("/documents", files={"file": (name, content, "application/pdf")})
    assert response.status_code == 201, response.text
    return response.json()


def test_upload_review_metrics(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    doc = upload(client)
    assert doc["filename"] == UK
    assert doc["line_items_source"] == "code"
    assert doc["final_values"] is None
    queue = {f["path"]: f for f in doc["fields"] if f["needs_review"]}
    assert set(queue) == {"contract_number", "supplier_account", "supplier_bank_code", "total"}
    assert queue["contract_number"]["status"] == "flagged"
    assert queue["contract_number"]["flags"][0]["code"] == "quote_not_found"

    listed = client.get("/documents").json()
    assert [(d["id"], d["to_review"], d["reviewed_at"]) for d in listed] == [(doc["id"], 4, None)]

    response = client.post(
        f"/documents/{doc['id']}/review", json={"values": {"contract_number": ""}}
    )
    assert response.status_code == 200
    review = response.json()
    assert review["corrected"] == ["contract_number"]
    assert review["confirmed"] == 3

    after = client.get(f"/documents/{doc['id']}").json()
    assert after["reviewed_at"] == review["reviewed_at"]
    assert after["final_values"]["contract_number"] is None

    edits = client.get(f"/documents/{doc['id']}/edits").json()
    assert len(edits) == len(doc["fields"])

    metrics = client.get("/metrics").json()
    assert (metrics["caught_by_checks"], metrics["false_alarms"]) == (1, 0)


def test_review_with_bad_values_explains_each_field(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    doc = upload(client)
    response = client.post(
        f"/documents/{doc['id']}/review",
        json={"values": {"issue_date": "31.02.2026", "nope": "x"}},
    )
    assert response.status_code == 422
    assert set(response.json()["detail"]["fields"]) == {"issue_date", "nope"}
    assert client.get(f"/documents/{doc['id']}/edits").json() == []  # nothing was stored


@pytest.mark.parametrize(
    ("data", "status"),
    [
        (b"hello", 415),  # not a PDF at all
        (b"%PDF-1.4 broken", 415),  # looks like one, cannot be parsed
    ],
)
def test_upload_rejects_non_pdfs(tmp_path: Path, data: bytes, status: int) -> None:
    client = make_client(tmp_path)
    response = client.post("/documents", files={"file": ("x.pdf", data, "application/pdf")})
    assert response.status_code == status


def test_unknown_document_is_404(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    assert client.get("/documents/nope").status_code == 404
    assert client.post("/documents/nope/review", json={"values": {}}).status_code == 404


def test_model_that_never_answers_properly_is_502(tmp_path: Path) -> None:
    mapper = LLMMapper(ScriptedClient("garbage", "more garbage"))
    client = make_client(tmp_path, lambda filename: mapper)
    response = client.post(
        "/documents", files={"file": (UK, (INVOICES / UK).read_bytes(), "application/pdf")}
    )
    assert response.status_code == 502
    assert client.get("/documents").json() == []


def test_oracle_from_env_knows_only_the_synthetic_set(tmp_path: Path) -> None:
    factory = mapper_factory_from_env(
        {"TRIAGE_MAPPER": "oracle", "TRIAGE_GOLD": str(INVOICES.parent / "gold.json")}
    )
    client = make_client(tmp_path, factory)
    upload(client)
    response = client.post(
        "/documents",
        files={"file": ("renamed.pdf", (INVOICES / UK).read_bytes(), "application/pdf")},
    )
    assert response.status_code == 422


def test_mapper_config_errors() -> None:
    with pytest.raises(ConfigError):
        mapper_factory_from_env({"TRIAGE_MAPPER": "magic"})
    with pytest.raises(ConfigError):
        mapper_factory_from_env({})  # llm without LLM_MODEL
