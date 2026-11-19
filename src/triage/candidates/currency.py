from __future__ import annotations

import re
from collections.abc import Iterator

from triage.candidates.model import RawMatch
from triage.normalize import parse_currency

_CURRENCY = re.compile(
    r"(?<![A-Za-z])(?:KZT|RUB|RUR|USD|EUR|GBP|CNY|CHF)(?![A-Za-z])"
    r"|[₸₽$€£]"
    r"|(?<!\w)(?:тенге|тг\.?|руб(?:лей|ля|ль|\.)?|долл\.|долларов|евро)(?!\w)",
)


def find_currencies(text: str) -> Iterator[RawMatch]:
    for m in _CURRENCY.finditer(text):
        parsed = parse_currency(m.group(0))
        if parsed:
            yield RawMatch(m.start(), m.end(), "currency", m.group(0), parsed.value)
