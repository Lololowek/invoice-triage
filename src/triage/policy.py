"""Risk policy: which fields a human sees. A business decision, kept out of code.

high   - always reviewed, flagged or not (bank details, the amount to pay)
medium - reviewed only when a check flagged it
low    - never shown, even when flagged (flags are still recorded for measurement)
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from triage.result import FieldResult, Risk
from triage.schema import DERIVED_FIELDS, HEADER_FIELDS, LINE_ITEM_FIELDS

DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "risk_policy.toml"
_LEVELS = ("high", "medium", "low")
KNOWN_SPECS = (
    {f.name for f in HEADER_FIELDS}
    | {f.name for f in DERIVED_FIELDS}
    | {f"line_items.{f.name}" for f in LINE_ITEM_FIELDS}
)


@dataclass(frozen=True)
class RiskPolicy:
    default: Risk = "medium"
    levels: dict[str, Risk] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path | None = None) -> RiskPolicy:
        path = Path(path or os.environ.get("TRIAGE_RISK_POLICY") or DEFAULT_POLICY_PATH)
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        default = data.get("default", "medium")
        levels = data.get("fields", {})
        for name, level in [("default", default), *levels.items()]:
            if level not in _LEVELS:
                raise ValueError(f"{path}: {name} = {level!r}, expected one of {_LEVELS}")
        unknown = set(levels) - KNOWN_SPECS
        if unknown:
            raise ValueError(f"{path}: unknown fields {sorted(unknown)}")
        return cls(default=cast(Risk, default), levels=cast(dict[str, Risk], levels))

    def risk_for(self, spec_name: str) -> Risk:
        return self.levels.get(spec_name, self.default)

    def apply(self, f: FieldResult) -> None:
        f.risk = self.risk_for(f.spec)
        if f.risk == "high":
            f.needs_review = True
            f.review_reason = "high risk: always reviewed" + (", flagged" if f.flags else "")
        elif f.risk == "low":
            f.needs_review = False
            f.review_reason = "low risk: never shown" + (
                " (flagged, logged only)" if f.flags else ""
            )
        else:
            f.needs_review = bool(f.flags)
            f.review_reason = "flagged" if f.flags else ""
