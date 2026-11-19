from pathlib import Path

from triage.llm.oracle import OracleMapper
from triage.pipeline import process_pdf
from triage.policy import RiskPolicy
from triage.review import build_edit_log
from triage.storage import SQLiteRepository

from .conftest import GOLD, INVOICES


def test_documents_and_edit_log_round_trip(tmp_path: Path, policy: RiskPolicy) -> None:
    repo = SQLiteRepository(tmp_path / "sub" / "triage.sqlite3")
    pdf = INVOICES / "inv_07_uk_software.pdf"
    result = process_pdf(pdf, OracleMapper(GOLD[pdf.name]), policy)

    doc = repo.add_document(pdf.name, result)
    stored = repo.get_document(doc.id)
    assert stored is not None
    assert stored.result == result
    assert stored.reviewed_at is None and stored.final_values is None

    [summary] = repo.list_documents()
    assert (summary.id, summary.to_review, summary.flagged) == (doc.id, 3, 0)

    first = build_edit_log(doc.id, result, {"payment_terms": "Net 45"})
    repo.add_review(doc.id, first)
    second = build_edit_log(doc.id, result, {"contract_number": None}, {"payment_terms": "Net 45"})
    reviewed_at = repo.add_review(doc.id, second)

    log = repo.edit_log(doc.id)  # latest review only
    assert len(log) == len(result.fields)
    assert {e.review_id for e in log} == {2}
    assert {e.path for e in log if e.action == "corrected"} == {"payment_terms", "contract_number"}
    assert next(e for e in log if e.path == "is_credit_note").final is False  # JSON types survive

    stored = repo.get_document(doc.id)
    assert stored is not None
    assert stored.reviewed_at == reviewed_at
    assert stored.final_values is not None
    assert stored.final_values["payment_terms"] == "Net 45"
    assert stored.final_values["contract_number"] is None


def test_edit_log_across_documents_takes_the_latest_review_each(
    tmp_path: Path, policy: RiskPolicy
) -> None:
    repo = SQLiteRepository(tmp_path / "triage.sqlite3")
    ids = []
    for name in ("inv_07_uk_software.pdf", "inv_01_kz_logistics.pdf"):
        result = process_pdf(INVOICES / name, OracleMapper(GOLD[name]), policy)
        doc = repo.add_document(name, result)
        repo.add_review(doc.id, build_edit_log(doc.id, result, {}))
        repo.add_review(doc.id, build_edit_log(doc.id, result, {}))
        ids.append(doc.id)
    log = repo.edit_log()
    assert {e.document_id for e in log} == set(ids)
    assert len({e.review_id for e in log}) == 2


def test_unknown_document(tmp_path: Path) -> None:
    assert SQLiteRepository(tmp_path / "triage.sqlite3").get_document("nope") is None
