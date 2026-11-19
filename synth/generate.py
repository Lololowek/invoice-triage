"""Generate the synthetic invoices and their gold annotation.

    python -m synth.generate            # writes data/invoices/*.pdf and data/gold.json

Real invoices are not used: they carry other people's personal and banking data.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from synth.layouts import register_fonts, render
from synth.specs import DOCS

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=ROOT / "data")
    args = parser.parse_args(argv)

    register_fonts()
    invoices = args.out / "invoices"
    invoices.mkdir(parents=True, exist_ok=True)
    gold = {
        "version": 1,
        "description": "Correct field values for the synthetic invoices. Values are normalized "
        "the way the pipeline normalizes them: ISO dates, decimal amounts, compact identifiers, "
        "ISO currency codes, text exactly as printed. null = not in the document.",
        "documents": {},
    }
    for doc in DOCS:
        render(doc, invoices / doc.file)
        gold["documents"][doc.file] = doc.gold()
        print(f"  {doc.file}")
    (args.out / "gold.json").write_text(
        json.dumps(gold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{len(DOCS)} invoices -> {invoices}, gold -> {args.out / 'gold.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
