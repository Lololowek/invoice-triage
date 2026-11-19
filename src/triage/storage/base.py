"""What the application needs from storage, and nothing more."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel

from triage.result import InvoiceResult
from triage.review import EditEntry, Value


class StoredDocument(BaseModel):
    id: str
    filename: str
    uploaded_at: datetime
    result: InvoiceResult
    reviewed_at: datetime | None = None
    final_values: dict[str, Value] | None = None  # from the latest review


class DocumentSummary(BaseModel):
    id: str
    filename: str
    uploaded_at: datetime
    reviewed_at: datetime | None
    mapper: str
    fields: int
    to_review: int
    flagged: int


class Repository(Protocol):
    def add_document(self, filename: str, result: InvoiceResult) -> StoredDocument: ...

    def get_document(self, document_id: str) -> StoredDocument | None: ...

    def list_documents(self) -> list[DocumentSummary]: ...

    def add_review(self, document_id: str, entries: list[EditEntry]) -> datetime:
        """Store one review (the full edit log of the document); return its timestamp."""
        ...

    def edit_log(self, document_id: str | None = None) -> list[EditEntry]:
        """Entries of the latest review of each document (or of one document)."""
        ...
