from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from triage.candidates import Candidate, extract_candidates
from triage.policy import RiskPolicy

ROOT = Path(__file__).resolve().parents[1]
INVOICES = ROOT / "data" / "invoices"
GOLD: dict[str, Any] = json.loads((ROOT / "data" / "gold.json").read_text(encoding="utf-8"))[
    "documents"
]

# Text of data/invoices/inv_07_uk_software.pdf as pdf_text extracts it (two spaces = column gap).
UK_INVOICE = """\
INVOICE  Brightline Analytics Ltd

From  Invoice no.: INV-2026-0042
Brightline Analytics Ltd  Invoice date: 15 Jan 2026
4 Canal Street, Manchester M1 3HE  Due date: 14 Feb 2026
VAT reg. no.: GB947145946  PO number: PO-7731
Agreement ref: MSA-2025-031

Bill to
Kestrel Data UK Ltd
20 Wharf Road, London N1 7GR
VAT: GB451851468

Description  Qty  Unit price  Amount (GBP)
(GBP)
Analytics Platform licence, Jan  25  48.00  1,200.00
Premium support, Jan  1  350.00  350.00
Onboarding workshop (remote)  1.5  600.00  900.00

Subtotal  £2,450.00
VAT (20%)  £490.00
Total due (GBP)  £2,940.00

Payment details
Bank: Northgate Bank plc
IBAN: GB81 DHBS 3169 3923 3682 89
BIC: HNWVGBKU
Terms: Net 30"""


def cid(candidates: list[Candidate], raw: str) -> str:
    """Id of the candidate printed as `raw` (the first one if it is printed twice)."""
    for c in candidates:
        if c.raw == raw:
            return c.id
    raise AssertionError(f"no candidate printed as {raw!r}: {[c.raw for c in candidates]}")


def uk_compact_answer(**overrides: Any) -> str:
    """A correct answer in the compact format, as the model would give it for UK_INVOICE."""
    cands = extract_candidates(UK_INVOICE)
    answer: dict[str, Any] = {
        "supplier_name": "Brightline Analytics Ltd",
        "supplier_tax_id": cid(cands, "GB947145946"),
        "supplier_account": cid(cands, "GB81 DHBS 3169 3923 3682 89"),
        "supplier_bank_code": cid(cands, "HNWVGBKU"),
        "buyer_name": "Kestrel Data UK Ltd",
        "buyer_tax_id": cid(cands, "GB451851468"),
        "invoice_number": cid(cands, "INV-2026-0042"),
        "contract_number": cid(cands, "MSA-2025-031"),
        "issue_date": cid(cands, "15 Jan 2026"),
        "due_date": cid(cands, "14 Feb 2026"),
        "currency": cid(cands, "GBP"),
        "subtotal": cid(cands, "2,450.00"),
        "tax_amount": cid(cands, "490.00"),
        "total": cid(cands, "2,940.00"),
        "payment_terms": "Net 30",
        "line_items": [],
        "expense_category": "software",
        "is_credit_note": False,
    }
    answer.update(overrides)
    return json.dumps(answer, ensure_ascii=False)


class ScriptedClient:
    """Stands in for the model: returns the given answers in order and records the requests."""

    name = "scripted"

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.requests: list[dict[str, Any]] = []

    def complete(
        self, messages: list[dict[str, str]], json_schema: dict[str, Any], schema_name: str
    ) -> str:
        self.requests.append({"messages": messages, "schema": json_schema})
        return self.answers.pop(0)


@pytest.fixture
def policy() -> RiskPolicy:
    return RiskPolicy.load()
