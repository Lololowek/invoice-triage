"""Console entry point.

triage run INVOICE.pdf [...]                 # model from LLM_* environment variables
triage run INVOICE.pdf --oracle data/gold.json [--inject transpose:total]
triage run INVOICE.pdf --json
triage candidates INVOICE.pdf [--annotated]
triage text INVOICE.pdf
triage serve [--host 127.0.0.1] [--port 8000]   # HTTP API, see triage/api.py
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

from triage.candidates import extract_candidates
from triage.env import load_env_file
from triage.llm.client import ConfigError, LLMSettings, OpenAICompatibleClient
from triage.llm.mapper import LLMMapper, Mapper
from triage.llm.oracle import OracleMapper
from triage.llm.prompt import annotate
from triage.pdf_text import NotAPdfError, NoTextLayerError, extract_text
from triage.pipeline import process_pdf
from triage.policy import RiskPolicy
from triage.result import FieldResult, InvoiceResult


def _short(value: object, width: int) -> str:
    text = "—" if value is None else str(value)
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _source(f: FieldResult) -> str:
    if f.source is None:
        return "—"
    head = f.source.candidate_id or ("quote~" if f.source.match == "fuzzy" else "quote")
    return f"{head} {f.source.text!r}"


def _row(f: FieldResult, why: str) -> str:
    return f"  {_short(f.path, 24):24} {_short(f.value, 28):28} {_short(_source(f), 30):30} {why}"


def render(result: InvoiceResult) -> str:
    out = [
        f"{result.document}   mapper: {result.mapper}   candidates: {len(result.candidates)}"
        f"   line items by: {result.line_items_source}"
    ]
    for flag in result.document_flags:
        out.append(f"  ! document: {flag.message}")
    review = [f for f in result.fields if f.needs_review]
    accepted = [f for f in result.fields if not f.needs_review]
    header = f"  {'field':24} {'value':28} {'source':30} why"
    out += ["", f"NEEDS REVIEW ({len(review)})", header]
    for f in review:
        reasons = [f"{fl.layer}: {fl.message}" for fl in f.flags]
        if f.risk == "high":
            reasons.append("high risk: always reviewed")
        out.append(_row(f, reasons[0] if reasons else ""))
        out += [" " * 87 + r for r in reasons[1:]]
    out += ["", f"ACCEPTED ({len(accepted)})", header]
    for f in accepted:
        why = "ok" if not f.flags else f"hidden, low risk: {f.flags[0].layer}: {f.flags[0].message}"
        out.append(_row(f, why))
    return "\n".join(out)


def _expand(patterns: list[str]) -> list[Path]:
    """Expand wildcards here: cmd and PowerShell pass 'data/invoices/*.pdf' through unexpanded."""
    paths: list[Path] = []
    for pattern in patterns:
        matches = sorted(glob.glob(pattern)) if glob.has_magic(pattern) else [pattern]
        if not matches:
            raise SystemExit(f"no files match {pattern}")
        paths += map(Path, matches)
    return paths


def _mapper(args: argparse.Namespace, pdf: Path) -> Mapper:
    if args.oracle:
        gold = json.loads(Path(args.oracle).read_text(encoding="utf-8"))
        document = gold["documents"].get(pdf.name)
        if document is None:
            raise SystemExit(f"{pdf.name} is not in {args.oracle}")
        return OracleMapper(document, inject=args.inject)
    if args.inject:
        raise SystemExit("--inject works only with --oracle")
    settings = LLMSettings.from_env()
    return LLMMapper(OpenAICompatibleClient(settings), answer_format=settings.answer_format)


def cmd_run(args: argparse.Namespace) -> int:
    policy = RiskPolicy.load(args.policy)
    results = []
    for pdf in _expand(args.pdf):
        result = process_pdf(pdf, _mapper(args, pdf), policy)
        results.append(result)
        if not args.json:
            print(render(result), end="\n\n")
    if args.json:
        payload = [r.model_dump(mode="json", exclude={"text", "candidates"}) for r in results]
        print(
            json.dumps(payload[0] if len(payload) == 1 else payload, ensure_ascii=False, indent=2)
        )
    return 0


def cmd_candidates(args: argparse.Namespace) -> int:
    text = extract_text(args.pdf)
    candidates = extract_candidates(text)
    if args.annotated:
        print(annotate(text, candidates))
        return 0
    for c in candidates:
        extra = ",".join(c.subtypes + c.flags)
        print(f"{c.id:5} {c.type:10} {c.value:26} {c.raw!r:30} {extra}")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from triage import evaluate

    if not args.use_oracle and args.inject:
        raise SystemExit("--inject works only with --oracle")
    args.oracle = args.gold if args.use_oracle else None
    report = evaluate.run(
        _expand(args.pdf), Path(args.gold), lambda pdf: _mapper(args, pdf),
        RiskPolicy.load(args.policy),
    )  # fmt: skip
    print(evaluate.render(report))
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nreport -> {args.out}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from triage.api import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port)
    return 0


def cmd_text(args: argparse.Namespace) -> int:
    print(extract_text(args.pdf))
    return 0


def _utf8_output() -> None:
    """Windows writes redirected output in the ANSI code page (cp1251), which has no '×' or '≠'.
    The console itself is unaffected: Python writes to it through the Unicode API."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="triage", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="process invoices and show which fields need review")
    run.add_argument("pdf", nargs="+")
    run.add_argument("--oracle", metavar="GOLD_JSON", help="offline: map from the gold annotation")
    run.add_argument(
        "--inject",
        action="append",
        default=[],
        metavar="SPEC",
        help="with --oracle: hallucinate:<field>=<v> | transpose:<field> | pick:<field>=<id>",
    )
    run.add_argument("--policy", help="risk policy TOML (default: config/risk_policy.toml)")
    run.add_argument("--json", action="store_true", help="machine-readable output")
    run.set_defaults(func=cmd_run)

    ev = sub.add_parser("eval", help="measure accuracy and silent errors against gold.json")
    ev.add_argument("pdf", nargs="+")
    ev.add_argument("--gold", default="data/gold.json")
    ev.add_argument("--oracle", dest="use_oracle", action="store_true", help="use the gold mapper")
    ev.add_argument("--inject", action="append", default=[], metavar="SPEC")
    ev.add_argument("--policy", help="risk policy TOML")
    ev.add_argument("--out", help="write the full report as JSON")
    ev.set_defaults(func=cmd_eval, oracle=None)

    cands = sub.add_parser("candidates", help="show candidates found in a PDF")
    cands.add_argument("pdf")
    cands.add_argument("--annotated", action="store_true", help="print text with [[ID]] markers")
    cands.set_defaults(func=cmd_candidates)

    text = sub.add_parser("text", help="show the extracted text")
    text.add_argument("pdf")
    text.set_defaults(func=cmd_text)

    serve = sub.add_parser("serve", help="run the HTTP API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    _utf8_output()
    load_env_file()
    try:
        return args.func(args)
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    except (NoTextLayerError, NotAPdfError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
