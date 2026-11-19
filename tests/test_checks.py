"""Layers 1 and 3 on hand-built field results: schema (types, checksums, cross-field rules) and
arithmetic (line math, sums, totals)."""

from __future__ import annotations

import re

from synth.ids import ru_bank
from triage.checks.arithmetic import check_arithmetic
from triage.checks.schema_check import check_schema
from triage.llm.oracle import transpose_digits
from triage.result import FieldResult
from triage.schema import FieldKind, spec_for

from .conftest import GOLD


def make(values: dict[str, object]) -> dict[str, FieldResult]:
    fields = {}
    for path, value in values.items():
        spec_name = re.sub(r"\[\d+\]", "", path)  # line_items[2].amount -> line_items.amount
        fields[path] = FieldResult(
            path=path, spec=spec_name, kind=spec_for(spec_name).kind, value=value
        )
    return fields


def codes(f: FieldResult) -> set[str]:
    return {fl.code for fl in f.flags}


def lines(*rows: tuple[str, str, str]) -> dict[str, object]:
    out: dict[str, object] = {}
    for i, (qty, price, amount) in enumerate(rows):
        out |= {
            f"line_items[{i}].quantity": qty,
            f"line_items[{i}].unit_price": price,
            f"line_items[{i}].amount": amount,
        }
    return out


# --- arithmetic ---


def test_consistent_invoice_has_no_arithmetic_flags() -> None:
    fields = make(
        lines(("25", "48.00", "1200.00"), ("1", "350.00", "350.00"), ("1.5", "600.00", "900.00"))
        | {"subtotal": "2450.00", "tax_amount": "490.00", "total": "2940.00"}
    )
    check_arithmetic(list(fields.values()))
    assert [f.path for f in fields.values() if f.flags] == []


def test_line_mismatch_flags_the_whole_line() -> None:
    fields = make(lines(("25", "48.00", "1200.00"), ("4", "350.00", "350.00")))
    check_arithmetic(list(fields.values()))
    flagged = {p for p, f in fields.items() if "line_mismatch" in codes(f)}
    assert flagged == {
        "line_items[1].quantity",
        "line_items[1].unit_price",
        "line_items[1].amount",
    }


def test_one_kopeck_rounding_is_tolerated() -> None:
    fields = make(lines(("3", "33.33", "100.00")) | {"subtotal": "100.00", "total": "100.00"})
    check_arithmetic(list(fields.values()))
    assert not any(f.flags for f in fields.values())


def test_transposed_total_breaks_the_equations() -> None:
    fields = make(
        lines(("2", "150000.00", "300000.00"))
        | {"subtotal": "300000.00", "tax_amount": "36000.00", "total": "363000.00"}
    )
    check_arithmetic(list(fields.values()))
    # lines = subtotal, so E2 holds; E3 (subtotal + tax = total) catches the swapped digits
    assert {p for p, f in fields.items() if f.flags} == {"subtotal", "tax_amount", "total"}
    assert codes(fields["total"]) == {"total_mismatch"}


def test_lines_may_sum_to_total_when_prices_include_tax() -> None:
    # 'в том числе НДС': no subtotal, the lines already contain the tax
    fields = make(
        lines(("2", "150000.00", "300000.00")) | {"tax_amount": "32142.86", "total": "300000.00"}
    )
    check_arithmetic(list(fields.values()))
    assert not any(f.flags for f in fields.values())


def test_subtotal_taken_as_total_is_caught() -> None:
    fields = make({"subtotal": "2450.00", "tax_amount": "490.00", "total": "2450.00"})
    check_arithmetic(list(fields.values()))
    assert {p for p, f in fields.items() if f.flags} == {"subtotal", "tax_amount", "total"}


def test_missing_tax_is_a_suspect_when_lines_do_not_match() -> None:
    fields = make(lines(("1", "100.00", "100.00")) | {"tax_amount": None, "total": "120.00"})
    check_arithmetic(list(fields.values()))
    assert "sum_mismatch" in codes(fields["tax_amount"])


# --- schema ---


def test_broken_checksum_is_flagged() -> None:
    kz = GOLD["inv_01_kz_logistics.pdf"]["fields"]
    fields = make({
        "supplier_tax_id": transpose_digits(kz["supplier_tax_id"]),
        "supplier_account": transpose_digits(kz["supplier_account"]),
        "buyer_tax_id": kz["buyer_tax_id"],
    })  # fmt: skip
    check_schema(list(fields.values()))
    assert codes(fields["supplier_tax_id"]) == {"invalid"}
    assert codes(fields["supplier_account"]) == {"invalid"}
    assert fields["buyer_tax_id"].flags == []


def test_correspondent_account_instead_of_settlement_account() -> None:
    bik, settlement, corr = ru_bank("test")
    good = make({"supplier_account": settlement, "supplier_bank_code": bik})
    check_schema(list(good.values()))
    assert good["supplier_account"].flags == []

    wrong = make({"supplier_account": corr, "supplier_bank_code": bik})
    check_schema(list(wrong.values()))
    [flag] = wrong["supplier_account"].flags
    assert flag.code == "checksum"
    assert "correspondent account" in flag.message


def test_russian_account_without_bik_is_unverifiable() -> None:
    _, settlement, _ = ru_bank("test")
    fields = make({"supplier_account": settlement, "supplier_bank_code": None})
    check_schema(list(fields.values()))
    assert codes(fields["supplier_account"]) == {"unverifiable"}


def test_due_date_before_issue_date() -> None:
    fields = make({"issue_date": "2026-02-14", "due_date": "2026-01-15"})
    check_schema(list(fields.values()))
    assert codes(fields["issue_date"]) == codes(fields["due_date"]) == {"due_before_issue"}


def test_three_decimals_in_money_and_unknown_currency() -> None:
    fields = make({"total": "100.005", "currency": "XYZ"})
    check_schema(list(fields.values()))
    assert codes(fields["total"]) == {"invalid"}
    assert codes(fields["currency"]) == {"invalid"}


def test_negative_amount_only_on_a_credit_note() -> None:
    invoice = make({"total": "-100.00", "is_credit_note": False})
    check_schema(list(invoice.values()))
    assert codes(invoice["total"]) == {"negative_amount"}

    credit_note = make({"total": "-100.00", "is_credit_note": True})
    check_schema(list(credit_note.values()))
    assert credit_note["total"].flags == []


def test_field_kinds_resolve_for_line_items() -> None:
    assert make({"line_items[0].amount": "1.00"})["line_items[0].amount"].kind is FieldKind.MONEY
