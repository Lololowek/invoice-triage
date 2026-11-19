"""The whole pipeline on the synthetic PDFs, with the oracle mapper (gold annotation) in place of
the model. Two properties:
- with a correct mapping the checks are silent: no false alarms, only high-risk fields reviewed;
- each injected model error ends up in the review queue."""

from __future__ import annotations

from pathlib import Path

import pytest

from triage.candidates import extract_candidates
from triage.evaluate import compare
from triage.llm.oracle import OracleMapper
from triage.pdf_text import extract_text
from triage.pipeline import process_pdf
from triage.policy import RiskPolicy
from triage.result import InvoiceResult

from .conftest import GOLD, INVOICES, UK_INVOICE

PDFS = sorted(INVOICES.glob("*.pdf"))


def oracle_run(pdf: Path, policy: RiskPolicy, *inject: str) -> InvoiceResult:
    return process_pdf(pdf, OracleMapper(GOLD[pdf.name], inject=inject), policy)


def codes(result: InvoiceResult, path: str) -> set[str]:
    f = result.field(path)
    assert f is not None
    return {fl.code for fl in f.flags}


def test_all_fifteen_invoices_are_annotated() -> None:
    assert len(PDFS) == 15
    assert {p.name for p in PDFS} == set(GOLD)


def test_text_extraction_keeps_columns_apart() -> None:
    assert extract_text(INVOICES / "inv_07_uk_software.pdf") == UK_INVOICE


@pytest.mark.parametrize("pdf", PDFS, ids=lambda p: p.stem)
def test_correct_mapping_raises_no_flags(pdf: Path, policy: RiskPolicy) -> None:
    result = oracle_run(pdf, policy)
    assert [f.path for f in result.fields if f.flags] == []
    assert result.document_flags == []
    assert [o.path for o in compare(result, GOLD[pdf.name]) if not o.correct] == []
    assert result.line_items_source == "code"
    assert {f.path for f in result.review_queue} == {
        "supplier_account",
        "supplier_bank_code",
        "total",
    }


def test_injected_hallucination_is_reviewed(policy: RiskPolicy) -> None:
    # inv_06 has no contract; the "model" invents one
    pdf = INVOICES / "inv_06_ru_marketing.pdf"
    assert GOLD[pdf.name]["fields"]["contract_number"] is None
    result = oracle_run(pdf, policy, "hallucinate:contract_number=ДГ-2026/017")
    assert codes(result, "contract_number") == {"quote_not_found"}
    assert result.field("contract_number").needs_review  # type: ignore[union-attr]


def test_injected_transposition_is_reviewed(policy: RiskPolicy) -> None:
    result = oracle_run(INVOICES / "inv_07_uk_software.pdf", policy, "transpose:total")
    assert {"value_mismatch", "total_mismatch"} <= codes(result, "total")


def test_correspondent_account_picked_instead_of_settlement_account(policy: RiskPolicy) -> None:
    pdf = INVOICES / "inv_04_ru_consulting.pdf"
    corr = next(
        c for c in extract_candidates(extract_text(pdf)) if c.value.startswith("30101")
    )  # к/с accounts start with 30101
    result = oracle_run(pdf, policy, f"pick:supplier_account={corr.id}")
    assert "checksum" in codes(result, "supplier_account")


def test_due_date_picked_as_issue_date_is_caught_by_reuse(policy: RiskPolicy) -> None:
    # Both fields then point at one printed date, which belongs to one label only.
    pdf = INVOICES / "inv_07_uk_software.pdf"
    due = next(c for c in extract_candidates(UK_INVOICE) if c.raw == "14 Feb 2026")
    result = oracle_run(pdf, policy, f"pick:issue_date={due.id}")
    assert "candidate_reused" in codes(result, "issue_date")
