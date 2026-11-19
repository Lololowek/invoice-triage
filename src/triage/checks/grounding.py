"""Layer 2: binding to the source.

Turns the model's mapping into values and checks that each value can be traced to the document:
- a candidate id must exist and be of a type the field accepts;
- a quote for a number/date/identifier must occur in the text EXACTLY (after whitespace
  normalization), as a whole token, and must normalize to the value the model claims;
- a quote for a text field may match fuzzily (rapidfuzz), because names differ in quote marks,
  dashes and case, and nothing downstream depends on their exact characters;
- a value with neither candidate nor quote cannot be traced at all.

Why no fuzzy matching for numbers: '12 345 678,90' with two digits swapped is ~92% similar, so a
fuzzy threshold of 90 would accept exactly the transposition this layer exists to catch.
"""

from __future__ import annotations

import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from rapidfuzz import fuzz

from triage import idformats
from triage.candidates import Candidate
from triage.llm.mapping import FieldMapping, Slot
from triage.normalize import (
    Parsed,
    collapse_ws,
    parse_amount,
    parse_currency,
    parse_date,
    parse_identifier,
)
from triage.result import FieldResult, Flag, Source
from triage.schema import (
    CANDIDATE_TYPE,
    DERIVED_FIELDS,
    HEADER_FIELDS,
    LINE_ITEM_FIELDS,
    FieldKind,
    FieldSpec,
    spec_for,
)

FUZZY_THRESHOLD = 90.0
_SEPARATORS = " .,/-"


# --- normalization by field kind ---


def normalize_for(kind: FieldKind, raw: str) -> Parsed | None:
    match kind:
        case FieldKind.DATE:
            return parse_date(raw)
        case FieldKind.MONEY | FieldKind.NUMBER:
            return parse_amount(raw)
        case FieldKind.IDENTIFIER:
            return parse_identifier(raw)
        case FieldKind.CURRENCY:
            return parse_currency(raw) or (Parsed(raw.strip().upper()) if raw.strip() else None)
    return Parsed(collapse_ws(raw)) if raw.strip() else None


def same_value(kind: FieldKind, normalized: str, claimed: str) -> bool:
    """Compare a normalized quote with the value the model claims (which may be formatted)."""
    if kind in (FieldKind.MONEY, FieldKind.NUMBER):
        claimed_parsed = parse_amount(claimed)
        try:
            return claimed_parsed is not None and Decimal(normalized) == Decimal(
                claimed_parsed.value
            )
        except InvalidOperation:
            return False
    other = normalize_for(kind, claimed)
    return other is not None and other.value == normalized


# --- locating quotes ---


def _token_boundaries_ok(text: str, start: int, end: int, *, numeric: bool) -> bool:
    """The match must not be a fragment of a longer word, number or code.

    '234,56' inside '1 234,56' and '01.2026' inside '15.01.2026' are rejected: a truncated
    number that happens to occur in the text is still a wrong number.
    """
    before = text[max(0, start - 2) : start]
    after = text[end : end + 2]
    if before[-1:].isalnum() or after[:1].isalnum():
        return False
    if numeric:
        if len(before) == 2 and before[1] in _SEPARATORS and before[0].isdigit():
            return False
        if len(after) == 2 and after[0] in _SEPARATORS and after[1].isdigit():
            return False
        if len(before) == 2 and before[1] in ".,/-" and before[0].isalnum():
            return False
        if len(after) == 2 and after[0] in ".,/-" and after[1].isalnum():
            return False
    return True


def find_exact(text: str, quote: str, *, numeric: bool) -> tuple[int, int] | None:
    tokens = quote.split()
    if not tokens:
        return None
    pattern = re.compile(r"\s+".join(re.escape(t) for t in tokens))
    for m in pattern.finditer(text):
        if _token_boundaries_ok(text, m.start(), m.end(), numeric=numeric):
            return m.start(), m.end()
    return None


def find_fuzzy(text: str, quote: str) -> tuple[float, int, int]:
    alignment = fuzz.partial_ratio_alignment(collapse_ws(quote).lower(), text.lower())
    if alignment is None:
        return 0.0, 0, 0
    return alignment.score, alignment.dest_start, alignment.dest_end


# --- resolving one slot ---


def resolve_slot(
    path: str, spec_name: str, spec: FieldSpec, slot: Slot, by_id: dict[str, Candidate], text: str
) -> FieldResult:
    result = FieldResult(path=path, spec=spec_name, kind=spec.kind, value=None)
    if slot.is_empty:
        return result
    if slot.candidate:
        _resolve_candidate(result, spec, slot, by_id)
    elif slot.quote:
        if spec.kind is FieldKind.TEXT:
            _resolve_text_quote(result, slot.quote, text)
        else:
            _resolve_typed_quote(result, spec, slot, text)
    else:
        result.value = slot.value
        result.flag(
            "grounding",
            "no_source",
            "value has neither a candidate nor a quote; it cannot be traced to the document",
        )
    return result


