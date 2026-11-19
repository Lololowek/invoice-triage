"""Layer 1: schema. Types, formats, ranges, checksums - via Pydantic - plus cross-field rules.

Catches: a date that is not a date, 3 decimals in money, an unknown currency, a tax ID or IBAN
with a broken checksum (a transposition inside an identifier), a due date before the issue date,
a Russian correspondent account picked instead of the settlement account.

Does not catch: a well-formed value that is simply the wrong one.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import ValidationError

from triage import idformats
from triage.result import FieldResult
from triage.schema import FieldKind, Invoice


def _loc_to_path(loc: tuple[Any, ...]) -> str:
    if len(loc) >= 3 and loc[0] == "line_items":
        return f"line_items[{loc[1]}].{loc[2]}"
    return str(loc[0]) if loc else ""


def _invoice_payload(fields: list[FieldResult]) -> dict[str, Any]:
    payload: dict[str, Any] = {"line_items": []}
    for f in fields:
        if f.path.startswith("line_items["):
            index = int(f.path[len("line_items[") : f.path.index("]")])
            while len(payload["line_items"]) <= index:
                payload["line_items"].append({})
            payload["line_items"][index][f.path.rsplit(".", 1)[1]] = f.value
        else:
            payload[f.path] = f.value
    return payload


def check_schema(fields: list[FieldResult]) -> None:
    by_path = {f.path: f for f in fields}
    try:
        Invoice.model_validate(_invoice_payload(fields))
    except ValidationError as e:
        for error in e.errors():
            target = by_path.get(_loc_to_path(error["loc"]))
            if target is not None:
                message = str(error["msg"]).removeprefix("Value error, ")
                target.flag("schema", "invalid", message)
    _check_dates(by_path)
    _check_ru_account(by_path)
    _check_signs(fields, by_path)


def _as_date(f: FieldResult | None) -> date | None:
    if f is None or not isinstance(f.value, str):
        return None
    try:
        return date.fromisoformat(f.value)
    except ValueError:
        return None


def _as_decimal(f: FieldResult) -> Decimal | None:
    if not isinstance(f.value, str):
        return None
    try:
        return Decimal(f.value)
    except InvalidOperation:
        return None


def _check_dates(by_path: dict[str, FieldResult]) -> None:
    issue, due = _as_date(by_path.get("issue_date")), _as_date(by_path.get("due_date"))
    if issue and due and due < issue:
        for path in ("issue_date", "due_date"):
            by_path[path].flag(
                "schema", "due_before_issue", f"due date {due} is before issue date {issue}"
            )


def _check_ru_account(by_path: dict[str, FieldResult]) -> None:
    """A 20-digit Russian account is only verifiable together with the bank's БИК."""
    account_field = by_path.get("supplier_account")
    if account_field is None or not isinstance(account_field.value, str):
        return
    account = idformats.compact(account_field.value)
    if not (account.isdigit() and len(account) == 20):
        return
    bank_field = by_path.get("supplier_bank_code")
    bik = (
        idformats.compact(bank_field.value)
        if bank_field and isinstance(bank_field.value, str)
        else ""
    )
    if not idformats.ru_bik_format_ok(bik):
        account_field.flag(
            "schema", "unverifiable", "Russian account cannot be verified without БИК"
        )
    elif not idformats.ru_account_key_ok(account, bik):
        if idformats.ru_corr_account_key_ok(account, bik):
            message = (
                "this is the bank's correspondent account (к/с), not the settlement account (р/с)"
            )
        else:
            message = f"account control key does not match БИК {bik}"
        account_field.flag("schema", "checksum", message)


def _check_signs(fields: list[FieldResult], by_path: dict[str, FieldResult]) -> None:
    credit_note = by_path.get("is_credit_note")
    if credit_note is not None and credit_note.value is True:
        return
    for f in fields:
        if f.kind is FieldKind.MONEY:
            value = _as_decimal(f)
            if value is not None and value < 0:
                f.flag(
                    "schema",
                    "negative_amount",
                    "negative amount on a document that is not a credit note",
                )
