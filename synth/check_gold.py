"""Verify gold.json against the PDFs, through the same text extraction the pipeline uses.

For every document and gold field:
- text fields must occur in the extracted text (exact, whitespace-normalized);
- dates, amounts, identifiers and currencies must be among the extracted candidates.

A miss means either the gold is wrong or the candidate extractor has a gap; both must be fixed
before the gold can be used to measure anything.

    python -m synth.check_gold
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from triage.candidates import extract_candidates
from triage.checks.grounding import find_exact
from triage.llm.oracle import _matches
from triage.pdf_text import extract_text
from triage.schema import HEADER_FIELDS, LINE_ITEM_FIELDS, FieldKind, FieldSpec

ROOT = Path(__file__).resolve().parents[1]


def check_document(pdf: Path, gold: dict) -> list[str]:
    text = extract_text(pdf)
    candidates = extract_candidates(text)
    problems = []

    def check(path: str, spec: FieldSpec, value: object) -> None:
        if value is None:
            return
        value = str(value)
        if spec.kind is FieldKind.TEXT:
            if find_exact(text, value, numeric=False) is None:
                problems.append(f"{path}: text {value!r} not found in extracted text")
        elif not any(_matches(spec, c, value) for c in candidates):
            problems.append(f"{path}: {spec.kind.value} {value!r} is not among the candidates")

    for spec in HEADER_FIELDS:
        check(spec.name, spec, gold["fields"].get(spec.name))
    for i, item in enumerate(gold["line_items"]):
        for spec in LINE_ITEM_FIELDS:
            check(f"line_items[{i}].{spec.name}", spec, item.get(spec.name))
    return problems


def main() -> int:
    gold = json.loads((ROOT / "data" / "gold.json").read_text(encoding="utf-8"))
    failed = 0
    for name, document in gold["documents"].items():
        problems = check_document(ROOT / "data" / "invoices" / name, document)
        status = "ok" if not problems else f"{len(problems)} problem(s)"
        print(f"{name:32} {status}")
        for p in problems:
            print(f"    {p}")
        failed += bool(problems)
    print(f"\n{len(gold['documents']) - failed}/{len(gold['documents'])} documents fully covered")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
