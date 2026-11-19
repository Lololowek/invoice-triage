from triage.candidates import extract_candidates
from triage.line_items import find_line_items

from .conftest import UK_INVOICE


def rows(text: str) -> list[tuple[str, str, str, str]]:
    found = find_line_items(text, extract_candidates(text))
    return [(r.description, r.quantity.value, r.unit_price.value, r.amount.value) for r in found]


def test_uk_invoice_rows() -> None:
    assert rows(UK_INVOICE) == [
        ("Analytics Platform licence, Jan", "25", "48.00", "1200.00"),
        ("Premium support, Jan", "1", "350.00", "350.00"),
        ("Onboarding workshop (remote)", "1.5", "600.00", "900.00"),
    ]


def test_row_number_and_numbers_inside_the_description_are_skipped() -> None:
    text = "1  Плита 800x1000 мм, 12 шт. в упаковке  4  12 500,00  50 000,00"
    assert rows(text) == [("Плита 800x1000 мм, 12 шт. в упаковке", "4", "12500.00", "50000.00")]


def test_totals_lines_are_not_rows() -> None:
    # three amounts, but no quantity × price = amount and no text cell before them
    assert rows("Итого:  300 000,00  36 000,00  336 000,00") == []


def test_prices_without_decimals_are_left_to_the_model() -> None:
    assert rows("Услуги  2  150  300") == []


def test_quantity_times_price_must_match() -> None:
    assert rows("Услуги  3  150,00  300,00") == []
