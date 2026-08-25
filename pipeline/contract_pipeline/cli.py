"""CLI: contract-pipeline analyze <pdf...> [--out DIR] [--mock] [--verbose] [--perspective provider|customer]

Writes per-contract artifacts (transcript.md, findings.json, report.md,
report.html, and -- on real runs -- model-log.md, the full audit of every
model exchange) plus a portfolio summary.md across the whole run.
"""

import argparse
import copy
import json
import os
import sys
from pathlib import Path

from openai import OpenAI

from . import ocr, analyze as analyze_mod, report, mock
from .model import render_audit_md

DEFAULT_BASE_URL = os.environ.get("MODEL_BASE_URL", "http://localhost:11434/v1")
DEFAULT_MODEL = os.environ.get("MODEL_NAME", "qwen3-vl:8b-instruct")
DEFAULT_API_KEY = os.environ.get("MODEL_API_KEY", "local")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="contract-pipeline",
        description="Find lost value in contracts using only in-network models.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("analyze", help="OCR and analyze one or more contract PDFs")
    p.add_argument("pdfs", nargs="+", help="contract PDF paths")
    p.add_argument("--out", default="reports", help="output directory (default: reports/)")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL,
                   help=f"OpenAI-compatible endpoint (default: {DEFAULT_BASE_URL})")
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help=f"model name at the endpoint (default: {DEFAULT_MODEL})")
    p.add_argument("--api-key", default=DEFAULT_API_KEY, help="API key if required")
    p.add_argument("--mock", action="store_true",
                   help="skip the model; use canned output to test the plumbing")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="print each raw model response in the terminal (the full "
                        "exchange is always saved to <name>.model-log.md regardless)")
    p.add_argument("--perspective", choices=["provider", "customer"], default="provider",
                   help="whose money is at stake: the party delivering the work and "
                        "underbilling for it (default), or the party paying and "
                        "overpaying / leaving credits unclaimed")
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    client = None
    if not args.mock:
        client = OpenAI(base_url=args.base_url, api_key=args.api_key)
        print(f"Model endpoint: {args.base_url} ({args.model})")

    results = []
    for pdf in args.pdfs:
        pdf_path = Path(pdf)
        name = pdf_path.stem
        print(f"[{name}]")
        audit = []  # one entry per model exchange; becomes <name>.model-log.md
        if args.mock:
            if args.perspective == "provider":
                transcript, fixture = mock.MOCK_TRANSCRIPT, mock.MOCK_FINDINGS
            else:
                transcript, fixture = mock.MOCK_TRANSCRIPT_CUSTOMER, mock.MOCK_FINDINGS_CUSTOMER
            findings = analyze_mod.finalize_findings(copy.deepcopy(fixture))
        else:
            transcript = ocr.ocr_pdf(client, args.model, str(pdf_path),
                                     verbose=args.verbose, audit=audit)
            findings = analyze_mod.analyze(client, args.model, transcript,
                                           perspective=args.perspective,
                                           verbose=args.verbose, audit=audit)

        (out_dir / f"{name}.transcript.md").write_text(transcript)
        (out_dir / f"{name}.findings.json").write_text(json.dumps(findings, indent=2))
        (out_dir / f"{name}.report.md").write_text(report.render_markdown(name, findings))
        (out_dir / f"{name}.report.html").write_text(report.render_html(name, findings))
        if audit:
            (out_dir / f"{name}.model-log.md").write_text(render_audit_md(name, audit))
        for i, f in enumerate(findings, 1):
            print(f"    {i}. [{f.get('category', 'other')}] {f.get('clause', '?')} — "
                  f"{report.fmt_usd(f.get('estimated_annual_value_usd'))}/yr "
                  f"({f.get('confidence', '?')} confidence)")
        value = report.total_value(findings)
        print(f"    => {len(findings)} findings, est. ${value:,.0f}/yr at stake")
        results.append((name, findings))

    (out_dir / "summary.md").write_text(report.render_summary(results))
    print(f"\nReports written to {out_dir}/ (summary.md has the portfolio view)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
