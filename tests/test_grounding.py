"""Layer 2: every value must be traceable to the document."""

from typing import Any

from triage.candidates import extract_candidates
from triage.checks.grounding import resolve
from triage.llm.mapping import FieldMapping, Slot, parse_mapping
from triage.result import FieldResult

from .conftest import UK_INVOICE, uk_compact_answer

CANDS = extract_candidates(UK_INVOICE)


def grounded(mapping: FieldMapping) -> dict[str, FieldResult]:
    fields, _ = resolve(mapping, CANDS, UK_INVOICE)
    return {f.path: f for f in fields}


def answer(**overrides: Any) -> dict[str, FieldResult]:
    return grounded(parse_mapping(uk_compact_answer(**overrides)))


def codes(f: FieldResult) -> set[str]:
    return {fl.code for fl in f.flags}


def test_correct_answer_raises_no_flags() -> None:
    fields = answer()
    assert {path: codes(f) for path, f in fields.items() if f.flags} == {}
    assert fields["total"].value == "2940.00"
    assert fields["total"].source is not None
    assert fields["total"].source.text == "2,940.00"


def test_hallucinated_contract_number_is_flagged() -> None:
    f = answer(contract_number="ДГ-2026/017")["contract_number"]
    assert codes(f) == {"quote_not_found"}
    assert f.value == "ДГ-2026/017"  # the claim is kept for the reviewer, with the flag


def test_transposed_total_as_quote_is_flagged() -> None:
    # compact format: a string that is not a candidate id is a quote; this one is not printed
    assert codes(answer(total="2,904.00")["total"]) == {"quote_not_found"}


def test_transposed_value_with_a_correct_quote_is_flagged() -> None:
    # full format: the model quotes the right text but claims a different number
    mapping = parse_mapping(uk_compact_answer())
    mapping.fields.total = Slot(quote="2,940.00", value="2490.00")
    f = grounded(mapping)["total"]
    assert codes(f) == {"value_mismatch"}
    assert f.value == "2490.00"


def test_truncated_number_does_not_match_inside_a_longer_one() -> None:
    # '940.00' occurs inside '2,940.00' but is a different number
    assert codes(answer(total="940.00")["total"]) == {"quote_not_found"}


def test_unknown_candidate_id() -> None:
    f = answer(total="A99")["total"]
    assert codes(f) == {"unknown_candidate", "missing_required"}  # no candidate, so no value
    assert f.value is None


def test_candidate_of_the_wrong_type() -> None:
    date_id = next(c.id for c in CANDS if c.raw == "15 Jan 2026")
    vat_id = next(c.id for c in CANDS if c.raw == "GB947145946")
    fields = answer(total=date_id, supplier_account=vat_id)
    assert "type_mismatch" in codes(fields["total"])
    assert "type_mismatch" in codes(fields["supplier_account"])  # a VAT number is not an IBAN


def test_missing_required_field() -> None:
    f = answer(supplier_name=None)["supplier_name"]
    assert codes(f) == {"missing_required"}


def test_missing_optional_field_is_not_flagged() -> None:
    assert answer(contract_number=None)["contract_number"].flags == []


def test_text_quote_matches_fuzzily_and_keeps_the_document_spelling() -> None:
    f = answer(supplier_name="BRIGHTLINE ANALYTICS LTD")["supplier_name"]
    assert f.flags == []
    assert f.value == "Brightline Analytics Ltd"
    assert f.source is not None
    assert f.source.match == "fuzzy"


def test_text_not_in_the_document() -> None:
    assert codes(answer(supplier_name="Acme Holdings GmbH")["supplier_name"]) == {"quote_not_found"}


def test_text_quote_across_a_column_gap() -> None:
    # "INVOICE  Brightline..." is two cells: the quote absorbed the title
    f = answer(supplier_name="INVOICE Brightline Analytics Ltd")["supplier_name"]
    assert "quote_spans_columns" in codes(f)


def test_one_date_used_for_two_fields() -> None:
    issue = next(c.id for c in CANDS if c.raw == "15 Jan 2026")
    fields = answer(due_date=issue)
    assert "candidate_reused" in codes(fields["issue_date"])
    assert "candidate_reused" in codes(fields["due_date"])


def test_order_number_as_contract_number_is_a_known_blind_spot() -> None:
    # PO-7731 is a real, well-formed document number: grounding cannot tell it from a contract.
    po = next(c.id for c in CANDS if c.raw == "PO-7731")
    assert answer(contract_number=po)["contract_number"].flags == []


def test_swapped_tax_ids_are_flagged_by_party_proximity() -> None:
    supplier_vat = next(c.id for c in CANDS if c.raw == "GB947145946")
    buyer_vat = next(c.id for c in CANDS if c.raw == "GB451851468")
    fields = answer(supplier_tax_id=buyer_vat, buyer_tax_id=supplier_vat)
    assert "party_mismatch" in codes(fields["supplier_tax_id"])
    assert "party_mismatch" in codes(fields["buyer_tax_id"])


def test_no_line_items_is_a_document_flag() -> None:
    _, document_flags = resolve(parse_mapping(uk_compact_answer()), CANDS, UK_INVOICE)
    assert [f.code for f in document_flags] == ["no_line_items"]
