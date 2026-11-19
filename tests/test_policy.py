from pathlib import Path

import pytest

from triage.policy import RiskPolicy
from triage.result import FieldResult
from triage.schema import FieldKind


def field(spec: str, flagged: bool) -> FieldResult:
    f = FieldResult(path=spec, spec=spec, kind=FieldKind.TEXT, value="x")
    if flagged:
        f.flag("grounding", "quote_not_found", "test")
    return f


@pytest.mark.parametrize(
    ("spec", "flagged", "shown"),
    [
        ("total", False, True),  # high: always
        ("total", True, True),
        ("contract_number", False, False),  # medium: only when flagged
        ("contract_number", True, True),
        ("payment_terms", False, False),  # low: never
        ("payment_terms", True, False),
    ],
)
def test_default_policy(policy: RiskPolicy, spec: str, flagged: bool, shown: bool) -> None:
    f = field(spec, flagged)
    policy.apply(f)
    assert f.needs_review is shown


def test_low_risk_keeps_its_flags_for_measurement(policy: RiskPolicy) -> None:
    f = field("payment_terms", flagged=True)
    policy.apply(f)
    assert f.flags and not f.needs_review
    assert "logged only" in f.review_reason


def test_line_item_fields_use_the_spec_name(tmp_path: Path) -> None:
    path = tmp_path / "policy.toml"
    path.write_text('default = "low"\n[fields]\n"line_items.amount" = "high"\n', encoding="utf-8")
    policy = RiskPolicy.load(path)
    assert policy.risk_for("line_items.amount") == "high"
    assert policy.risk_for("total") == "low"


@pytest.mark.parametrize(
    "content",
    ['default = "urgent"\n', '[fields]\ntotl = "high"\n', '[fields]\ntotal = "critical"\n'],
)
def test_policy_rejects_typos(tmp_path: Path, content: str) -> None:
    path = tmp_path / "policy.toml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        RiskPolicy.load(path)
