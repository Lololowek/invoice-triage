"""Prompt: document text with inline candidate markers + candidate list + field descriptions.

Markers sit right after the value (`15.01.2026[[D2]]`) because the model decides by the label next
to the value, and the label is only visible in context. The separate list adds normalized values.
"""

from __future__ import annotations

from triage.candidates import Candidate
from triage.schema import DERIVED_FIELDS, HEADER_FIELDS, LINE_ITEM_FIELDS, FieldKind, FieldSpec

INTRO = """\
You read an invoice and map its fields to candidates. The candidates (dates, amounts, \
identifiers, currencies) were found in the text by deterministic code and are marked in the \
document as value[[ID]]. Pick by the LABEL next to the value (the date next to "Invoice date" / \
"Дата счёта" is issue_date), not by the value. Never guess: if a field is not in the document, \
answer null."""

HINTS = [
    "- supplier = the party that issues the invoice and receives the money (Поставщик, Продавец, "
    "Исполнитель, Арендодатель, Бенефициар, Seller, From, the letterhead); buyer = the party "
    "that pays (Покупатель, Заказчик, Арендатор, Bill to, Client, Customer, the addressee).",
    "- contract_number = the number next to a contract label (Договор, Основание, Contract, "
    "Agreement, framework agreement). Order, PO, customer, booking and delivery note numbers are "
    "not contracts. No contract label in the document -> null.",
]
LINE_ITEM_HINT = (
    "- quantity = the value in the quantity column (Кол-во, Qty, Quantity), never a row number "
    "(№, Pos.) and never a number inside the description."
)

RULES: dict[str, list[str]] = {
    "compact": [
        "Answer with ONE flat JSON object; every field is one string or null:",
        '- date, amount, identifier and currency fields: the candidate ID, e.g. "D2";',
        "- text fields (names, payment terms, descriptions): the exact text from the document, "
        "without the label; a description is only the item text, without row number or unit;",
        "- a value that is printed but has no [[ID]] marker: the exact printed text;",
        "LINE_ITEMS:- line_items: one object per row of the items table, in order;",
        "- expense_category and is_credit_note: your judgement about the whole document.",
        "Answer with JSON only.",
    ],
    "full": [
        'Fill one slot {"candidate", "quote", "value"} per field:',
        '- date, amount, identifier and currency fields: "candidate" = the candidate ID, '
        'e.g. "D2";',
        "- not in the document: all three keys null;",
        '- text fields (names, payment terms, descriptions): "quote" = the exact text from the '
        "document, without the label; a description is only the item text, without row number "
        "or unit;",
        '- only if a value is printed but has no [[ID]] marker: "quote" = the exact printed text, '
        '"value" = its normalized form (dates YYYY-MM-DD, amounts like 1234.56);',
        "LINE_ITEMS:- line_items: one entry per row of the items table, in order;",
        "- expense_category and is_credit_note: your judgement about the whole document.",
        "Answer with JSON only.",
    ],
}


def system_prompt(answer_format: str = "compact", with_line_items: bool = True) -> str:
    """Line-item instructions are left out when code already found the rows (line_items.py)."""
    hints = HINTS + ([LINE_ITEM_HINT] if with_line_items else [])
    rules = []
    for rule in RULES[answer_format]:
        if rule.startswith("LINE_ITEMS:"):
            if not with_line_items:
                continue
            rule = rule.removeprefix("LINE_ITEMS:")
        rules.append(rule)
    return "\n".join([INTRO, "", "Hints:", *hints, "", *rules])


def annotate(text: str, candidates: list[Candidate]) -> str:
    parts: list[str] = []
    cursor = 0
    for c in sorted(candidates, key=lambda c: c.start):
        parts.append(text[cursor : c.end])
        parts.append(f"[[{c.id}]]")
        cursor = c.end
    parts.append(text[cursor:])
    return "".join(parts)


def _describe(spec: FieldSpec) -> str:
    kind = {
        FieldKind.TEXT: "text, quote",
        FieldKind.DATE: "date candidate",
        FieldKind.MONEY: "amount candidate",
        FieldKind.NUMBER: "amount candidate",
        FieldKind.IDENTIFIER: "identifier candidate",
        FieldKind.CURRENCY: "currency candidate",
        FieldKind.DERIVED: "your judgement",
    }[spec.kind]
    required = ", required" if spec.required else ""
    return f"- {spec.name} ({kind}{required}): {spec.description}"


def _candidate_line(c: Candidate) -> str:
    extra = f" [{','.join(c.subtypes)}]" if c.subtypes else ""
    flags = f" ({','.join(c.flags)})" if c.flags else ""
    return f"{c.id} {c.type}{extra} = {c.value}  printed as {c.raw!r}{flags}"


def build_user_prompt(text: str, candidates: list[Candidate], with_line_items: bool = True) -> str:
    line_item_block = [
        "LINE ITEM FIELDS (for each row of the items table):",
        *(_describe(f) for f in LINE_ITEM_FIELDS),
        "",
    ]
    return "\n".join(
        [
            "FIELDS:",
            *(_describe(f) for f in HEADER_FIELDS),
            "",
            *(line_item_block if with_line_items else []),
            "DERIVED FIELDS:",
            *(_describe(f) for f in DERIVED_FIELDS),
            "",
            "CANDIDATES:",
            *(_candidate_line(c) for c in candidates),
            "",
            "DOCUMENT:",
            "<<<",
            annotate(text, candidates),
            ">>>",
        ]
    )


def build_messages(
    text: str,
    candidates: list[Candidate],
    answer_format: str = "compact",
    with_line_items: bool = True,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": system_prompt(answer_format, with_line_items)},
        {"role": "user", "content": build_user_prompt(text, candidates, with_line_items)},
    ]
