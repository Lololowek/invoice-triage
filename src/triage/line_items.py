"""Line items without the model.

A row of an items table is a text line that carries three amount candidates, in column order,
with quantity × unit price = line amount. That is an arithmetic fact about the document, so code
can find it; the model is asked for line items only when no such row exists.

Measured on qwen3.5:4b before this change: half of all its errors (17 of 33 on 15 invoices) were
in line items - quantities read from inside descriptions ("800" from "800x1000") or from the row
number column, and descriptions cut at a comma.

Rules:
- unit price and amount must be printed as money (with a decimal part: "150 000,00", "48.00");
  quantity may be any number;
- the rightmost matching triple wins: quantity, price and amount are the right-hand columns, while
  row numbers and numbers inside the description sit to the left;
- the description is the last text cell before the quantity (pdf_text separates cells with two
  spaces); a row without a text cell is not a row.

Not handled (the model fallback takes these): discounts or per-line tax that break
quantity × price = amount, prices without decimals, descriptions wrapped onto a second line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from triage.candidates import Candidate

TOLERANCE = Decimal("0.01")
_MONEY_FORMAT = re.compile(r"[.,]\d{2}$")
_CELL_GAP = re.compile(r" {2,}")


@dataclass(frozen=True)
class ParsedRow:
    description: str
    quantity: Candidate
    unit_price: Candidate
    amount: Candidate


def _line_spans(text: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for line in text.split("\n"):
        spans.append((start, start + len(line)))
        start += len(line) + 1
    return spans


def _is_money(c: Candidate) -> bool:
    return _MONEY_FORMAT.search(c.raw) is not None


def _description(text: str, line_start: int, quantity_start: int) -> str | None:
    cells = [c.strip() for c in _CELL_GAP.split(text[line_start:quantity_start])]
    text_cells = [c for c in cells if any(ch.isalpha() for ch in c)]
    return text_cells[-1] if text_cells else None


def _row_on_line(text: str, line_start: int, amounts: list[Candidate]) -> ParsedRow | None:
    for k in range(len(amounts) - 1, 1, -1):
        amount = amounts[k]
        if not _is_money(amount) or Decimal(amount.value) == 0:
            continue
        for j in range(k - 1, 0, -1):
            price = amounts[j]
            if not _is_money(price):
                continue
            for i in range(j - 1, -1, -1):
                quantity = amounts[i]
                q, p, a = (Decimal(c.value) for c in (quantity, price, amount))
                if q != 0 and abs(q * p - a) <= TOLERANCE:
                    description = _description(text, line_start, quantity.start)
                    if description:
                        return ParsedRow(description, quantity, price, amount)
    return None


def find_line_items(text: str, candidates: list[Candidate]) -> list[ParsedRow]:
    amounts = sorted((c for c in candidates if c.type == "amount"), key=lambda c: c.start)
    rows = []
    for start, end in _line_spans(text):
        on_line = [c for c in amounts if start <= c.start and c.end <= end]
        if len(on_line) >= 3 and (row := _row_on_line(text, start, on_line)):
            rows.append(row)
    return rows