def _resolve_candidate(
    result: FieldResult, spec: FieldSpec, slot: Slot, by_id: dict[str, Candidate]
) -> None:
    candidate = by_id.get(slot.candidate or "")
    if candidate is None:
        result.value = slot.value or slot.quote
        result.flag(
            "grounding", "unknown_candidate", f"candidate {slot.candidate!r} does not exist"
        )
        return
    result.value = candidate.value
    result.source = Source(
        via="candidate",
        candidate_id=candidate.id,
        text=candidate.raw,
        start=candidate.start,
        end=candidate.end,
    )
    expected = CANDIDATE_TYPE.get(spec.kind)
    if candidate.type != expected:
        result.flag(
            "grounding",
            "type_mismatch",
            f"{spec.kind.value} field points at a {candidate.type} candidate {candidate.id}",
        )
    elif spec.kind is FieldKind.IDENTIFIER and not set(candidate.subtypes) & spec.id_subtypes:
        result.flag(
            "grounding",
            "type_mismatch",
            f"expects {'/'.join(sorted(spec.id_subtypes))}, candidate {candidate.id} looks like "
            f"{'/'.join(candidate.subtypes)}",
        )
    if "ambiguous" in candidate.flags:
        result.flag(
            "grounding", "ambiguous_format", f"{candidate.raw!r} can be read in more than one way"
        )


def _resolve_text_quote(result: FieldResult, quote: str, text: str) -> None:
    span = find_exact(text, quote, numeric=False)
    if span:
        result.value = collapse_ws(quote)
        result.source = Source(
            via="quote", text=text[span[0] : span[1]], start=span[0], end=span[1]
        )
        return
    score, start, end = find_fuzzy(text, quote)
    if score >= FUZZY_THRESHOLD:
        # The document is the source of truth: keep its spelling, not the model's.
        result.value = collapse_ws(text[start:end])
        result.source = Source(
            via="quote",
            text=text[start:end],
            start=start,
            end=end,
            match="fuzzy",
            score=round(score, 1),
        )
        return
    result.value = collapse_ws(quote)
    result.flag(
        "grounding",
        "quote_not_found",
        f"quote not found in the document (best fuzzy match {score:.0f} < {FUZZY_THRESHOLD:.0f})",
    )


def _resolve_typed_quote(result: FieldResult, spec: FieldSpec, slot: Slot, text: str) -> None:
    quote = slot.quote or ""
    claimed = slot.value
    parsed = normalize_for(spec.kind, quote)
    span = find_exact(text, quote, numeric=True)
    if span is None:
        result.value = claimed or (parsed.value if parsed else quote)
        result.flag(
            "grounding",
            "quote_not_found",
            f"{quote!r} does not occur in the document (numbers, dates and identifiers must "
            "match exactly)",
        )
        return
    result.source = Source(via="quote", text=text[span[0] : span[1]], start=span[0], end=span[1])
    if parsed is None:
        result.value = claimed or quote
        result.flag("grounding", "unparseable", f"{quote!r} is not a valid {spec.kind.value}")
        return
    if claimed is not None and not same_value(spec.kind, parsed.value, claimed):
        result.value = claimed
        result.flag(
            "grounding",
            "value_mismatch",
            f"document says {quote!r} = {parsed.value}, model claims {claimed}",
        )
        return
    result.value = parsed.value
    if parsed.ambiguous:
        result.flag("grounding", "ambiguous_format", f"{quote!r} can be read in more than one way")


# --- whole mapping ---


def resolve(
    mapping: FieldMapping, candidates: list[Candidate], text: str
) -> tuple[list[FieldResult], list[Flag]]:
    """Mapping -> field results with grounding flags, plus document-level flags."""
    by_id = {c.id: c for c in candidates}
    results: list[FieldResult] = []
    for spec in HEADER_FIELDS:
        slot = getattr(mapping.fields, spec.name)
        results.append(resolve_slot(spec.name, spec.name, spec, slot, by_id, text))
    for i, item in enumerate(mapping.line_items):
        for spec in LINE_ITEM_FIELDS:
            path = f"line_items[{i}].{spec.name}"
            slot = getattr(item, spec.name)
            results.append(resolve_slot(path, f"line_items.{spec.name}", spec, slot, by_id, text))
    for spec in DERIVED_FIELDS:
        value = getattr(mapping, spec.name)
        results.append(FieldResult(path=spec.name, spec=spec.name, kind=spec.kind, value=value))

    _check_required(results)
    _check_candidate_reuse(results)
    _check_identifier_uniqueness(results)

    document_flags: list[Flag] = []
    if not mapping.line_items:
        document_flags.append(
            Flag(layer="grounding", code="no_line_items", message="no line items were mapped")
        )
    return results, document_flags


def _check_required(results: list[FieldResult]) -> None:
    for r in results:
        if r.value is None and spec_for(r.spec).required:
            r.flag("grounding", "missing_required", "required field not found in the document")


def _check_candidate_reuse(results: list[FieldResult]) -> None:
    """One printed date or number belongs to one label. Two fields on the same occurrence means
    at least one of them was matched by value rather than by label (the classic way a missing
    contract number gets 'filled')."""
    users: dict[str, list[FieldResult]] = defaultdict(list)
    for r in results:
        if r.kind in (FieldKind.DATE, FieldKind.IDENTIFIER) and r.source and r.source.candidate_id:
            users[r.source.candidate_id].append(r)
    for cid, fields in users.items():
        if len(fields) > 1:
            names = ", ".join(f.path for f in fields)
            for f in fields:
                f.flag(
                    "grounding",
                    "candidate_reused",
                    f"candidate {cid} is used by several fields: {names}",
                )


def _check_identifier_uniqueness(results: list[FieldResult]) -> None:
    by_value: dict[str, list[FieldResult]] = defaultdict(list)
    for r in results:
        if r.kind is FieldKind.IDENTIFIER and isinstance(r.value, str):
            by_value[idformats.compact(r.value)].append(r)
    for value, fields in by_value.items():
        if len(fields) > 1:
            names = ", ".join(f.path for f in fields)
            for f in fields:
                f.flag("grounding", "duplicate_identifier", f"{value} is assigned to {names}")
