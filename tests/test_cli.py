import json
from pathlib import Path

import pytest

from triage.cli import _expand, main

from .conftest import INVOICES, ROOT


def test_cli_expands_wildcards_itself(tmp_path: Path) -> None:
    for name in ("b.pdf", "a.pdf", "c.txt"):
        (tmp_path / name).write_bytes(b"")
    assert [p.name for p in _expand([str(tmp_path / "*.pdf")])] == ["a.pdf", "b.pdf"]
    with pytest.raises(SystemExit):
        _expand([str(tmp_path / "*.doc")])


def test_run_with_oracle_and_injection(capsys: pytest.CaptureFixture[str]) -> None:
    code = main([
        "run", str(INVOICES / "inv_06_ru_marketing.pdf"),
        "--oracle", str(ROOT / "data" / "gold.json"),
        "--inject", "hallucinate:contract_number=ДГ-2026/017",
        "--json",
    ])  # fmt: skip
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    contract = next(f for f in result["fields"] if f["path"] == "contract_number")
    assert contract["needs_review"] is True


def test_missing_model_settings_exit_with_a_hint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)  # no .env here
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert main(["run", str(INVOICES / "inv_07_uk_software.pdf")]) == 2
    assert "LLM_MODEL" in capsys.readouterr().err
