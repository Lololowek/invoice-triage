from __future__ import annotations

import re
from collections.abc import Iterator

from triage.candidates.model import RawMatch
from triage.normalize import EN_DMY_RE, EN_MDY_RE, RU_MONTH_RE, parse_date

# Boundaries: a date must not be glued to letters, digits or id punctuation ("INV-2026-01-15"
# is an identifier, not a date).
_L = r"(?<![\w/.\-])"
_R = r"(?![\w/\-]|\.\d)"

_PATTERNS = [
    re.compile(_L + r"\d{4}-\d{2}-\d{2}" + _R),
    re.compile(_L + r"\d{1,2}\.\d{1,2}\.(?:\d{4}|\d{2})" + _R),
    re.compile(_L + r"\d{1,2}/\d{1,2}/\d{4}" + _R),
    re.compile(_L + rf"«?\d{{1,2}}»?\s+{RU_MONTH_RE}\s+\d{{4}}" + _R, re.IGNORECASE),
    re.compile(_L + EN_DMY_RE + _R, re.IGNORECASE),
    re.compile(_L + EN_MDY_RE + _R, re.IGNORECASE),
]


def find_dates(text: str) -> Iterator[RawMatch]:
    for pattern in _PATTERNS:
        for m in pattern.finditer(text):
            parsed = parse_date(m.group(0))
            if parsed is None:
                continue  # 31.02.2026 and friends: looks like a date, is not one
            yield RawMatch(
                start=m.start(),
                end=m.end(),
                type="date",
                raw=m.group(0),
                value=parsed.value,
                flags=("ambiguous",) if parsed.ambiguous else (),
            )
