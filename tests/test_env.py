from pathlib import Path

import pytest

from triage.env import load_env_file, parse_env


def test_parse_env_formats() -> None:
    text = (
        "# comment\n"
        "\n"
        "LLM_MODEL=invoice-4b\n"
        'LLM_EXTRA_BODY={"reasoning_effort": "none"}\n'
        "export LLM_BASE_URL=http://localhost:11434/v1\n"
        "QUOTED='a b'\n"
        "EMPTY=\n"
    )
    assert parse_env(text) == {
        "LLM_MODEL": "invoice-4b",
        "LLM_EXTRA_BODY": '{"reasoning_effort": "none"}',
        "LLM_BASE_URL": "http://localhost:11434/v1",
        "QUOTED": "a b",
        "EMPTY": "",
    }


def test_parse_env_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="line 1"):
        parse_env("this is not a setting\n")


def test_existing_variables_win(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    # a BOM, as Notepad on Windows may write it
    path.write_text("﻿LLM_MODEL=from-file\nLLM_TIMEOUT_S=600\n", encoding="utf-8")
    environ = {"LLM_MODEL": "from-shell"}
    assert load_env_file(path, environ) == ["LLM_TIMEOUT_S"]
    assert environ == {"LLM_MODEL": "from-shell", "LLM_TIMEOUT_S": "600"}


def test_missing_file_is_fine(tmp_path: Path) -> None:
    assert load_env_file(tmp_path / ".env", {}) == []


def test_env_example_parses() -> None:
    example = Path(__file__).resolve().parents[1] / ".env.example"
    values = parse_env(example.read_text(encoding="utf-8"))
    assert values["LLM_MODEL"] and values["LLM_BASE_URL"]
