"""Findings -> per-contract markdown/HTML reports and a run summary."""

import html
import re


def fmt_usd(value) -> str:
    """Dollar-format a computed value; unquantified findings show as n/a."""
    return f"${value:,.0f}" if isinstance(value, (int, float)) else "n/a"


def total_value(findings: list[dict]) -> float:
    """Sum the computed annual values, skipping unquantified findings."""
    return sum(f.get("estimated_annual_value_usd") or 0 for f in findings)


def fmt_total(findings: list[dict]) -> str:
    """Format the known total without turning wholly unquantified work into $0."""
    quantified = [
        f["estimated_annual_value_usd"]
        for f in findings
        if isinstance(f.get("estimated_annual_value_usd"), (int, float))
    ]
    if not quantified:
        return "n/a" if findings else "$0"
    suffix = " quantified" if len(quantified) != len(findings) else ""
    return f"{fmt_usd(sum(quantified))}{suffix}"


def _md(value) -> str:
    """Neutralize HTML and Markdown syntax in model-derived text."""
    escaped_html = html.escape(str(value or ""), quote=False)
    escaped = re.sub(r"([\\`*{}\[\]()!_|])", r"\\\1", escaped_html)
    escaped = re.sub(r"(?m)^([ \t]{0,3})([#>+\-])", r"\1\\\2", escaped)
    return re.sub(r"(?m)^([ \t]{0,3})(\d+)([.)])(?=\s)", r"\1\2\\\3", escaped)


def _md_one_line(value) -> str:
    return " ".join(_md(value).splitlines())


def _math_line(f: dict) -> str:
    """Human-auditable math for a finding, or why there is no number."""
    if f.get("estimated_annual_value_usd") is not None and f.get("annual_value_formula"):
        notes = f" — {f['formula_notes']}" if f.get("formula_notes") else ""
        return f"{f['annual_value_formula']} = {fmt_usd(f['estimated_annual_value_usd'])}{notes}"
    if f.get("value_note"):
        return f"not computed — {f['value_note']}"
    return "no defensible dollar figure in the contract"


def _math_markdown(f: dict) -> str:
    """Markdown math with only the validated formula placed in a code span."""
    if f.get("estimated_annual_value_usd") is not None and f.get("annual_value_formula"):
        notes = f" — {_md(f['formula_notes'])}" if f.get("formula_notes") else ""
        return (
            f"`{f['annual_value_formula']}` = "
            f"{fmt_usd(f['estimated_annual_value_usd'])}{notes}"
        )
    if f.get("value_note"):
        return f"not computed — {_md(f['value_note'])}"
    return "no defensible dollar figure in the contract"


def render_markdown(contract_name: str, findings: list[dict]) -> str:
    """One contract's report as markdown: a section per finding, math shown."""
    lines = [
        f"# Lost-Value Report: {_md_one_line(contract_name)}",
        "",
        f"**Findings:** {len(findings)}  |  "
        f"**Estimated annual value at stake:** {fmt_total(findings)}",
        "",
        "*Candidate analysis for human review; not legal or accounting advice.*",
        "",
    ]
    for i, f in enumerate(findings, 1):
        quote = _md(f.get("quote", ""))
        quote_block = "\n".join(f"> {line}" for line in quote.splitlines()) or "> "
        lines += [
            f"## {i}. [{_md_one_line(f.get('category', 'other'))}] "
            f"{_md_one_line(f.get('clause', ''))} "
            f"— {fmt_usd(f.get('estimated_annual_value_usd'))} "
            f"({_md_one_line(f.get('confidence', '?'))} confidence)",
            "",
            quote_block,
            "",
            f"**Issue:** {_md(f.get('issue', ''))}",
            "",
            f"**Math:** {_math_markdown(f)}",
            "",
            f"**Recommended action:** {_md(f.get('action', ''))}",
            "",
        ]
        if f.get("evidence_note"):
            lines += [f"**Evidence check:** {_md(f['evidence_note'])}", ""]
    lines.append("---")
    lines.append("*The demo enclave keeps document content inside its configured environment.*")
    return "\n".join(lines)


def render_html(contract_name: str, findings: list[dict]) -> str:
    """One contract's report as a self-contained HTML page (inline CSS, no assets)."""
    e = html.escape
    rows = "\n".join(
        f"<tr><td>{e(str(f.get('category', '')))}</td>"
        f"<td>{e(str(f.get('clause', '')))}</td>"
        f"<td class='num'>{fmt_usd(f.get('estimated_annual_value_usd'))}</td>"
        f"<td>{e(str(f.get('confidence', '')))}</td>"
        f"<td>{e(str(f.get('issue', '')))}<br>"
        f"<blockquote>{e(str(f.get('quote', '')))}</blockquote>"
        f"<b>Math:</b> {e(_math_line(f))}<br>"
        f"<b>Action:</b> {e(str(f.get('action', '')))}"
        + (f"<br><b>Evidence check:</b> {e(str(f['evidence_note']))}" if f.get("evidence_note") else "")
        + "</td></tr>"
        for f in findings
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>Lost-Value Report: {e(contract_name)}</title>
<style>
  /* The palette is light-only, so both the background and the scheme are
     pinned; without them, dark-mode browsers paint a dark ground under the
     dark text and the report becomes unreadable. */
  body {{ font: 15px/1.5 -apple-system, Segoe UI, sans-serif; margin: 2rem auto; max-width: 60rem; padding: 0 1rem; color: #1a202c; background: #fff; }}
  h1 {{ font-size: 1.4rem; }}
  .kpi {{ font-size: 1.1rem; margin-bottom: 1.5rem; }}
  .kpi b {{ color: #b7791f; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #cbd5e0; padding: .5rem .6rem; text-align: left; vertical-align: top; }}
  th {{ background: #edf2f7; }}
  td.num {{ white-space: nowrap; font-variant-numeric: tabular-nums; }}
  blockquote {{ margin: .4rem 0; padding: .2rem .6rem; border-left: 3px solid #cbd5e0; color: #4a5568; font-style: italic; }}
  footer {{ margin-top: 1.5rem; color: #718096; font-size: .85rem; }}
</style>
</head>
<body>
<h1>Lost-Value Report: {e(contract_name)}</h1>
<p class="kpi">{len(findings)} findings &middot; estimated annual value at stake:
<b>{fmt_total(findings)}</b></p>
<p><i>Candidate analysis for human review; not legal or accounting advice.</i></p>
<table>
<thead><tr><th scope="col">Category</th><th scope="col">Clause</th><th scope="col">Est. annual value</th><th scope="col">Confidence</th><th scope="col">Detail</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
<footer>The demo enclave keeps document content inside its configured environment.</footer>
</body>
</html>
"""


def render_summary(results: list[tuple[str, list[dict]]]) -> str:
    """Portfolio view across the whole run: one table row per contract."""
    all_findings = [finding for _, findings in results for finding in findings]
    lines = [
        "# Portfolio Summary",
        "",
        f"**Contracts analyzed:** {len(results)}  |  "
        f"**Total estimated annual value at stake:** {fmt_total(all_findings)}",
        "",
        "*Totals include quantified findings only. Candidate analysis for human review; not legal or accounting advice.*",
        "",
        "| Contract | Findings | Est. annual value |",
        "|---|---|---|",
    ]
    for name, findings in results:
        lines.append(f"| {_md_one_line(name)} | {len(findings)} | {fmt_total(findings)} |")
    return "\n".join(lines) + "\n"
