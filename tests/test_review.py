"""Human edits -> edit log -> metrics."""

from __future__ import annotations

import pytest

from triage.llm.mapper import LLMMapper
from triage.pipeline import process_text
from triage.policy import RiskPolicy
from triage.result import InvoiceResult
from triage.review import EditError, build_edit_log, normalize_edit, quality_metrics

from .conftest import UK_INVOICE, ScriptedClient, uk_compact_answer


@pytest.fixture
def hallucinated(policy: RiskPolicy) -> InvoiceResult:
    """UK invoice where the 'model' invented a contract number and the total is right."""
    answer = uk_compact_answer(contract_number="ДГ-2026/017")
    return process_text(UK_INVOICE, LLMMapper(ScriptedClient(answer)), policy, "uk.pdf")


def actions(entries: list) -> dict[str, str]:  # type: ignore[type-arg]
    return {e.path: e.action for e in entries if e.action != "accepted"}


@pytest.mark.parametrize(
    ("spec", "raw", "value"),
    [
        ("issue_date", "15.01.2026", "2026-01-15"),
        ("issue_date", "2026-01-15", "2026-01-15"),
        ("total", "2 940,00", "2940.00"),
        ("total", "2,940.00", "2940.00"),
        ("supplier_account", "gb81 dhbs 3169 3923 3682 89", "GB81DHBS31693923368289"),
        ("supplier_name", "  Brightline   Analytics Ltd ", "Brightline Analytics Ltd"),
        ("contract_number", "", None),
        ("contract_number", None, None),
        ("is_credit_note", True, True),
        ("expense_category", "software", "software"),
        ("line_items.quantity", "1.5", "1.5"),
    ],
)
def test_human_input_is_normalized_like_the_model_output(
    spec: str, raw: object, value: object
) -> None:
    assert normalize_edit(spec, raw) == value


@pytest.mark.parametrize(
    ("spec", "raw", "reason"),
    [
        ("issue_date", "31.02.2026", "cannot read"),
        ("issue_date", "03/04/2026", "more than one way"),
        ("total", "1,234", "more than one way"),
        ("total", "100.0051", "2 decimal places"),
        ("supplier_account", "GB82 DHBS 3169 3923 3682 89", "checksum"),
        ("currency", "XYZ", "ISO 4217"),
        ("is_credit_note", "yes", "true or false"),
        ("expense_category", "groceries", "one of"),
        ("line_items.quantity", "0", "non-zero"),
    ],
)
def test_bad_human_input_is_refused_with_a_reason(spec: str, raw: object, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        normalize_edit(spec, raw)


def test_clearing_a_hallucinated_value_is_a_correction(hallucinated: InvoiceResult) -> None:
    entries = build_edit_log("d1", hallucinated, {"contract_number": ""})
    assert actions(entries) == {
        "contract_number": "corrected",
        "supplier_account": "confirmed",
        "supplier_bank_code": "confirmed",
        "total": "confirmed",
    }
    entry = next(e for e in entries if e.path == "contract_number")
    assert (entry.extracted, entry.final) == ("ДГ-2026/017", None)
    assert entry.flags == ["grounding:quote_not_found"]
    assert len(entries) == len(hallucinated.fields)


def test_same_value_in_another_format_is_not_a_correction(hallucinated: InvoiceResult) -> None:
    entries = build_edit_log("d1", hallucinated, {"total": "2 940,00", "issue_date": "15.01.2026"})
    assert actions(entries)["total"] == "confirmed"
    assert "issue_date" not in actions(entries)


def test_flagged_field_kept_as_is_counts_as_a_false_alarm(hallucinated: InvoiceResult) -> None:
    metrics = quality_metrics(build_edit_log("d1", hallucinated, {}))
    assert metrics["false_alarms"] == 1
    assert metrics["flag_precision"] == 0.0


def test_bad_input_reports_every_field(hallucinated: InvoiceResult) -> None:
    with pytest.raises(EditError) as e:
        build_edit_log("d1", hallucinated, {"total": "abc", "no_such_field": "x"})
    assert set(e.value.errors) == {"total", "no_such_field"}


def test_a_second_review_keeps_the_first_corrections(hallucinated: InvoiceResult) -> None:
    first = build_edit_log("d1", hallucinated, {"contract_number": None})
    previous = {e.path: e.final for e in first}
    second = build_edit_log("d1", hallucinated, {"payment_terms": "Net 45"}, previous)
    assert actions(second)["contract_number"] == "corrected"
    assert actions(second)["payment_terms"] == "corrected"


def test_metrics(hallucinated: InvoiceResult) -> None:
    entries = build_edit_log(
        "d1",
        hallucinated,
        {
            "contract_number": None,  # flagged and wrong: caught by a check
            "total": "2 950,00",  # high risk, no flag: caught by the policy
            "payment_terms": "Net 45",  # low risk, never shown: found outside the queue
        },
    )
    m = quality_metrics(entries)
    assert m["documents"] == 1
    assert m["fields"] == len(hallucinated.fields)
    assert m["shown"] == 4  # contract_number + 3 high-risk fields
    assert m["corrected"] == 3
    assert m["caught_by_checks"] == 1
    assert m["caught_by_policy"] == 1
    assert m["corrected_outside_queue"] == 1
    assert m["false_alarms"] == 0
    assert m["flag_precision"] == 1.0
    assert m["by_check"]["grounding:quote_not_found"] == {"fired": 1, "corrected": 1, "shown": 1}
    assert m["by_field"]["total"]["corrected"] == 1


def test_metrics_on_an_empty_log() -> None:
    m = quality_metrics([])
    assert m["fields"] == 0
    assert m["review_load"] is None
    assert m["flag_precision"] is None
