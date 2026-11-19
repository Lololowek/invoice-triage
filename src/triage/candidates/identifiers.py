"""Identifier finders: IBAN, long digit runs (BIN/INN/accounts/BIK), VAT IDs, BIC, document numbers.

Subtypes are assigned by format only. Whether a 12-digit number is the supplier's BIN or the
buyer's is a question about the label next to it, which is the model's job.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from triage import idformats
from triage.candidates.model import RawMatch
from triage.normalize import parse_identifier

_IBAN = re.compile(r"(?<![\w])[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?(?![\w])")
_DIGITS = re.compile(r"(?<![\w.,\-/])\d{9,20}(?![\w]|[.,]\d)")
_VAT = re.compile(rf"(?<![\w])(?:{'|'.join(idformats.VAT_PREFIXES)}) ?[0-9A-Z]{{8,12}}(?![\w])")
_BIC = re.compile(r"(?<![\w])[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?(?![\w])")

# A number after an explicit marker: "№ 45", "No. INV-7", "Nr. 2026/117", "# 1182".
_MARKED = re.compile(
    r"(?:№|\bN[oº°]\.?|\bNr\.?|#)[ \t]*"
    r"(?P<num>[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9\-/._]*)"
)
# Codes without a marker: "INV-2026-0042", "СЧ-00045", "ДП-0457", "2026-117", "MSA-2025-031".
_CODE = re.compile(r"(?<![\w\-/])[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9\-/]{2,39}(?![\w\-/])")


def _iban_matches(text: str) -> Iterator[RawMatch]:
    for m in _IBAN.finditer(text):
        raw = m.group(0)
        expected = idformats.IBAN_LENGTHS.get(raw[:2])
        if expected is None:
            continue
        # The greedy pattern may swallow a following group; cut at the country's IBAN length.
        count, end = 0, m.start()
        for i, ch in enumerate(raw):
            if ch != " ":
                count += 1
            if count == expected:
                end = m.start() + i + 1
                break
        if count < expected:
            continue
        raw = text[m.start() : end]
        yield RawMatch(m.start(), end, "identifier", raw, idformats.compact(raw), ("iban",))


def _digit_matches(text: str) -> Iterator[RawMatch]:
    for m in _DIGITS.finditer(text):
        value = m.group(0)
        yield RawMatch(
            m.start(), m.end(), "identifier", value, value, idformats.subtypes_for_digits(value)
        )


def _vat_matches(text: str) -> Iterator[RawMatch]:
    for m in _VAT.finditer(text):
        value = idformats.compact(m.group(0))
        if idformats.vat_format_ok(value):
            yield RawMatch(m.start(), m.end(), "identifier", m.group(0), value, ("vat",))


def _bic_matches(text: str) -> Iterator[RawMatch]:
    for m in _BIC.finditer(text):
        if idformats.bic_format_ok(m.group(0)):
            yield RawMatch(m.start(), m.end(), "identifier", m.group(0), m.group(0), ("bic",))


def _doc_number_matches(text: str) -> Iterator[RawMatch]:
    for m in _MARKED.finditer(text):
        num = m.group("num").rstrip("._/-")
        if not any(c.isdigit() for c in num):
            continue
        start = m.start("num")
        yield RawMatch(start, start + len(num), "identifier", num, _id(num), ("doc_number",))
    for m in _CODE.finditer(text):
        token = m.group(0)
        digits = sum(c.isdigit() for c in token)
        has_letter = any(c.isalpha() for c in token)
        has_sep = "-" in token or "/" in token
        if digits < 2 or not (has_letter or has_sep) or token.isdigit():
            continue
        if has_letter and not has_sep and not any(c.isupper() for c in token):
            continue  # "100мл", "5кг2": units glued to numbers, not codes
        yield RawMatch(m.start(), m.end(), "identifier", token, _id(token), ("doc_number",))


def _id(raw: str) -> str:
    parsed = parse_identifier(raw)
    return parsed.value if parsed else raw


def find_strong_identifiers(text: str) -> Iterator[RawMatch]:
    """Identifiers with a strict format. Run before dates and amounts."""
    yield from _iban_matches(text)
    yield from _digit_matches(text)
    yield from _vat_matches(text)
    yield from _bic_matches(text)


def find_doc_numbers(text: str) -> Iterator[RawMatch]:
    """Loose document-number shapes. Run after dates so '15.01.2026' is never a number."""
    yield from _doc_number_matches(text)
