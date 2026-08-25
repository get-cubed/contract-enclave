"""Findings -> per-contract markdown/HTML reports and a run summary."""

import html


def fmt_usd(value) -> str:
    """Dollar-format a computed value; unquantified findings show as n/a."""
    return f"${value:,.0f}" if isinstance(value, (int, float)) else "n/a"


def total_value(findings: list[dict]) -> float:
    """Sum the computed annual values, skipping unquantified findings."""
    return sum(f.get("estimated_annual_value_usd") or 0 for f in findings)


def _math_line(f: dict) -> str:
    """Human-auditable math for a finding, or why there is no number."""
    if f.get("estimated_annual_value_usd") is not None and f.get("annual_value_formula"):
        notes = f" — {f['formula_notes']}" if f.get("formula_notes") else ""
        return f"`{f['annual_value_formula']}` = {fmt_usd(f['estimated_annual_value_usd'])}{notes}"
    if f.get("value_note"):
        return f"not computed — {f['value_note']}"
    return "no defensible dollar figure in the contract"


def render_markdown(contract_name: str, findings: list[dict]) -> str:
    """One contract's report as markdown: a section per finding, math shown."""
    lines = [
        f"# Lost-Value Report: {contract_name}",
        "",
        f"**Findings:** {len(findings)}  |  "
        f"**Estimated annual value at stake:** {fmt_usd(total_value(findings))}",
        "",
    ]
    for i, f in enumerate(findings, 1):
        lines += [
            f"## {i}. [{f.get('category', 'other')}] {f.get('clause', '')} "
            f"— {fmt_usd(f.get('estimated_annual_value_usd'))} "
            f"({f.get('confidence', '?')} confidence)",
            "",
            f"> {f.get('quote', '')}",
            "",
            f"**Issue:** {f.get('issue', '')}",
            "",
            f"**Math:** {_math_line(f)}",
            "",
            f"**Recommended action:** {f.get('action', '')}",
            "",
        ]
    lines.append("---")
    lines.append("*Generated in-network. No document content left this environment.*")
    return "\n".join(lines)


def render_html(contract_name: str, findings: list[dict]) -> str:
    """One contract's report as a self-contained HTML page (inline CSS, no assets)."""
    e = html.escape
    rows = "\n".join(
        f"<tr><td>{e(f.get('category', ''))}</td>"
        f"<td>{e(str(f.get('clause', '')))}</td>"
        f"<td class='num'>{fmt_usd(f.get('estimated_annual_value_usd'))}</td>"
        f"<td>{e(f.get('confidence', ''))}</td>"
        f"<td>{e(f.get('issue', ''))}<br>"
        f"<blockquote>{e(f.get('quote', ''))}</blockquote>"
        f"<b>Math:</b> {e(_math_line(f))}<br>"
        f"<b>Action:</b> {e(f.get('action', ''))}</td></tr>"
        for f in findings
    )
    return f"""<!doctype html>
<meta charset="utf-8">
<title>Lost-Value Report: {e(contract_name)}</title>
<style>
  body {{ font: 15px/1.5 -apple-system, Segoe UI, sans-serif; margin: 2rem auto; max-width: 60rem; padding: 0 1rem; color: #1a202c; }}
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
<h1>Lost-Value Report: {e(contract_name)}</h1>
<p class="kpi">{len(findings)} findings &middot; estimated annual value at stake:
<b>{fmt_usd(total_value(findings))}</b></p>
<table>
<tr><th>Category</th><th>Clause</th><th>Est. annual value</th><th>Confidence</th><th>Detail</th></tr>
{rows}
</table>
<footer>Generated in-network. No document content left this environment.</footer>
"""


def render_summary(results: list[tuple[str, list[dict]]]) -> str:
    """Portfolio view across the whole run: one table row per contract."""
    grand = sum(total_value(f) for _, f in results)
    lines = [
        "# Portfolio Summary",
        "",
        f"**Contracts analyzed:** {len(results)}  |  "
        f"**Total estimated annual value at stake:** {fmt_usd(grand)}",
        "",
        "| Contract | Findings | Est. annual value |",
        "|---|---|---|",
    ]
    for name, findings in results:
        lines.append(f"| {name} | {len(findings)} | {fmt_usd(total_value(findings))} |")
    return "\n".join(lines) + "\n"
