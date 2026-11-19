"""Candidate extraction: plain Python and regular expressions, no model.

Finders run in priority order and each one claims its spans; a later finder cannot take a span that
overlaps an earlier claim. The order encodes which reading wins:

1. strict identifiers (IBAN, 9-20 digit runs, VAT, BIC) - so a BIN is never read as an amount;
2. dates - so '15.01.2026' is never a document number or three amounts;
3. document numbers ('№ 45', 'INV-2026-0042');
4. percentages - claimed and dropped, so '16' in 'НДС 16%' is not an amount;
5. currency markers;
6. amounts - whatever numbers are left.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable

from triage.candidates.amounts import find_amounts, find_percentages
from triage.candidates.currency import find_currencies
from triage.candidates.dates import find_dates
from triage.candidates.identifiers import find_doc_numbers, find_strong_identifiers
from triage.candidates.model import ID_PREFIX, Candidate, RawMatch

Finder = Callable[[str], Iterable[RawMatch]]

STAGES: tuple[Finder, ...] = (
    find_strong_identifiers,
    find_dates,
    find_doc_numbers,
    find_percentages,
    find_currencies,
    find_amounts,
)


def extract_candidates(text: str) -> list[Candidate]:
    claimed: list[tuple[int, int]] = []
    accepted: list[RawMatch] = []
    for stage in STAGES:
        for m in sorted(stage(text), key=lambda m: (m.start, m.start - m.end)):
            if any(m.start < end and start < m.end for start, end in claimed):
                continue
            claimed.append((m.start, m.end))
            if m.type is not None:
                accepted.append(m)

    accepted = _dedupe_currencies(accepted)
    accepted.sort(key=lambda m: m.start)

    counters: Counter[str] = Counter()
    candidates: list[Candidate] = []
    for m in accepted:
        assert m.type is not None
        counters[m.type] += 1
        candidates.append(
            Candidate(
                id=f"{ID_PREFIX[m.type]}{counters[m.type]}",
                type=m.type,
                raw=m.raw,
                value=m.value,
                start=m.start,
                end=m.end,
                subtypes=m.subtypes,
                flags=m.flags,
            )
        )
    return candidates


def _dedupe_currencies(matches: list[RawMatch]) -> list[RawMatch]:
    """A currency sign next to every amount adds nothing; keep the first occurrence per code."""
    seen: set[str] = set()
    result: list[RawMatch] = []
    for m in sorted(matches, key=lambda m: m.start):
        if m.type == "currency":
            if m.value in seen:
                continue
            seen.add(m.value)
        result.append(m)
    return result
