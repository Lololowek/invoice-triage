"""Output model: what the pipeline says about every field."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, computed_field

from triage.candidates import Candidate
from triage.schema import FieldKind

Layer = Literal["schema", "grounding", "arithmetic"]
Risk = Literal["high", "medium", "low"]


class Flag(BaseModel):
    layer: Layer
    code: str  # stable machine code, e.g. "quote_not_found", "checksum", "sum_mismatch"
    message: str


class Source(BaseModel):
    """Where in the document the value came from."""

    via: Literal["candidate", "quote"]
    candidate_id: str | None = None
    text: str  # the document substring
    start: int
    end: int
    match: Literal["exact", "fuzzy"] = "exact"
    score: float | None = None  # rapidfuzz score for fuzzy text matches


class FieldResult(BaseModel):
    path: str  # "total", "line_items[2].amount", "expense_category"
    spec: str  # "total", "line_items.amount", "expense_category"
    kind: FieldKind
    value: str | bool | None
    source: Source | None = None
    flags: list[Flag] = []
    risk: Risk = "medium"
    needs_review: bool = False
    review_reason: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> Literal["ok", "flagged"]:
        return "flagged" if self.flags else "ok"

    def flag(self, layer: Layer, code: str, message: str) -> None:
        if not any(f.layer == layer and f.code == code for f in self.flags):
            self.flags.append(Flag(layer=layer, code=code, message=message))


class InvoiceResult(BaseModel):
    document: str
    mapper: str  # which mapper produced the mapping: model name or "oracle"
    line_items_source: Literal["code", "model"] = "model"  # see line_items.py
    fields: list[FieldResult]
    document_flags: list[Flag] = []  # problems that belong to no single field
    candidates: list[Candidate]
    text: str

    def field(self, path: str) -> FieldResult | None:
        return next((f for f in self.fields if f.path == path), None)

    @property
    def review_queue(self) -> list[FieldResult]:
        return [f for f in self.fields if f.needs_review]
