from triage import idformats
from triage.llm.oracle import transpose_digits

from .conftest import GOLD

KZ = GOLD["inv_01_kz_logistics.pdf"]["fields"]
RU = GOLD["inv_04_ru_consulting.pdf"]["fields"]
UK = GOLD["inv_07_uk_software.pdf"]["fields"]


def test_valid_identifiers_from_the_synthetic_set() -> None:
    assert idformats.bin_iin_valid(KZ["supplier_tax_id"])
    assert idformats.iban_valid(KZ["supplier_account"])
    assert idformats.inn_valid(RU["supplier_tax_id"])
    assert idformats.ru_account_key_ok(RU["supplier_account"], RU["supplier_bank_code"])
    assert idformats.iban_valid(UK["supplier_account"])
    assert idformats.bic_format_ok(UK["supplier_bank_code"])
    assert idformats.vat_format_ok(UK["supplier_tax_id"])


def test_checksums_catch_a_transposition() -> None:
    assert not idformats.bin_iin_valid(transpose_digits(KZ["supplier_tax_id"]))
    assert not idformats.inn_valid(transpose_digits(RU["supplier_tax_id"]))
    assert not idformats.iban_valid(transpose_digits(UK["supplier_account"]))
    assert not idformats.ru_account_key_ok(
        transpose_digits(RU["supplier_account"]), RU["supplier_bank_code"]
    )


def test_compact_removes_spaces_and_uppercases() -> None:
    assert idformats.compact("gb81 dhbs 3169") == "GB81DHBS3169"


def test_iban_check_digits_round_trip() -> None:
    iban = idformats.compact(UK["supplier_account"])
    assert idformats.iban_check_digits(iban[:2], iban[4:]) == iban[2:4]
