"""Storage behind a narrow interface. SQLite now; another database is one module implementing
`Repository` (see sqlite.py for the tables)."""

from triage.storage.base import DocumentSummary, Repository, StoredDocument
from triage.storage.sqlite import SQLiteRepository

__all__ = ["DocumentSummary", "Repository", "SQLiteRepository", "StoredDocument"]
