"""SQLite repository: standard library only, one connection per operation (FastAPI runs sync
endpoints in a thread pool, and a sqlite3 connection must stay in its thread).

documents   one row per upload; the pipeline result as JSON plus a few columns for listing
reviews     one row per submitted review
edit_log    one row per field per review: extracted value, final value, action, flags
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path

from triage.result import InvoiceResult
from triage.review import EditEntry, final_values
from triage.storage.base import DocumentSummary, StoredDocument

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id          TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    mapper      TEXT NOT NULL,
    fields      INTEGER NOT NULL,
    to_review   INTEGER NOT NULL,
    flagged     INTEGER NOT NULL,
    result_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id  TEXT NOT NULL REFERENCES documents(id),
    submitted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS edit_log (
    review_id    INTEGER NOT NULL REFERENCES reviews(id),
    document_id  TEXT NOT NULL REFERENCES documents(id),
    path         TEXT NOT NULL,
    spec         TEXT NOT NULL,
    kind         TEXT NOT NULL,
    extracted    TEXT,          -- JSON: string, boolean or null
    final        TEXT,
    action       TEXT NOT NULL CHECK (action IN ('corrected', 'confirmed', 'accepted')),
    needs_review INTEGER NOT NULL,
    risk         TEXT NOT NULL,
    flags        TEXT NOT NULL, -- JSON list of "layer:code"
    PRIMARY KEY (review_id, path)
);
CREATE INDEX IF NOT EXISTS edit_log_document ON edit_log(document_id);
"""

# The latest review of each document; earlier reviews stay in the table as history.
_LATEST = "SELECT MAX(id) FROM reviews GROUP BY document_id"


def _now() -> datetime:
    return datetime.now(UTC)


class SQLiteRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._tx() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            with db:  # commit on success, roll back on error
                yield db

    def add_document(self, filename: str, result: InvoiceResult) -> StoredDocument:
        doc = StoredDocument(
            id=uuid.uuid4().hex[:12], filename=filename, uploaded_at=_now(), result=result
        )
        with self._tx() as db:
            db.execute(
                "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    doc.id,
                    filename,
                    doc.uploaded_at.isoformat(),
                    result.mapper,
                    len(result.fields),
                    len(result.review_queue),
                    sum(bool(f.flags) for f in result.fields),
                    result.model_dump_json(),
                ),
            )
        return doc

    def get_document(self, document_id: str) -> StoredDocument | None:
        with self._tx() as db:
            row = db.execute(
                "SELECT d.*, (SELECT MAX(submitted_at) FROM reviews r WHERE r.document_id = d.id)"
                " AS reviewed_at FROM documents d WHERE d.id = ?",
                (document_id,),
            ).fetchone()
        if row is None:
            return None
        entries = self.edit_log(document_id)
        return StoredDocument(
            id=row["id"],
            filename=row["filename"],
            uploaded_at=row["uploaded_at"],
            result=InvoiceResult.model_validate_json(row["result_json"]),
            reviewed_at=row["reviewed_at"],
            final_values=final_values(entries) if entries else None,
        )

    def list_documents(self) -> list[DocumentSummary]:
        with self._tx() as db:
            rows = db.execute(
                "SELECT d.id, d.filename, d.uploaded_at, d.mapper, d.fields, d.to_review,"
                " d.flagged, (SELECT MAX(submitted_at) FROM reviews r"
                " WHERE r.document_id = d.id) AS reviewed_at"
                " FROM documents d ORDER BY d.uploaded_at DESC"
            ).fetchall()
        return [DocumentSummary(**dict(row)) for row in rows]

    def add_review(self, document_id: str, entries: list[EditEntry]) -> datetime:
        submitted_at = _now()
        with self._tx() as db:
            cursor = db.execute(
                "INSERT INTO reviews (document_id, submitted_at) VALUES (?, ?)",
                (document_id, submitted_at.isoformat()),
            )
            db.executemany(
                "INSERT INTO edit_log VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        cursor.lastrowid,
                        document_id,
                        e.path,
                        e.spec,
                        e.kind.value,
                        json.dumps(e.extracted, ensure_ascii=False),
                        json.dumps(e.final, ensure_ascii=False),
                        e.action,
                        int(e.needs_review),
                        e.risk,
                        json.dumps(e.flags),
                    )
                    for e in entries
                ],
            )
        return submitted_at

    def edit_log(self, document_id: str | None = None) -> list[EditEntry]:
        query = (
            "SELECT e.*, r.submitted_at FROM edit_log e JOIN reviews r ON r.id = e.review_id"
            f" WHERE e.review_id IN ({_LATEST})"
        )
        params: tuple[str, ...] = ()
        if document_id is not None:
            query += " AND e.document_id = ?"
            params = (document_id,)
        with self._tx() as db:
            rows = db.execute(query + " ORDER BY e.review_id, e.rowid", params).fetchall()
        return [
            EditEntry(
                document_id=row["document_id"],
                path=row["path"],
                spec=row["spec"],
                kind=row["kind"],
                extracted=json.loads(row["extracted"]),
                final=json.loads(row["final"]),
                action=row["action"],
                needs_review=bool(row["needs_review"]),
                risk=row["risk"],
                flags=json.loads(row["flags"]),
                review_id=row["review_id"],
                reviewed_at=row["submitted_at"],
            )
            for row in rows
        ]
