"""Layer 3: arithmetic. Catches numbers that are each honestly taken from the document, but are
the wrong numbers: a subtotal picked as total, a row number picked as quantity.

Equations (tolerance one minor unit, 0.01, for rounding):
  E1  quantity × unit_price = amount                      per line item
  E2  Σ line amounts = subtotal, or = total (prices include tax), or = total − tax
  E3  subtotal + tax = total                              (tax missing counts as 0)

When an equation fails every participant is flagged: arithmetic knows that a number is wrong, not
which one. Not checked: a tax shown only as 'в том числе' (no subtotal), and tax rates - the rate
would have to come from the document too.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from triage.result import FieldResult

TOLERANCE = Decimal("0.01")


def _num(by_path: dict[str, FieldResult], path: str) -> Decimal | None:
    f = by_path.get(path)
    if f is None or not isinstance(f.value, str):
        return None
    try:
        return Decimal(f.value)
    except InvalidOperation:
        return None


def _close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= TOLERANCE


def _flag(by_path: dict[str, FieldResult], paths: list[str], code: str, message: str) -> None:
    for path in paths:
        if path in by_path:
            by_path[path].flag("arithmetic", code, message)


def check_arithmetic(fields: list[FieldResult]) -> None:
    by_path = {f.path: f for f in fields}
    n_items = len({f.path.split(".")[0] for f in fields if f.path.startswith("line_items[")})

    # E1: per line
    for i in range(n_items):
        p = f"line_items[{i}]"
        qty, price, amount = (
            _num(by_path, f"{p}.{k}") for k in ("quantity", "unit_price", "amount")
        )
        if qty is not None and price is not None and amount is not None:
            expected = qty * price
            if not _close(expected, amount):
                _flag(
                    by_path,
                    [f"{p}.quantity", f"{p}.unit_price", f"{p}.amount"],
                    "line_mismatch",
                    f"line {i + 1}: {qty} × {price} = {expected.normalize():f}, amount is {amount}",
                )

    subtotal, tax, total = (_num(by_path, k) for k in ("subtotal", "tax_amount", "total"))

    # E2: lines vs totals
    amounts = [_num(by_path, f"line_items[{i}].amount") for i in range(n_items)]
    if amounts and all(a is not None for a in amounts):
        lines_sum = sum(amounts, Decimal(0))  # type: ignore[arg-type]
        targets = []
        if subtotal is not None:
            targets.append(subtotal)
        if total is not None:
            targets.append(total)
            if tax is not None:
                targets.append(total - tax)
        if targets and not any(_close(lines_sum, t) for t in targets):
            stated = ", ".join(
                f"{name} {value}"
                for name, value in (("subtotal", subtotal), ("total", total))
                if value is not None
            )
            _flag(
                by_path,
                # tax_amount takes part through "total - tax": a missing tax is a suspect too
                [f"line_items[{i}].amount" for i in range(n_items)]
                + ["subtotal", "tax_amount", "total"],
                "sum_mismatch",
                f"sum of line amounts is {lines_sum}; matches none of: {stated}",
            )

    # E3: subtotal + tax = total
    if subtotal is not None and total is not None:
        expected_total = subtotal + (tax or Decimal(0))
        if not _close(expected_total, total):
            _flag(
                by_path,
                ["subtotal", "tax_amount", "total"],
                "total_mismatch",
                f"subtotal {subtotal} + tax {tax if tax is not None else 'missing'} "
                f"= {expected_total}, total is {total}",
            )
