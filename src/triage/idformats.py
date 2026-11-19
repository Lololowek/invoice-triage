"""Identifier formats and checksums.

Two consumers with different questions:
- candidate extraction asks "what could this token be?" -> format only (`subtypes_for_digits`);
- the schema check asks "is this a valid value?" -> format and checksum (`is_valid`).

Keeping checksums out of extraction matters: a tax ID with a typo in the source document is still a
candidate (the model may legitimately pick it), and the schema layer then flags it.
"""

from __future__ import annotations

import re

# IBAN length per country (subset: countries we expect on invoices in the demo region + EU).
IBAN_LENGTHS: dict[str, int] = {
    "AE": 23, "AT": 20, "AZ": 28, "BE": 16, "CH": 21, "CY": 28, "CZ": 24, "DE": 22, "DK": 18,
    "EE": 20, "ES": 24, "FI": 18, "FR": 27, "GB": 22, "GE": 22, "GR": 27, "HR": 21, "HU": 28,
    "IE": 22, "IT": 27, "KZ": 20, "LT": 20, "LU": 20, "LV": 21, "MT": 31, "NL": 18, "NO": 15,
    "PL": 28, "PT": 25, "RO": 24, "SE": 24, "SI": 19, "SK": 24, "TR": 26, "UA": 29,
}  # fmt: skip

# Country codes accepted in positions 5-6 of a BIC. Restricting them keeps 8-letter words
# like "SUBTOTAL" or "CUSTOMER" from being read as bank codes.
BIC_COUNTRIES = frozenset(IBAN_LENGTHS) | {"RU", "US", "CN", "UZ", "KG", "BY", "AM"}

VAT_PREFIXES = (
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR", "GB", "HR", "HU",
    "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK", "XI",
)  # fmt: skip

_VAT_RE = re.compile(rf"^(?:{'|'.join(VAT_PREFIXES)})[0-9A-Z]{{8,12}}$")
_BIC_RE = re.compile(r"^[A-Z]{4}([A-Z]{2})[A-Z0-9]{2}(?:[A-Z0-9]{3})?$")


def compact(value: str) -> str:
    """Canonical identifier form: no whitespace, upper case."""
    return re.sub(r"\s+", "", value).upper()


# --- Kazakhstan: BIN / IIN (12 digits) ---


def bin_iin_valid(value: str) -> bool:
    if not re.fullmatch(r"\d{12}", value):
        return False
    d = [int(c) for c in value]
    check = sum(d[i] * (i + 1) for i in range(11)) % 11
    if check == 10:
        weights = (3, 4, 5, 6, 7, 8, 9, 10, 11, 1, 2)
        check = sum(d[i] * weights[i] for i in range(11)) % 11
        if check == 10:
            return False
    return check == d[11]


# --- Russia: INN (10 digits for companies, 12 for individuals) ---

_INN10_W = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_W1 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_W2 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def _inn_digit(digits: list[int], weights: tuple[int, ...]) -> int:
    return sum(d * w for d, w in zip(digits, weights, strict=False)) % 11 % 10


def inn_valid(value: str) -> bool:
    if re.fullmatch(r"\d{10}", value):
        d = [int(c) for c in value]
        return _inn_digit(d, _INN10_W) == d[9]
    if re.fullmatch(r"\d{12}", value):
        d = [int(c) for c in value]
        return _inn_digit(d, _INN12_W1) == d[10] and _inn_digit(d, _INN12_W2) == d[11]
    return False


# --- IBAN (ISO 13616, mod 97) ---


def _iban_remainder(value: str) -> int:
    rearranged = value[4:] + value[:4]
    numeric = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(numeric) % 97


def iban_format_ok(value: str) -> bool:
    return re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]+", value) is not None and IBAN_LENGTHS.get(
        value[:2]
    ) == len(value)


def iban_valid(value: str) -> bool:
    return iban_format_ok(value) and _iban_remainder(value) == 1


def iban_check_digits(country: str, bban: str) -> str:
    """Check digits for a new IBAN (used by the synthetic generator)."""
    remainder = _iban_remainder(f"{country}00{bban}")
    return f"{98 - remainder:02d}"


# --- Russia: settlement account (20 digits) + BIK (9 digits) ---

_RU_ACC_W = (7, 1, 3) * 8


def ru_account_key_ok(account: str, bik: str) -> bool:
    """Bank of Russia control key for a settlement account at a credit institution.

    The 23-digit string is the last three digits of the BIK followed by the 20-digit account; the
    sum of the lowest digits of digit*weight products must be divisible by 10.
    """
    if not (re.fullmatch(r"\d{20}", account) and re.fullmatch(r"\d{9}", bik)):
        return False
    digits = [int(c) for c in bik[-3:] + account]
    return sum((d * w) % 10 for d, w in zip(digits, _RU_ACC_W, strict=False)) % 10 == 0


def ru_corr_account_key_ok(account: str, bik: str) -> bool:
    """Same key, but for a correspondent account the prefix is '0' + BIK digits 5-6."""
    if not (re.fullmatch(r"\d{20}", account) and re.fullmatch(r"\d{9}", bik)):
        return False
    digits = [int(c) for c in "0" + bik[4:6] + account]
    return sum((d * w) % 10 for d, w in zip(digits, _RU_ACC_W, strict=False)) % 10 == 0


def ru_bik_format_ok(value: str) -> bool:
    return re.fullmatch(r"04\d{7}", value) is not None


# --- BIC / VAT ---


def bic_format_ok(value: str) -> bool:
    m = _BIC_RE.fullmatch(value)
    return m is not None and m.group(1) in BIC_COUNTRIES


def vat_format_ok(value: str) -> bool:
    return _VAT_RE.fullmatch(value) is not None and sum(c.isdigit() for c in value) >= 6


# --- dispatch ---


def subtypes_for_digits(value: str) -> tuple[str, ...]:
    """Format-only guess for a run of 9-20 digits found in the text."""
    n = len(value)
    if n == 9:
        return ("ru_bik",) if value.startswith("04") else ("kpp",)
    if n == 10:
        return ("inn",)
    if n == 12:
        return ("bin_iin", "inn")
    if n == 13:
        return ("ogrn",)
    if n == 20:
        return ("ru_account",)
    return ("number",)


def is_valid(subtype: str, value: str) -> bool:
    """Format + checksum where one exists; ru_account needs the BIK and is checked cross-field."""
    match subtype:
        case "bin_iin":
            return bin_iin_valid(value)
        case "inn":
            return inn_valid(value)
        case "vat":
            return vat_format_ok(value)
        case "iban":
            return iban_valid(value)
        case "ru_account":
            return re.fullmatch(r"\d{20}", value) is not None
        case "bic":
            return bic_format_ok(value)
        case "ru_bik":
            return ru_bik_format_ok(value)
        case "doc_number":
            return 1 <= len(value) <= 40 and any(c.isalnum() for c in value)
    return False
