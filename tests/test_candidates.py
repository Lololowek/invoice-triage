from triage.candidates import extract_candidates

from .conftest import UK_INVOICE


def by_raw(text: str) -> dict[str, tuple[str, str, tuple[str, ...]]]:
    return {c.raw: (c.type, c.value, tuple(c.subtypes)) for c in extract_candidates(text)}


def test_every_span_points_at_its_raw_text() -> None:
    for c in extract_candidates(UK_INVOICE):
        assert UK_INVOICE[c.start : c.end] == c.raw


def test_ids_are_typed_and_numbered_in_order() -> None:
    cands = extract_candidates(UK_INVOICE)
    for prefix, kind in {"D": "date", "A": "amount", "I": "identifier", "C": "currency"}.items():
        ids = [c.id for c in cands if c.type == kind]
        assert ids == [f"{prefix}{i}" for i in range(1, len(ids) + 1)]


def test_uk_invoice_candidates() -> None:
    found = by_raw(UK_INVOICE)
    assert found["15 Jan 2026"] == ("date", "2026-01-15", ())
    assert found["1,200.00"] == ("amount", "1200.00", ())
    assert found["2,940.00"] == ("amount", "2940.00", ())
    assert found["GB947145946"] == ("identifier", "GB947145946", ("vat",))
    assert found["GB81 DHBS 3169 3923 3682 89"] == (
        "identifier",
        "GB81DHBS31693923368289",
        ("iban",),
    )
    assert found["HNWVGBKU"] == ("identifier", "HNWVGBKU", ("bic",))
    assert found["MSA-2025-031"] == ("identifier", "MSA-2025-031", ("doc_number",))


def test_percent_is_not_an_amount() -> None:
    found = by_raw("VAT (20%)  490.00")
    assert "20" not in found
    assert found["490.00"][0] == "amount"


def test_date_digits_are_not_amounts() -> None:
    found = by_raw("Дата: 15.01.2026  Сумма: 1 250 000,00")
    assert found["15.01.2026"] == ("date", "2026-01-15", ())
    assert found["1 250 000,00"] == ("amount", "1250000.00", ())
    assert {kind for kind, _, _ in found.values()} == {"date", "amount"}


def test_russian_text_date_and_amount_with_spaces() -> None:
    found = by_raw("Счёт № 45 от «15» января 2026 г.  Итого:  362 000,00 тенге")
    assert found["«15» января 2026"][1] == "2026-01-15"  # "г." stays outside the span
    assert found["45"] == ("identifier", "45", ("doc_number",))
    assert found["362 000,00"][1] == "362000.00"
    assert found["тенге"] == ("currency", "KZT", ())


def test_ambiguous_amount_is_marked() -> None:
    cands = [c for c in extract_candidates("Qty: 1,234") if c.type == "amount"]
    assert len(cands) == 1
    assert "ambiguous" in cands[0].flags
