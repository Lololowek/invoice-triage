"""The model is mocked: ScriptedClient returns prepared answers. What is tested is everything around
the model - settings, the response schema, parsing, retry - and what the pipeline does with a
wrong answer: a hallucinated value and a transposition must end up in front of a human."""

from __future__ import annotations

import json

import pytest

from triage.candidates import extract_candidates
from triage.llm.client import ConfigError, LLMSettings
from triage.llm.mapper import LLMMapper, MappingError
from triage.llm.mapping import parse_mapping, response_json_schema
from triage.pipeline import process_text
from triage.policy import RiskPolicy
from triage.result import InvoiceResult

from .conftest import UK_INVOICE, ScriptedClient, cid, uk_compact_answer

CANDS = extract_candidates(UK_INVOICE)


def run(client: ScriptedClient, policy: RiskPolicy) -> InvoiceResult:
    return process_text(UK_INVOICE, LLMMapper(client), policy, document="uk.pdf")


def codes(result: InvoiceResult, path: str) -> set[str]:
    f = result.field(path)
    assert f is not None
    return {fl.code for fl in f.flags}


# --- settings ---


def test_settings_require_a_model() -> None:
    with pytest.raises(ConfigError, match="LLM_MODEL"):
        LLMSettings.from_env({})


def test_settings_from_env() -> None:
    s = LLMSettings.from_env({
        "LLM_MODEL": "invoice-4b",
        "LLM_BASE_URL": "http://localhost:11434/v1",
        "LLM_EXTRA_BODY": '{"reasoning_effort": "none"}',
        "LLM_TIMEOUT_S": "600",
    })  # fmt: skip
    assert s.model == "invoice-4b"
    assert s.extra_body == {"reasoning_effort": "none"}
    assert s.timeout_s == 600
    assert s.answer_format == "compact"
    assert s.response_format == "json_schema"


@pytest.mark.parametrize(
    "env",
    [
        {"LLM_MODEL": "m", "LLM_EXTRA_BODY": "{not json"},
        {"LLM_MODEL": "m", "LLM_RESPONSE_FORMAT": "xml"},
        {"LLM_MODEL": "m", "LLM_ANSWER_FORMAT": "verbose"},
    ],
)
def test_settings_reject_bad_values(env: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        LLMSettings.from_env(env)


# --- response schema: the model can only pick ids of the right type ---


def test_compact_schema_enumerates_allowed_candidates() -> None:
    props = response_json_schema("compact", CANDS)["properties"]
    total_ids = props["total"]["anyOf"][0]["enum"]
    assert all(i.startswith("A") for i in total_ids)
    assert props["supplier_account"]["anyOf"][0]["enum"] == [
        cid(CANDS, "GB81 DHBS 3169 3923 3682 89")
    ]
    assert props["supplier_name"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}


def test_field_without_candidates_of_its_type_can_only_be_null() -> None:
    props = response_json_schema("compact", extract_candidates("Total  100.00"))["properties"]
    assert props["issue_date"] == {"type": "null"}


def test_schema_without_line_items() -> None:
    assert (
        "line_items"
        not in response_json_schema("compact", CANDS, with_line_items=False)["properties"]
    )


# --- parsing what small models actually return ---


def test_parse_tolerates_think_blocks_fences_and_echoed_markers() -> None:
    raw = "<think>hmm</think>\n```json\n" + uk_compact_answer(total="[[A16]]") + "\n```"
    assert parse_mapping(raw).fields.total.candidate == "A16"


def test_parse_full_format() -> None:
    data = json.loads(uk_compact_answer())
    full = {
        "fields": {k: ({"candidate": None, "quote": None, "value": None} if v is None else v)
                   for k, v in data.items()
                   if k not in ("line_items", "expense_category", "is_credit_note")},
        "line_items": [],
        "expense_category": "software",
        "is_credit_note": False,
    }  # fmt: skip
    mapping = parse_mapping(json.dumps(full))
    assert mapping.fields.supplier_name.quote == "Brightline Analytics Ltd"


# --- retry ---


def test_retry_once_with_the_error() -> None:
    client = ScriptedClient("not json at all", uk_compact_answer())
    mapping = LLMMapper(client).map(UK_INVOICE, CANDS)
    assert mapping.fields.total.candidate == cid(CANDS, "2,940.00")
    retry_messages = client.requests[1]["messages"]
    assert retry_messages[-2] == {"role": "assistant", "content": "not json at all"}
    assert "not valid JSON" in retry_messages[-1]["content"]


def test_give_up_after_two_bad_answers() -> None:
    bad_category = '{"expense_category": "groceries"}'  # valid JSON, not a valid answer
    with pytest.raises(MappingError, match="after 2 attempts"):
        LLMMapper(ScriptedClient("{", bad_category)).map(UK_INVOICE, CANDS)


# --- end to end with a mocked model ---


def test_correct_answer_shows_only_high_risk_fields(policy: RiskPolicy) -> None:
    client = ScriptedClient(uk_compact_answer())
    result = run(client, policy)
    assert result.line_items_source == "code"
    assert [f.path for f in result.fields if f.flags] == []
    assert [f.path for f in result.review_queue] == [
        "supplier_account",
        "supplier_bank_code",
        "total",
    ]
    # rows were found by code, so the model was not asked for them
    assert "line_items" not in client.requests[0]["schema"]["properties"]


def test_hallucinated_contract_number_goes_to_review(policy: RiskPolicy) -> None:
    result = run(ScriptedClient(uk_compact_answer(contract_number="ДГ-2026/017")), policy)
    f = result.field("contract_number")
    assert f is not None and f.needs_review
    assert codes(result, "contract_number") == {"quote_not_found"}


def test_transposed_total_goes_to_review_with_arithmetic_evidence(policy: RiskPolicy) -> None:
    result = run(ScriptedClient(uk_compact_answer(total="2,490.00")), policy)
    # '2,490.00' is not printed anywhere, and subtotal + tax no longer equals it
    assert codes(result, "total") == {"quote_not_found", "total_mismatch"}


def test_subtotal_picked_as_total_is_caught_by_arithmetic(policy: RiskPolicy) -> None:
    # an existing, well-formed candidate: only arithmetic can tell it is the wrong one
    result = run(ScriptedClient(uk_compact_answer(total=cid(CANDS, "2,450.00"))), policy)
    assert "total_mismatch" in codes(result, "total")
    assert result.field("subtotal").needs_review  # type: ignore[union-attr]
