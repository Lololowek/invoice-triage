"""Fictional but checksum-valid identifiers for synthetic invoices.

Every generator is seeded from a string, so the documents are reproducible byte for byte.
"""

from __future__ import annotations

import random
import string
import zlib
from collections.abc import Callable
from functools import partial

from triage import idformats


def rng_for(seed: str) -> random.Random:
    return random.Random(zlib.crc32(seed.encode("utf-8")))


def _digits(rng: random.Random, n: int) -> str:
    return "".join(rng.choice(string.digits) for _ in range(n))


def kz_bin(seed: str, registered: str = "1502") -> str:
    """BIN: YYMM of registration, entity type 4 (legal entity), serial, check digit."""
    rng = rng_for("bin" + seed)
    while True:
        body = registered + "4" + _digits(rng, 6)
        for check in range(10):
            if idformats.bin_iin_valid(body + str(check)):
                return body + str(check)


def ru_inn10(seed: str, region: str = "77") -> str:
    rng = rng_for("inn" + seed)
    while True:
        body = region + _digits(rng, 7)
        for check in range(10):
            if idformats.inn_valid(body + str(check)):
                return body + str(check)


def ru_kpp(inn: str) -> str:
    return inn[:4] + "01001"


def ru_bank(seed: str) -> tuple[str, str, str]:
    """(БИК, р/с, к/с) where the к/с does NOT pass the settlement-account check.

    That is what lets the schema layer tell "the model picked the correspondent account" apart from
    a genuine settlement account.
    """
    rng = rng_for("rubank" + seed)
    while True:
        bik = "044525" + _digits(rng, 3)
        corr = _with_key(
            "30101810", "00000000" + bik[-3:], partial(_swap, idformats.ru_corr_account_key_ok, bik)
        )
        settlement = _with_key(
            "40702810", "0" + _digits(rng, 10), partial(_swap, idformats.ru_account_key_ok, bik)
        )
        if corr and settlement and not idformats.ru_account_key_ok(corr, bik):
            return bik, settlement, corr


def _swap(check: Callable[[str, str], bool], bik: str, account: str) -> bool:
    return check(account, bik)


def _with_key(head: str, tail: str, ok: Callable[[str], bool]) -> str | None:
    for key in range(10):
        account = f"{head}{key}{tail}"
        if ok(account):
            return account
    return None


def iban(country: str, bban: str) -> str:
    value = country + idformats.iban_check_digits(country, bban) + bban
    assert idformats.iban_valid(value), value
    return value


def kz_iban(seed: str, bank_code: str) -> str:
    rng = rng_for("kziban" + seed)
    return iban("KZ", bank_code + "KZT" + _digits(rng, 10))


def eu_iban(seed: str, country: str) -> str:
    rng = rng_for("iban" + seed)
    letters = "".join(rng.choice(string.ascii_uppercase) for _ in range(4))
    bban = {
        "DE": lambda: _digits(rng, 18),
        "AT": lambda: _digits(rng, 16),
        "GB": lambda: letters + _digits(rng, 14),
        "IE": lambda: letters + _digits(rng, 14),
        "NL": lambda: letters + _digits(rng, 10),
        "LT": lambda: _digits(rng, 16),
        "EE": lambda: _digits(rng, 16),
    }[country]()
    return iban(country, bban)


def bic(seed: str, country: str) -> str:
    rng = rng_for("bic" + seed)
    bank = "".join(rng.choice("BCDFGHJKLMNPQRSTVWXZ") for _ in range(4))
    location = "".join(rng.choice(string.ascii_uppercase + string.digits) for _ in range(2))
    return bank + country + location


def vat(seed: str, country: str) -> str:
    rng = rng_for("vat" + seed)
    body = {
        "GB": lambda: _digits(rng, 9),
        "DE": lambda: _digits(rng, 9),
        "NL": lambda: _digits(rng, 9) + "B01",
        "EE": lambda: "10" + _digits(rng, 7),
        "LT": lambda: _digits(rng, 9),
        "IE": lambda: _digits(rng, 7) + "WA",
        "AT": lambda: "U" + _digits(rng, 8),
    }[country]()
    value = country + body
    assert idformats.vat_format_ok(value), value
    return value
