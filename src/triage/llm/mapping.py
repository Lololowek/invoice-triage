"""The contract between the model and the pipeline: a mapping, not values.

For every field the model fills one slot:
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
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, create_model, model_validator

from triage.schema import HEADER_FIELDS, LINE_ITEM_FIELDS, ExpenseCategory

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
            data = data.strip()
            return {"candidate": data} if _CANDIDATE_ID.match(data) else {"quote": data}
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


def response_json_schema() -> dict[str, Any]:
    """Strict variant of FieldMapping's schema: all keys required, no defaults, no extras."""
    schema = copy.deepcopy(FieldMapping.model_json_schema())

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


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def parse_mapping(raw: str) -> FieldMapping:
    text = _FENCE.sub("", _THINK.sub("", raw).strip()).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise MappingParseError(f"response is not valid JSON: {e}") from e
    try:
        return FieldMapping.model_validate(data)
    except ValidationError as e:
        raise MappingParseError(f"response does not match the schema: {e}") from e
