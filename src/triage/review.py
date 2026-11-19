"""Human review: edits -> edit log -> quality measured from the log.

A review submits final values for any subset of fields; a field that is not submitted keeps its
current value (the extracted one, or the one from an earlier review). Every field of the document
is written to the log with one action:

    corrected   the final value differs from the extracted one
    confirmed   the field was in the review queue and the human kept the extracted value
    accepted    the field was not shown and not touched

Human input goes through the same normalizers and type validators as the model's answers:
"15.01.2026" and "2026-01-15" are the same date, and an IBAN with a wrong check digit is refused.
Empty input clears the field (the fix for a hallucinated contract number is "no value").
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import cache
from typing import Any, Literal

from pydantic import BaseModel, TypeAdapter, ValidationError

from triage import idformats
from triage.checks.grounding import normalize_for
from triage.normalize import collapse_ws
from triage.result import FieldResult, InvoiceResult, Risk
from triage.schema import EXPENSE_CATEGORIES, FieldKind, Invoice, LineItem, spec_for

Action = Literal["corrected", "confirmed", "accepted"]
Value = str | bool | None


class EditEntry(BaseModel):
    document_id: str
    path: str
    spec: str
    kind: FieldKind
    extracted: Value
    final: Value
    action: Action
    needs_review: bool
    risk: Risk
    flags: list[str]  # "layer:code", e.g. "grounding:quote_not_found"
    review_id: int | None = None  # set by storage
    reviewed_at: datetime | None = None


class EditError(ValueError):
    """Submitted values that cannot be accepted, by field path."""

    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("; ".join(f"{path}: {message}" for path, message in errors.items()))
        self.errors = errors


# --- one value ---


@cache
def _adapter(spec_name: str) -> TypeAdapter[Any]:
    """The schema layer's type for this field: format, range and checksum validators."""
    if spec_name.startswith("line_items."):
        annotation = LineItem.model_fields[spec_name.split(".", 1)[1]].annotation
    else:
        annotation = Invoice.model_fields[spec_name].annotation
    return TypeAdapter(annotation)


def normalize_edit(spec_name: str, raw: object) -> Value:
    """Human input -> the value form the pipeline uses. Raises ValueError with a readable reason."""
    spec = spec_for(spec_name)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if spec_name == "is_credit_note":
        if isinstance(raw, bool):
            return raw
        raise ValueError("expected true or false")
    if not isinstance(raw, str):
        raise ValueError("expected a string")
    if spec_name == "expense_category":
        if raw not in EXPENSE_CATEGORIES:
            raise ValueError(f"expected one of: {', '.join(EXPENSE_CATEGORIES)}")
        return raw
    parsed = normalize_for(spec.kind, raw)
    if parsed is None:
        raise ValueError(f"cannot read {raw!r} as {spec.kind.value}")
    if parsed.ambiguous:
        raise ValueError(
            f"{raw!r} can be read in more than one way; write dates as DD.MM.YYYY or YYYY-MM-DD "
            "and amounts with a decimal part"
        )
    try:
        _adapter(spec_name).validate_python(parsed.value)
    except ValidationError as e:
        raise ValueError(e.errors()[0]["msg"].removeprefix("Value error, ")) from e
    return parsed.value


def same_value(kind: FieldKind, a: Value, b: Value) -> bool:
    """Equal as values: '1200.0' == '1200.00'. Text is compared exactly (after whitespace), so a
    human fixing only the case of a name counts as a correction."""
    if a is None or b is None:
        return a is None and b is None
    if kind in (FieldKind.MONEY, FieldKind.NUMBER):
        try:
            return Decimal(str(a)) == Decimal(str(b))
        except InvalidOperation:
            return False
    if kind is FieldKind.TEXT:
        return collapse_ws(str(a)) == collapse_ws(str(b))
    if kind is FieldKind.IDENTIFIER:
        return idformats.compact(str(a)) == idformats.compact(str(b))
    return a == b


# --- one review ---


def final_values(entries: list[EditEntry]) -> dict[str, Value]:
    return {e.path: e.final for e in entries}


def build_edit_log(
    document_id: str,
    result: InvoiceResult,
    submitted: dict[str, Any],
    previous: dict[str, Value] | None = None,
) -> list[EditEntry]:
    """Diff the human's final values against the extraction. Raises EditError on bad input."""
    by_path = {f.path: f for f in result.fields}
    errors: dict[str, str] = {}
    normalized: dict[str, Value] = {}
    for path, raw in submitted.items():
        field = by_path.get(path)
        if field is None:
            errors[path] = "no such field in this document"
            continue
        try:
            normalized[path] = normalize_edit(field.spec, raw)
        except ValueError as e:
            errors[path] = str(e)
    if errors:
        raise EditError(errors)

    # Not submitted: keeps the value from an earlier review, else the extracted one.
    current = {**(previous or {}), **normalized}
    return [_entry(document_id, f, current.get(f.path, f.value)) for f in result.fields]


def _entry(document_id: str, f: FieldResult, final: Value) -> EditEntry:
    if not same_value(f.kind, f.value, final):
        action: Action = "corrected"
    elif f.needs_review:
        action = "confirmed"
    else:
        action = "accepted"
    return EditEntry(
        document_id=document_id,
        path=f.path,
        spec=f.spec,
        kind=f.kind,
        extracted=f.value,
        final=final,
        action=action,
        needs_review=f.needs_review,
        risk=f.risk,
        flags=[f"{fl.layer}:{fl.code}" for fl in f.flags],
    )


# --- quality from the log ---


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def quality_metrics(entries: list[EditEntry]) -> dict[str, Any]:
    """Quality as seen by reviewers (pass the latest review of each document).

    A reviewer checks the review queue, not the accepted fields, so 'corrected_outside_queue' is a
    lower bound on silent errors. The exact number needs a gold annotation: `triage eval`.
    """
    shown = [e for e in entries if e.needs_review]
    hidden = [e for e in entries if not e.needs_review]
    flagged_shown = [e for e in shown if e.flags]
    unflagged_shown = [e for e in shown if not e.flags]

    def corrected(items: list[EditEntry]) -> int:
        return sum(e.action == "corrected" for e in items)

    by_check: dict[str, Counter[str]] = defaultdict(Counter)
    for e in entries:
        for code in e.flags:
            by_check[code]["fired"] += 1
            by_check[code]["corrected"] += e.action == "corrected"
            by_check[code]["shown"] += e.needs_review

    by_field: dict[str, Counter[str]] = defaultdict(Counter)
    for e in entries:
        by_field[e.spec]["fields"] += 1
        by_field[e.spec]["shown"] += e.needs_review
        by_field[e.spec]["flagged"] += bool(e.flags)
        by_field[e.spec]["corrected"] += e.action == "corrected"

    return {
        "documents": len({e.document_id for e in entries}),
        "fields": len(entries),
        "shown": len(shown),
        "review_load": _rate(len(shown), len(entries)),
        "corrected": corrected(entries),
        "corrected_in_queue": corrected(shown),
        # caught by a check: flagged, shown, and the human changed it
        "caught_by_checks": corrected(flagged_shown),
        # caught only because the policy always shows the field (high risk, no flag)
        "caught_by_policy": corrected(unflagged_shown),
        "false_alarms": len(flagged_shown) - corrected(flagged_shown),
        "flag_precision": _rate(corrected(flagged_shown), len(flagged_shown)),
        "corrected_outside_queue": corrected(hidden),
        "by_check": {k: dict(v) for k, v in sorted(by_check.items())},
        "by_field": {k: dict(v) for k, v in sorted(by_field.items())},
    }
