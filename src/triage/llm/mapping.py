"""The contract between the model and the pipeline: a mapping, not values.

Two answer formats carry the same information.

compact (default) - one string per field, what a small model can afford to generate:
    {"issue_date": "D2", "supplier_name": "ТОО «Арна»", "contract_number": null,
     "line_items": [{"description": "...", "quantity": "A6", "unit_price": "A7", "amount": "A8"}]}
  A string that looks like a candidate id is a pick; any other string is an exact quote.
  Given the document's candidates, the schema lists for every typed field only the ids it may
  take (dates for issue_date, IBAN / р/с for supplier_account, ...). Constrained decoding then
  makes it impossible to write a value instead of an id - measured on qwen3.5:4b, an unconstrained
  string made the model write "2026-01-15" instead of "D1" in a quarter of the fields. The price:
  if the extractor missed a value, the model cannot quote it; the field comes back null.

full - one slot object per field, lets the model state a value next to a fallback quote:
    {"candidate": "D2", "quote": null, "value": null}        - pick a candidate (normal case)
    {"candidate": null, "quote": "ТОО «Арна»", "value": null} - text field, exact quote
    {"candidate": null, "quote": "1 234,56", "value": "1234.56"} - fallback: no candidate fits
    {"candidate": null, "quote": null, "value": null}        - not in the document

The JSON schema sent to the model is strict (every key required, no extras) so constrained
decoding can enforce it. The parser is lenient: small models sometimes answer `null` or a bare
"D2" instead of a slot object, and rejecting that would only cost a retry.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, create_model, model_validator

from triage.candidates import Candidate
from triage.schema import (
    CANDIDATE_TYPE,
    EXPENSE_CATEGORIES,
    HEADER_FIELDS,
    LINE_ITEM_FIELDS,
    ExpenseCategory,
    FieldKind,
    FieldSpec,
)

AnswerFormat = Literal["compact", "full"]
_CANDIDATE_ID = re.compile(r"^[DAIC]\d+$")


class Slot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate: str | None = None
    quote: str | None = None
    value: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _lenient(cls, data: Any) -> Any:
        if data is None:
            return {}
        if isinstance(data, str):
            stripped = data.strip()
            marker = stripped.strip("[]")  # small models sometimes echo the "[[D2]]" marker
            if _CANDIDATE_ID.match(marker):
                return {"candidate": marker}
            return {"quote": stripped} if stripped else {}
        if isinstance(data, int | float | bool):
            return {"value": str(data)}
        return data

    @property
    def is_empty(self) -> bool:
        return not (self.candidate or self.quote or self.value)


HeaderSlots = create_model(  # type: ignore[call-overload]
    "HeaderSlots",
    __config__=ConfigDict(extra="forbid"),
    **{f.name: (Slot, Slot()) for f in HEADER_FIELDS},
)
LineItemSlots = create_model(  # type: ignore[call-overload]
    "LineItemSlots",
    __config__=ConfigDict(extra="forbid"),
    **{f.name: (Slot, Slot()) for f in LINE_ITEM_FIELDS},
)


class FieldMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: HeaderSlots  # type: ignore[valid-type]
    line_items: list[LineItemSlots] = []  # type: ignore[valid-type]
    expense_category: ExpenseCategory | None = None
    is_credit_note: bool | None = None


class MappingParseError(ValueError):
    pass


def response_json_schema(
    answer_format: AnswerFormat = "full",
    candidates: list[Candidate] | None = None,
    with_line_items: bool = True,
) -> dict[str, Any]:
    """Strict schema for constrained decoding: all keys required, no defaults, no extras."""
    schema = (
        compact_json_schema(candidates)
        if answer_format == "compact"
        else _strict(copy.deepcopy(FieldMapping.model_json_schema()))
    )
    if not with_line_items:
        schema["properties"].pop("line_items")
        schema["required"].remove("line_items")
    return schema


def _strict(schema: dict[str, Any]) -> dict[str, Any]:
    def strict(node: Any) -> None:
        if isinstance(node, dict):
            node.pop("default", None)
            node.pop("title", None)
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            for child in node.values():
                strict(child)
        elif isinstance(node, list):
            for child in node:
                strict(child)

    strict(schema)
    return schema


def _slot_schema(spec: FieldSpec, candidates: list[Candidate] | None) -> dict[str, Any]:
    if candidates is None or spec.kind is FieldKind.TEXT:
        return {"anyOf": [{"type": "string"}, {"type": "null"}]}
    allowed = [
        c.id
        for c in candidates
        if c.type == CANDIDATE_TYPE[spec.kind]
        and (spec.kind is not FieldKind.IDENTIFIER or set(c.subtypes) & spec.id_subtypes)
    ]
    if not allowed:
        return {"type": "null"}
    return {"anyOf": [{"type": "string", "enum": allowed}, {"type": "null"}]}


def compact_json_schema(candidates: list[Candidate] | None = None) -> dict[str, Any]:
    line_fields = [f.name for f in LINE_ITEM_FIELDS]
    line = {
        "type": "object",
        "properties": {f.name: _slot_schema(f, candidates) for f in LINE_ITEM_FIELDS},
        "required": line_fields,
        "additionalProperties": False,
    }
    properties: dict[str, Any] = {f.name: _slot_schema(f, candidates) for f in HEADER_FIELDS}
    properties["line_items"] = {"type": "array", "items": line}
    properties["expense_category"] = {
        "anyOf": [{"type": "string", "enum": list(EXPENSE_CATEGORIES)}, {"type": "null"}]
    }
    properties["is_credit_note"] = {"anyOf": [{"type": "boolean"}, {"type": "null"}]}
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _expand_compact(data: dict[str, Any]) -> dict[str, Any]:
    names = [f.name for f in LINE_ITEM_FIELDS]
    items = []
    for item in data.get("line_items") or []:
        items.append(dict(zip(names, item, strict=False)) if isinstance(item, list) else item)
    return {
        "fields": {f.name: data.get(f.name) for f in HEADER_FIELDS},
        "line_items": items,
        "expense_category": data.get("expense_category"),
        "is_credit_note": data.get("is_credit_note"),
    }


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def parse_mapping(raw: str) -> FieldMapping:
    text = _FENCE.sub("", _THINK.sub("", raw).strip()).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise MappingParseError(f"response is not valid JSON: {e}") from e
    if isinstance(data, dict) and "fields" not in data:
        data = _expand_compact(data)  # the format is recognized by shape, not by configuration
    try:
        return FieldMapping.model_validate(data)
    except ValidationError as e:
        raise MappingParseError(f"response does not match the schema: {e}") from e
