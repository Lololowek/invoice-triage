"""Normalizers: document substring -> canonical value.

Used by candidate extraction (search) and by the grounding check (verifying a model-supplied quote).
Both must use the same code, otherwise the check would test the normalizer instead of the model.

Ambiguity is reported, not resolved silently: `1,234` and `01/02/2026` come back with
`ambiguous=True`, and the grounding layer turns that into a flag.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

from dateutil import parser as dateutil_parser

from triage import idformats

_WS = re.compile(r"\s+")


def collapse_ws(text: str) -> str:
    return _WS.sub(" ", text).strip()


class Parsed(NamedTuple):
    value: str
    ambiguous: bool = False


# --- amounts ---

_MINUS = "-−–"


def parse_amount(raw: str) -> Parsed | None:
    """'1 234,56' / '1,234.56' / '1.234,56' / '-500.00' -> '1234.56'.

    Rules:
    - single spaces separate thousands (columns are separated by 2+ spaces, see pdf_text);
    - if both '.' and ',' occur, the last one is the decimal separator;
    - a lone separator followed by exactly three digits ('1,234', '1.234') is read as a thousands
      separator and marked ambiguous: it could also be a decimal with three places.
    """
    s = raw.strip().replace(" ", " ").replace(" ", " ")
    negative = False
    if s and s[0] in _MINUS:
        negative, s = True, s[1:].strip()
    if not s or not re.fullmatch(r"[\d ,.]+", s) or not s[0].isdigit() or not s[-1].isdigit():
        return None

    ambiguous = False
    if " " in s:
        groups = s.split(" ")
        tail = groups[-1]
        decimal_part = ""
        m = re.fullmatch(r"(\d{3})[.,](\d{1,4})", tail)
        if m:
            groups[-1], decimal_part = m.group(1), m.group(2)
        if not (1 <= len(groups[0]) <= 3 and all(len(g) == 3 for g in groups[1:])):
            return None
        if not all(g.isdigit() for g in groups):
            return None
        number = "".join(groups) + (f".{decimal_part}" if decimal_part else "")
    elif "," in s and "." in s:
        dec_sep = "," if s.rfind(",") > s.rfind(".") else "."
        thou_sep = "." if dec_sep == "," else ","
        int_part, _, frac = s.rpartition(dec_sep)
        groups = int_part.split(thou_sep)
        if not (1 <= len(groups[0]) <= 3 and all(len(g) == 3 for g in groups[1:])):
            return None
        number = "".join(groups) + "." + frac
    elif "," in s or "." in s:
        sep = "," if "," in s else "."
        parts = s.split(sep)
        if len(parts) > 2:  # 1,234,567 -> thousands
            if not (1 <= len(parts[0]) <= 3 and all(len(p) == 3 for p in parts[1:])):
                return None
            number = "".join(parts)
        elif len(parts[1]) == 3 and len(parts[0]) <= 3 and parts[0] != "0":
            number, ambiguous = parts[0] + parts[1], True
        else:
            number = parts[0] + "." + parts[1]
    else:
        number = s

    try:
        value = Decimal(number)
    except InvalidOperation:
        return None
    if negative:
        value = -value
    return Parsed(_decimal_str(value), ambiguous)


def _decimal_str(value: Decimal) -> str:
    text = format(value, "f")
    return "0" if text in ("-0", "-0.00") else text


# --- dates ---

RU_MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7,
    "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}  # fmt: skip

EN_MONTH_RE = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?"
    r"|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
RU_MONTH_RE = "(?:" + "|".join(RU_MONTHS) + ")"

_ISO = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_DOTS = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})")
_SLASH = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
_RU_TEXT = re.compile(
    rf"«?(\d{{1,2}})»?\s+({RU_MONTH_RE})\s+(\d{{4}})(?:\s*(?:г\.?|года))?", re.IGNORECASE
)
# Both English patterns require an explicit day: dateutil would otherwise fill a missing day
# from today's date and invent a value.
EN_DMY_RE = rf"\d{{1,2}}(?:st|nd|rd|th)?\s+{EN_MONTH_RE}\.?,?\s+\d{{4}}"
EN_MDY_RE = rf"{EN_MONTH_RE}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}"
_EN_TEXT = re.compile(rf"(?:{EN_DMY_RE}|{EN_MDY_RE})", re.IGNORECASE)


def _mk(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date(raw: str) -> Parsed | None:
    """Supported: 2026-01-15, 15.01.2026, 15/01/2026, «15» января 2026, 15 Jan 2026, Jan 15, 2026.

    Slash dates where both parts are <= 12 are ambiguous (DMY vs MDY); they are read as DMY and
    marked ambiguous.
    """
    s = collapse_ws(raw)
    result: date | None = None
    ambiguous = False
    if m := _ISO.fullmatch(s):
        result = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    elif m := _DOTS.fullmatch(s):
        year = int(m.group(3))
        year = year + 2000 if year < 100 else year
        result = _mk(year, int(m.group(2)), int(m.group(1)))
    elif m := _SLASH.fullmatch(s):
        a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a > 12:
            result = _mk(year, b, a)
        elif b > 12:
            result = _mk(year, a, b)
        else:
            result, ambiguous = _mk(year, b, a), a != b
    elif m := _RU_TEXT.fullmatch(s):
        result = _mk(int(m.group(3)), RU_MONTHS[m.group(2).lower()], int(m.group(1)))
    elif _EN_TEXT.fullmatch(s):
        try:
            result = dateutil_parser.parse(s, dayfirst=True, fuzzy=False).date()
        except (ValueError, OverflowError):
            result = None
    if result is None:
        return None
    return Parsed(result.isoformat(), ambiguous)


# --- currency ---

CURRENCY_ALIASES = {
    "₸": "KZT", "тенге": "KZT", "тг": "KZT", "тг.": "KZT", "kzt": "KZT",
    "₽": "RUB", "руб": "RUB", "руб.": "RUB", "рубль": "RUB", "рубля": "RUB", "рублей": "RUB",
    "rub": "RUB", "rur": "RUB",
    "$": "USD", "usd": "USD", "долл.": "USD", "долларов": "USD",
    "€": "EUR", "eur": "EUR", "евро": "EUR",
    "£": "GBP", "gbp": "GBP",
    "cny": "CNY", "chf": "CHF",
}  # fmt: skip


def parse_currency(raw: str) -> Parsed | None:
    code = CURRENCY_ALIASES.get(collapse_ws(raw).lower())
    return Parsed(code) if code else None


# --- identifiers ---

_ID_MARKER = re.compile(r"^(?:№|N[oº°]\.?|Nr\.?|#)\s*", re.IGNORECASE)


def parse_identifier(raw: str) -> Parsed | None:
    value = idformats.compact(_ID_MARKER.sub("", raw.strip()))
    value = value.rstrip(".,;:")
    return Parsed(value) if value else None
