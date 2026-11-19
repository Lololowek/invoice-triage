from __future__ import annotations

import re
from collections.abc import Iterator

from triage.candidates.model import RawMatch
from triage.normalize import parse_amount

# Percentages are claimed first so that "16" in "НДС 16%" does not become an amount candidate.
_PERCENT = re.compile(r"(?<![\w.,])\d{1,3}(?:[.,]\d{1,2})?\s?%")

# Order of alternatives matters: grouped forms before the plain one.
# Thousands are separated by ONE space; pdf_text guarantees table columns are 2+ spaces apart.
_AMOUNT = re.compile(
    r"(?<![\w.,\-−])"
    r"(?:[-−]\s?)?"
    r"(?:"
    r"\d{1,3}(?: \d{3})+(?:[.,]\d{1,4})?"
    r"|\d{1,3}(?:,\d{3})+(?:\.\d{1,4})?"
    r"|\d{1,3}(?:\.\d{3})+(?:,\d{1,4})?"
    r"|\d+(?:[.,]\d{1,4})?"
    r")"
    r"(?!\d|[.,]\d)"
)


def find_percentages(text: str) -> Iterator[RawMatch]:
    for m in _PERCENT.finditer(text):
        yield RawMatch(start=m.start(), end=m.end(), type=None, raw=m.group(0))


def find_amounts(text: str) -> Iterator[RawMatch]:
    for m in _AMOUNT.finditer(text):
        parsed = parse_amount(m.group(0))
        if parsed is None:
            continue
        yield RawMatch(
            start=m.start(),
            end=m.end(),
            type="amount",
            raw=m.group(0),
            value=parsed.value,
            flags=("ambiguous",) if parsed.ambiguous else (),
        )
