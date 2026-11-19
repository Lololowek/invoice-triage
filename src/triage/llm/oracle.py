"""Oracle mapper: an offline stand-in for the model, built from the gold annotation.

Two uses:
1. Run the pipeline end to end without a model (CI, a laptop without Ollama). With a correct
   mapping every flag that remains comes from the document or the checks, not from the model; a
   'no_source' flag means the candidate extractor missed a gold value.
2. Inject the model errors the checks are meant to catch, reproducibly:
     hallucinate:<field>=<value>   the model writes a value that is not in the document
     transpose:<field>             quotes the right text but claims a value with two digits swapped
     pick:<field>=<candidate_id>   picks an existing but wrong candidate
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from triage.candidates import Candidate
from triage.llm.mapping import FieldMapping, HeaderSlots, LineItemSlots, Slot
from triage.schema import (
    CANDIDATE_TYPE,
    HEADER_BY_NAME,
    HEADER_FIELDS,
    LINE_ITEM_FIELDS,
    FieldKind,
    FieldSpec,
)


class OracleMapper:
    name = "oracle"

    def __init__(
        self, gold_document: dict[str, Any], inject: list[str] | tuple[str, ...] = ()
    ) -> None:
        self.gold = gold_document
        self.inject = list(inject)
        if self.inject:
            self.name = "oracle+" + ",".join(self.inject)

    def map(self, text: str, candidates: list[Candidate]) -> FieldMapping:
        used: set[str] = set()
        header = {
            spec.name: self._slot(spec, self.gold["fields"].get(spec.name), candidates, used)
            for spec in HEADER_FIELDS
        }
        line_items = [
            LineItemSlots(**{
                spec.name: self._slot(spec, item.get(spec.name), candidates, used)
                for spec in LINE_ITEM_FIELDS
            })
            for item in self.gold.get("line_items", [])
        ]  # fmt: skip
        for spec_text in self.inject:
            self._apply_injection(spec_text, header, candidates)
        derived = self.gold.get("derived", {})
        return FieldMapping(
            fields=HeaderSlots(**header),
            line_items=line_items,
            expense_category=derived.get("expense_category"),
            is_credit_note=derived.get("is_credit_note"),
        )

    @staticmethod
    def _slot(
        spec: FieldSpec, gold_value: Any, candidates: list[Candidate], used: set[str]
    ) -> Slot:
        if gold_value is None:
            return Slot()
        if spec.kind is FieldKind.TEXT:
            return Slot(quote=str(gold_value))
        matches = [c for c in candidates if _matches(spec, c, str(gold_value))]
        # Dates and identifiers: one printed occurrence per label, so prefer an unused one.
        fresh = [c for c in matches if c.id not in used] or matches
        if not fresh:
            return Slot(value=str(gold_value))  # extractor missed it; the pipeline will flag it
        used.add(fresh[0].id)
        return Slot(candidate=fresh[0].id)

    @staticmethod
    def _apply_injection(
        spec_text: str, header: dict[str, Slot], candidates: list[Candidate]
    ) -> None:
        action, _, rest = spec_text.partition(":")
        name, _, arg = rest.partition("=")
        if name not in HEADER_BY_NAME:
            raise ValueError(f"inject: unknown header field {name!r}")
        if action == "hallucinate":
            header[name] = Slot(quote=arg, value=arg)
        elif action == "pick":
            header[name] = Slot(candidate=arg)
        elif action == "transpose":
            current = header[name]
            candidate = next((c for c in candidates if c.id == current.candidate), None)
            if candidate is None:
                raise ValueError(f"inject: {name} has no candidate to transpose")
            header[name] = Slot(quote=candidate.raw, value=transpose_digits(candidate.value))
        else:
            raise ValueError(f"inject: unknown action {action!r} (hallucinate, transpose, pick)")


def _matches(spec: FieldSpec, c: Candidate, gold_value: str) -> bool:
    if c.type != CANDIDATE_TYPE.get(spec.kind):
        return False
    if spec.kind is FieldKind.IDENTIFIER and not set(c.subtypes) & spec.id_subtypes:
        return False
    if spec.kind in (FieldKind.MONEY, FieldKind.NUMBER):
        try:
            return Decimal(c.value) == Decimal(gold_value)
        except InvalidOperation:
            return False
    return c.value == gold_value


def transpose_digits(value: str) -> str:
    """Swap the last pair of adjacent, different digits: '345000.00' -> '340500.00'."""
    chars = list(value)
    for i in range(len(chars) - 2, -1, -1):
        a, b = chars[i], chars[i + 1]
        if a.isdigit() and b.isdigit() and a != b:
            chars[i], chars[i + 1] = b, a
            return "".join(chars)
    raise ValueError(f"cannot transpose digits in {value!r}")
