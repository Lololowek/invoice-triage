"""Prompt: document text with inline candidate markers + candidate list + field descriptions.

Markers sit right after the value (`15.01.2026[[D2]]`) because the model decides by the label next
to the value, and the label is only visible in context. The separate list adds normalized values.
"""

from __future__ import annotations

from triage.candidates import Candidate
from triage.schema import DERIVED_FIELDS, HEADER_FIELDS, LINE_ITEM_FIELDS, FieldKind, FieldSpec

SYSTEM_PROMPT = """\
You read an invoice and map its fields to candidates. The candidates (dates, amounts, \
identifiers, currencies) were found in the text by deterministic code and are marked in the \
document as value[[ID]].

Rules:
1. Date, amount, identifier and currency fields: set "candidate" to the ID of the candidate \
whose LABEL in the document matches the field (e.g. the date next to "Invoice date" / \
"Дата счёта" is issue_date). The same value may appear several times; any of its IDs is fine.
2. If the document does not contain a field, return all three keys as null. Never guess and \
never reuse a candidate that belongs to another label. A missing contract number is normal.
3. Text fields (names, payment terms, line descriptions) have no candidates: copy the exact \
text from the document into "quote", character for character, without labels.
4. Only if a value is clearly printed but has no [[ID]] marker: put the exact printed text in \
"quote" and its normalized form in "value" (dates YYYY-MM-DD, amounts like 1234.56).
5. line_items: one entry per row of the items table, in order.
6. expense_category and is_credit_note are your judgement about the whole document.
Answer with JSON only."""


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


def build_user_prompt(text: str, candidates: list[Candidate]) -> str:
    return "\n".join(
        [
            "FIELDS:",
            *(_describe(f) for f in HEADER_FIELDS),
            "",
            "LINE ITEM FIELDS (for each row of the items table):",
            *(_describe(f) for f in LINE_ITEM_FIELDS),
            "",
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


def build_messages(text: str, candidates: list[Candidate]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(text, candidates)},
    ]
