"""Measure the pipeline against the gold annotation.

For every field of every document: is the value right, was it flagged, did it go to a human?
The number that matters most is SILENT ERRORS: wrong values that were accepted without review.
Everything else (accuracy, review load, false alarms) is context for that number.

    triage eval data/invoices/*.pdf --gold data/gold.json [--oracle] [--out results.json]
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from triage import idformats
from triage.llm.mapper import Mapper
from triage.normalize import collapse_ws
from triage.pipeline import process_pdf
from triage.policy import RiskPolicy
from triage.result import FieldResult, InvoiceResult
from triage.schema import HEADER_FIELDS, LINE_ITEM_FIELDS, FieldKind, spec_for


@dataclass
class FieldOutcome:
    document: str
    path: str
    spec: str
    gold: Any
    predicted: Any
    correct: bool
    flagged: bool
    reviewed: bool
    flags: list[str]


def same_value(kind: FieldKind, predicted: Any, gold: Any) -> bool:
    if predicted is None or gold is None:
        return predicted is None and gold is None
    if kind in (FieldKind.MONEY, FieldKind.NUMBER):
        try:
            return Decimal(str(predicted)) == Decimal(str(gold))
        except InvalidOperation:
            return False
    if kind is FieldKind.TEXT:
        return collapse_ws(str(predicted)).casefold() == collapse_ws(str(gold)).casefold()
    if kind is FieldKind.IDENTIFIER:
        return idformats.compact(str(predicted)) == idformats.compact(str(gold))
    return predicted == gold


def compare(result: InvoiceResult, gold: dict[str, Any]) -> list[FieldOutcome]:
    by_path = {f.path: f for f in result.fields}
    expected: dict[str, Any] = {}
    for spec in HEADER_FIELDS:
        expected[spec.name] = gold["fields"].get(spec.name)
    for i, item in enumerate(gold.get("line_items", [])):
        for spec in LINE_ITEM_FIELDS:
            expected[f"line_items[{i}].{spec.name}"] = item.get(spec.name)
    for name, value in gold.get("derived", {}).items():
        expected[name] = value
    # Rows the model invented are errors too: compare them against "nothing".
    for path in by_path:
        expected.setdefault(path, None)

    outcomes = []
    for path, gold_value in expected.items():
        f: FieldResult | None = by_path.get(path)
        spec_name = f.spec if f else _spec_name(path)
        predicted = f.value if f else None
        outcomes.append(
            FieldOutcome(
                document=result.document,
                path=path,
                spec=spec_name,
                gold=gold_value,
                predicted=predicted,
                correct=same_value(spec_for(spec_name).kind, predicted, gold_value),
                flagged=bool(f and f.flags),
                reviewed=bool(f and f.needs_review),
                flags=[fl.code for fl in f.flags] if f else ["row_missing"],
            )
        )
    return outcomes


def _spec_name(path: str) -> str:
    return "line_items." + path.split(".", 1)[1] if path.startswith("line_items[") else path


def summarize(outcomes: list[FieldOutcome], seconds: list[float]) -> dict[str, Any]:
    n = len(outcomes)
    wrong = [o for o in outcomes if not o.correct]
    per_spec: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for o in outcomes:
        per_spec[o.spec][0] += 1
        per_spec[o.spec][1] += o.correct
    return {
        "documents": len(seconds),
        "fields": n,
        "accuracy": round(1 - len(wrong) / n, 4) if n else None,
        "wrong": len(wrong),
        "wrong_flagged": sum(o.flagged for o in wrong),
        "silent_errors": sum(not o.reviewed for o in wrong),
        "false_alarms": sum(o.flagged for o in outcomes if o.correct),
        "review_load": round(sum(o.reviewed for o in outcomes) / n, 4) if n else None,
        "seconds_per_doc": round(sum(seconds) / len(seconds), 1) if seconds else None,
        "seconds_max": round(max(seconds), 1) if seconds else None,
        "per_field": {
            spec: {"total": total, "correct": correct}
            for spec, (total, correct) in sorted(per_spec.items())
        },
    }


def run(pdfs: list[Path], gold_path: Path, make_mapper, policy: RiskPolicy) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    gold = json.loads(gold_path.read_text(encoding="utf-8"))["documents"]
    outcomes: list[FieldOutcome] = []
    seconds: list[float] = []
    for pdf in pdfs:
        if pdf.name not in gold:
            print(f"skip {pdf.name}: not in gold")
            continue
        mapper: Mapper = make_mapper(pdf)
        start = time.perf_counter()
        result = process_pdf(pdf, mapper, policy)
        seconds.append(time.perf_counter() - start)
        doc_outcomes = compare(result, gold[pdf.name])
        outcomes += doc_outcomes
        bad = [o for o in doc_outcomes if not o.correct]
        silent = [o for o in bad if not o.reviewed]
        print(
            f"{pdf.name:30} {seconds[-1]:6.1f}s  wrong {len(bad):2}  silent {len(silent):2}",
            flush=True,
        )
    return {"summary": summarize(outcomes, seconds), "outcomes": [asdict(o) for o in outcomes]}


def render(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        "",
        f"documents {s['documents']}   fields {s['fields']}   accuracy {s['accuracy']:.1%}",
        f"wrong {s['wrong']}: flagged {s['wrong_flagged']}, "
        f"SILENT (accepted unseen) {s['silent_errors']}",
        f"false alarms {s['false_alarms']}   review load {s['review_load']:.1%}   "
        f"time {s['seconds_per_doc']}s/doc (max {s['seconds_max']}s)",
        "",
        "fields with errors:",
    ]
    for spec, counts in s["per_field"].items():
        if counts["correct"] < counts["total"]:
            lines.append(f"  {spec:26} {counts['correct']:3}/{counts['total']}")
    silent = [o for o in report["outcomes"] if not o["correct"] and not o["reviewed"]]
    if silent:
        lines += ["", "silent errors:"]
        for o in silent:
            lines.append(
                f"  {o['document'][:22]:22} {o['path']:26} got {str(o['predicted'])[:30]!r:34} "
                f"want {str(o['gold'])[:30]!r}"
            )
    return "\n".join(lines)
