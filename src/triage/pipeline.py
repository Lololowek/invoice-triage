"""PDF -> text -> candidates -> mapping (model) -> grounding -> schema -> arithmetic -> policy."""

from __future__ import annotations

from pathlib import Path

from triage.candidates import extract_candidates
from triage.checks.arithmetic import check_arithmetic
from triage.checks.grounding import resolve
from triage.checks.schema_check import check_schema
from triage.llm.mapper import Mapper
from triage.pdf_text import extract_text
from triage.policy import RiskPolicy
from triage.result import InvoiceResult


def process_text(
    text: str, mapper: Mapper, policy: RiskPolicy, document: str = "<text>"
) -> InvoiceResult:
    candidates = extract_candidates(text)
    mapping = mapper.map(text, candidates)
    fields, document_flags = resolve(mapping, candidates, text)
    check_schema(fields)
    check_arithmetic(fields)
    for f in fields:
        policy.apply(f)
    return InvoiceResult(
        document=document,
        mapper=mapper.name,
        fields=fields,
        document_flags=document_flags,
        candidates=candidates,
        text=text,
    )


def process_pdf(path: str | Path, mapper: Mapper, policy: RiskPolicy) -> InvoiceResult:
    path = Path(path)
    return process_text(extract_text(path), mapper, policy, document=path.name)
