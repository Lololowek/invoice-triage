from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

CandidateType = Literal["date", "amount", "identifier", "currency"]

ID_PREFIX: dict[str, str] = {"date": "D", "amount": "A", "identifier": "I", "currency": "C"}


class Candidate(BaseModel):
    """A value found in the text by deterministic code. The model may only point at these."""

    model_config = ConfigDict(frozen=True)

    id: str
    type: CandidateType
    raw: str  # exact substring of the document text
    value: str  # normalized: ISO date, decimal string, compact identifier, ISO currency code
    start: int
    end: int
    subtypes: tuple[str, ...] = ()  # identifiers only: bin_iin, inn, vat, iban, doc_number, ...
    flags: tuple[str, ...] = ()  # e.g. "ambiguous"


@dataclass(frozen=True)
class RawMatch:
    """A finder's result before overlap resolution and numbering."""

    start: int
    end: int
    type: CandidateType | None  # None = claim the span but emit nothing (percentages)
    raw: str
    value: str = ""
    subtypes: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()
