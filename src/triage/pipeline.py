"""PDF -> text -> candidates -> line items (code) -> mapping (model) -> grounding -> schema ->
arithmetic -> policy."""

from __future__ import annotations

from pathlib import Path

from triage.candidates import extract_candidates
from triage.checks.arithmetic import check_arithmetic
from triage.checks.grounding import resolve
from triage.checks.schema_check import check_schema
from triage.line_items import ParsedRow, find_line_items
from triage.llm.mapper import Mapper
from triage.llm.mapping import LineItemSlots, Slot
from triage.pdf_text import extract_text
from triage.policy import RiskPolicy
from triage.result import InvoiceResult


def process_text(
    text: str, mapper: Mapper, policy: RiskPolicy, document: str = "<text>"
) -> InvoiceResult:
    candidates = extract_candidates(text)
    rows = find_line_items(text, candidates)
    mapping = mapper.map(text, candidates, with_line_items=not rows)
    if rows:
        mapping.line_items = [_slots(row) for row in rows]
    fields, document_flags = resolve(mapping, candidates, text)
    check_schema(fields)
    check_arithmetic(fields)
    for f in fields:
        policy.apply(f)
    return InvoiceResult(
        document=document,
        mapper=mapper.name,
        line_items_source="code" if rows else "model",
        fields=fields,
        document_flags=document_flags,
        candidates=candidates,
        text=text,
    )


def _slots(row: ParsedRow) -> LineItemSlots:
    """Rows found by code go through the same grounding and checks as the model's answers."""
    return LineItemSlots(
        description=Slot(quote=row.description),
        quantity=Slot(candidate=row.quantity.id),
        unit_price=Slot(candidate=row.unit_price.id),
        amount=Slot(candidate=row.amount.id),
    )


def process_pdf(path: str | Path, mapper: Mapper, policy: RiskPolicy) -> InvoiceResult:
    path = Path(path)
    return process_text(extract_text(path), mapper, policy, document=path.name)
