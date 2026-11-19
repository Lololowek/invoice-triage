""".env loading, so that settings work the same on Windows (no `set -a; . ./.env`) and Linux.

Rules:
- KEY=VALUE per line; blank lines and lines starting with # are skipped; `export KEY=...` works;
- the value is everything after the first '=', so JSON values need no escaping;
- one pair of surrounding quotes is removed;
- variables already set in the environment win: the file is a default, not an override.
"""

from __future__ import annotations

import os
import re
from collections.abc import MutableMapping
from pathlib import Path

_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").lstrip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not _KEY.match(key):
            raise ValueError(f".env line {number}: expected KEY=VALUE, got {line!r}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def load_env_file(
    path: str | Path = ".env", environ: MutableMapping[str, str] = os.environ
) -> list[str]:
    """Load `path` into `environ` without overriding; return the names that were set."""
    path = Path(path)
    if not path.is_file():
        return []
    loaded = []
    # utf-8-sig: Notepad on Windows may save a BOM
    for key, value in parse_env(path.read_text(encoding="utf-8-sig")).items():
        if key not in environ:
            environ[key] = value
            loaded.append(key)
    return loaded
