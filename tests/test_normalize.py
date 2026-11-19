import pytest

from triage.normalize import parse_amount, parse_currency, parse_date, parse_identifier


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ("1 234,56", "1234.56"),  # RU/KZ: space thousands, comma decimal
        ("1 234 567,89", "1234567.89"),
        ("1,234.56", "1234.56"),  # EN
        ("1.234,56", "1234.56"),  # DE
        ("1,234,567", "1234567"),
        ("48.00", "48.00"),
        ("350", "350"),
        ("-500.00", "-500.00"),
        ("−1 200,00", "-1200.00"),  # typographic minus
        ("0,5", "0.5"),
        ("1.5", "1.5"),
    ],
)
def test_amount_formats(raw: str, value: str) -> None:
    parsed = parse_amount(raw)
    assert parsed is not None
    assert parsed.value == value
    assert not parsed.ambiguous


@pytest.mark.parametrize("raw", ["1,234", "1.234"])
def test_amount_three_digits_after_lone_separator_is_ambiguous(raw: str) -> None:
    parsed = parse_amount(raw)
    assert parsed is not None
    assert parsed == ("1234", True)


@pytest.mark.parametrize("raw", ["", "abc", "12 34,00", "1,23,4", "12%", "1 2345"])
def test_amount_rejects_malformed(raw: str) -> None:
    assert parse_amount(raw) is None


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ("2026-01-15", "2026-01-15"),
        ("15.01.2026", "2026-01-15"),
        ("15.01.26", "2026-01-15"),
        ("15/01/2026", "2026-01-15"),
        ("«15» января 2026 г.", "2026-01-15"),
        ("15 января 2026 года", "2026-01-15"),
        ("15 Jan 2026", "2026-01-15"),
        ("15th January, 2026", "2026-01-15"),
        ("January 15, 2026", "2026-01-15"),
        ("Feb 3 2026", "2026-02-03"),
    ],
)
def test_date_formats(raw: str, value: str) -> None:
    assert parse_date(raw) == (value, False)


def test_slash_date_with_both_parts_up_to_12_is_ambiguous() -> None:
    assert parse_date("03/04/2026") == ("2026-04-03", True)
    assert parse_date("04/04/2026") == ("2026-04-04", False)  # same either way


@pytest.mark.parametrize("raw", ["31.02.2026", "January 2026", "15 Jan", "2026", "32.01.2026"])
def test_date_rejects_impossible_or_incomplete(raw: str) -> None:
    # 'January 2026' has no day: dateutil would fill it from today and invent a date
    assert parse_date(raw) is None


@pytest.mark.parametrize(
    ("raw", "code"), [("₸", "KZT"), ("тенге", "KZT"), ("руб.", "RUB"), ("€", "EUR"), ("£", "GBP")]
)
def test_currency_aliases(raw: str, code: str) -> None:
    assert parse_currency(raw) == (code, False)


@pytest.mark.parametrize(
    ("raw", "value"),
    [("№ 45", "45"), ("No. INV-2026-0042", "INV-2026-0042"), ("GB81 DHBS 3169", "GB81DHBS3169")],
)
def test_identifier_strips_number_sign_and_spaces(raw: str, value: str) -> None:
    assert parse_identifier(raw) == (value, False)
