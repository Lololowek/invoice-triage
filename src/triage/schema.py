"""Invoice schema: one registry of field specs + the Pydantic model used by the schema check.

Field kinds decide how a value is bound to the document:
- DATE / MONEY / NUMBER / IDENTIFIER / CURRENCY - extractive, the model returns a candidate id;
- TEXT - extractive, no candidates exist (names, terms), the model returns an exact quote;
- DERIVED - inferred, not copied (category, credit note); no source check applies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict

from triage import idformats


class FieldKind(StrEnum):
    TEXT = "text"
    DATE = "date"
    MONEY = "money"
    NUMBER = "number"
    IDENTIFIER = "identifier"
    CURRENCY = "currency"
    DERIVED = "derived"


# Which candidate type a field kind may point at.
CANDIDATE_TYPE: dict[FieldKind, str] = {
    FieldKind.DATE: "date",
    FieldKind.MONEY: "amount",
    FieldKind.NUMBER: "amount",
    FieldKind.IDENTIFIER: "identifier",
    FieldKind.CURRENCY: "currency",
}

TAX_ID_SUBTYPES = frozenset({"bin_iin", "inn", "vat"})


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: FieldKind
    description: str
    required: bool = False
    id_subtypes: frozenset[str] = frozenset()

    @property
    def extractive(self) -> bool:
        return self.kind is not FieldKind.DERIVED


HEADER_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("supplier_name", FieldKind.TEXT,
              "Legal name of the seller who issued the invoice", required=True),
    FieldSpec("supplier_tax_id", FieldKind.IDENTIFIER,
              "Seller's tax ID: BIN/IIN (Kazakhstan), INN (Russia) or VAT ID",
              required=True, id_subtypes=TAX_ID_SUBTYPES),
    FieldSpec("supplier_account", FieldKind.IDENTIFIER,
              "Seller's bank account to pay to: IBAN/ИИК, or Russian settlement account "
              "(р/с, not the correspondent account к/с)",
              required=True, id_subtypes=frozenset({"iban", "ru_account"})),
    FieldSpec("supplier_bank_code", FieldKind.IDENTIFIER,
              "Seller's bank code: BIC/SWIFT or Russian БИК",
              id_subtypes=frozenset({"bic", "ru_bik"})),
    FieldSpec("buyer_name", FieldKind.TEXT,
              "Legal name of the buyer / customer / payer", required=True),
    FieldSpec("buyer_tax_id", FieldKind.IDENTIFIER,
              "Buyer's tax ID: BIN/IIN, INN or VAT ID", id_subtypes=TAX_ID_SUBTYPES),
    FieldSpec("invoice_number", FieldKind.IDENTIFIER,
              "Number of THIS invoice or credit note (not an order, customer or original "
              "invoice number)", required=True, id_subtypes=frozenset({"doc_number"})),
    FieldSpec("contract_number", FieldKind.IDENTIFIER,
              "Number of the contract / agreement the invoice is based on. Often absent - "
              "then null. Purchase order, customer and invoice numbers are NOT contracts.",
              id_subtypes=frozenset({"doc_number"})),
    FieldSpec("issue_date", FieldKind.DATE,
              "Date the invoice was issued", required=True),
    FieldSpec("due_date", FieldKind.DATE,
              "Payment due date, only if a date is printed (not computed from terms)"),
    FieldSpec("currency", FieldKind.CURRENCY,
              "Invoice currency", required=True),
    FieldSpec("subtotal", FieldKind.MONEY,
              "Total before tax, only if printed"),
    FieldSpec("tax_amount", FieldKind.MONEY,
              "VAT / tax amount, including 'в том числе НДС'"),
    FieldSpec("total", FieldKind.MONEY,
              "Final amount payable", required=True),
    FieldSpec("payment_terms", FieldKind.TEXT,
              "Payment terms as written, e.g. 'Net 30' or 'в течение 5 банковских дней'"),
)  # fmt: skip

LINE_ITEM_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("description", FieldKind.TEXT, "Item or service description", required=True),
    FieldSpec("quantity", FieldKind.NUMBER, "Quantity", required=True),
    FieldSpec("unit_price", FieldKind.MONEY, "Price per unit", required=True),
    FieldSpec("amount", FieldKind.MONEY, "Line total", required=True),
)

EXPENSE_CATEGORIES = (
    "software", "it_services", "consulting", "logistics", "office_supplies", "equipment",
    "rent", "utilities", "marketing", "travel", "other",
)  # fmt: skip
ExpenseCategory = Literal[
    "software", "it_services", "consulting", "logistics", "office_supplies", "equipment",
    "rent", "utilities", "marketing", "travel", "other",
]  # fmt: skip

DERIVED_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("expense_category", FieldKind.DERIVED,
              "Expense category, one of: " + ", ".join(EXPENSE_CATEGORIES)),
    FieldSpec("is_credit_note", FieldKind.DERIVED,
              "true if the document is a credit note (кредит-нота), not a regular invoice"),
)  # fmt: skip

HEADER_BY_NAME = {f.name: f for f in HEADER_FIELDS}
LINE_BY_NAME = {f.name: f for f in LINE_ITEM_FIELDS}
DERIVED_BY_NAME = {f.name: f for f in DERIVED_FIELDS}


def spec_for(spec_name: str) -> FieldSpec:
    """'total' -> header spec, 'line_items.amount' -> line item spec."""
    if spec_name.startswith("line_items."):
        return LINE_BY_NAME[spec_name.split(".", 1)[1]]
    return HEADER_BY_NAME.get(spec_name) or DERIVED_BY_NAME[spec_name]


# --- value types: formats and ranges (layer 1) ---

EARLIEST_DATE = date(2000, 1, 1)
MONEY_LIMIT = Decimal("1e12")
CURRENCIES = frozenset({
    "KZT", "RUB", "USD", "EUR", "GBP", "CNY", "CHF", "UZS", "KGS", "BYN", "AMD", "GEL", "AED",
    "TRY", "PLN", "CZK", "SEK", "NOK", "DKK", "JPY",
})  # fmt: skip


def _plausible_date(value: date) -> date:
    latest = date.today() + timedelta(days=730)
    if not (EARLIEST_DATE <= value <= latest):
        raise ValueError(f"date outside plausible range {EARLIEST_DATE} .. {latest}")
    return value


def _money(value: Decimal) -> Decimal:
    if abs(value) >= MONEY_LIMIT:
        raise ValueError("amount out of range")
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -2:
        raise ValueError("money must have at most 2 decimal places")
    return value


def _quantity(value: Decimal) -> Decimal:
    if value == 0 or abs(value) >= Decimal("1e7"):
        raise ValueError("quantity must be non-zero and below 10 000 000")
    return value


def _currency(value: str) -> str:
    if value not in CURRENCIES:
        raise ValueError(f"not a supported ISO 4217 code: {value!r}")
    return value


def _text(value: str) -> str:
    value = " ".join(value.split())
    if not 1 <= len(value) <= 300:
        raise ValueError("text must be 1..300 characters")
    return value


def _identifier(allowed: frozenset[str], label: str):
    def check(value: str) -> str:
        value = idformats.compact(value)
        if not any(idformats.is_valid(subtype, value) for subtype in allowed):
            raise ValueError(f"not a valid {label} (format or checksum)")
        return value

    return AfterValidator(check)


InvoiceDate = Annotated[date, AfterValidator(_plausible_date)]
Money = Annotated[Decimal, AfterValidator(_money)]
Quantity = Annotated[Decimal, AfterValidator(_quantity)]
CurrencyCode = Annotated[str, AfterValidator(_currency)]
Text = Annotated[str, AfterValidator(_text)]
TaxId = Annotated[str, _identifier(TAX_ID_SUBTYPES, "tax ID (BIN/IIN, INN, VAT)")]
Account = Annotated[str, _identifier(frozenset({"iban", "ru_account"}), "IBAN / account")]
BankCode = Annotated[str, _identifier(frozenset({"bic", "ru_bik"}), "BIC / БИК")]
DocNumber = Annotated[str, _identifier(frozenset({"doc_number"}), "document number")]


class LineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: Text | None = None
    quantity: Quantity | None = None
    unit_price: Money | None = None
    amount: Money | None = None


class Invoice(BaseModel):
    """Every field is optional here: a missing required field is the grounding layer's flag."""

    model_config = ConfigDict(extra="forbid")

    supplier_name: Text | None = None
    supplier_tax_id: TaxId | None = None
    supplier_account: Account | None = None
    supplier_bank_code: BankCode | None = None
    buyer_name: Text | None = None
    buyer_tax_id: TaxId | None = None
    invoice_number: DocNumber | None = None
    contract_number: DocNumber | None = None
    issue_date: InvoiceDate | None = None
    due_date: InvoiceDate | None = None
    currency: CurrencyCode | None = None
    subtotal: Money | None = None
    tax_amount: Money | None = None
    total: Money | None = None
    payment_terms: Text | None = None
    line_items: list[LineItem] = []
    expense_category: ExpenseCategory | None = None
    is_credit_note: bool | None = None


# The registry and the model describe the same fields; fail at import time if they drift apart.
assert set(Invoice.model_fields) == (
    {f.name for f in HEADER_FIELDS} | {f.name for f in DERIVED_FIELDS} | {"line_items"}
), "schema.HEADER_FIELDS / DERIVED_FIELDS and Invoice are out of sync"
assert set(LineItem.model_fields) == {f.name for f in LINE_ITEM_FIELDS}
