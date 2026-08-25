"""Contract transcription -> structured lost-value findings.

The model is good at spotting a clause and the mismatch behind it, and bad at
arithmetic. So it never reports a dollar figure. It returns a formula built
from numbers in the contract; the pipeline evaluates that deterministically
and the report shows the math next to the result.

Two perspectives, because they're genuinely different asks:
  provider (default) -- the client DELIVERS the services/goods in the
    contract and wants to know what they're contractually owed but aren't
    collecting: missed escalations, unbilled overage or emergency work,
    discounts that should have expired, minimum commitments never trued up.
  customer -- the client RECEIVES the services and wants to know what
    they're overpaying or leaving unclaimed.
"""

import ast
import json
import operator
import re

from openai import OpenAI

from .model import chat

_ROLE_FRAMING = {
    "provider": '''Your client is the party that DELIVERS the services or goods described
in the contract below -- the Provider, Vendor, Licensor, or Contractor; the
party that issues the invoices. Find revenue this contract entitles them to
that they are not currently collecting. Look for, at minimum:

- unbilled_escalation: a rate increase or CPI adjustment the contract allows
  that was never invoiced
- unbilled_services: overage charges, after-hours or emergency work, change
  orders, or pass-through expenses the contract allows to be billed
  separately, that appear to have been delivered but never billed
- expired_discount_continued: a promotional or time-limited discount still
  being applied after its contractual expiration date
- minimum_commitment_shortfall: a minimum spend, minimum purchase, or
  take-or-pay commitment the other party owes, where billing reflects only
  their lower actual usage
- lapsed_contract_continued_service: services still being delivered after
  the term or a renewal deadline lapsed, with no new agreement or updated rate
- missed_true_up: a reconciliation or usage true-up the contract requires
  that does not appear to have happened''',
    "customer": '''Your client is the party that RECEIVES the services or goods described
in the contract below -- the Customer or Licensee. Find money they are
leaving on the table. Look for, at minimum:

- auto_renewal: renewal or notice windows that are approaching or were missed
- price_escalation: increases applied above a contractual cap
- unclaimed_credits: SLA or service credits they are entitled to but appear
  never to have claimed
- unclaimed_discounts: volume or tier discounts they qualify for but are not
  receiving
- billing_overlap: items billed separately that another clause already
  includes
- overprovisioning: committed quantities well above actual usage shown
- termination_exposure: fees or penalties that constrain renegotiation''',
}

_SHARED_INSTRUCTIONS = '''

Use the exhibits (rate schedules, usage reports, invoice history, service
logs) as evidence. Quote the exact contract language that supports each
finding.

DOLLAR VALUES: do NOT calculate them. Instead give "annual_value_formula": an
arithmetic expression that uses ONLY literal numbers taken from the contract
and its exhibits (plus 12 for months, 4 for quarters, 100 for percentages).
Use + - * / and parentheses only. The system evaluates it; you just write it.
Explain every number in "formula_notes". Use null for both when the contract
gives no defensible numbers (for example an approaching notice deadline).

The formula must equal ONE YEAR of value:
- Amounts that are already annual are never multiplied by 12.
- Monthly amounts are multiplied by 12; quarterly amounts by 4.
- Use the most recent full year or annualize a clear recent trend -- never
  add up several past years, and never treat a one-off historical shortfall
  as if it recurs forever.
- If the evidence covers less than a full year (e.g. a log of calls spanning
  7 months), scale it explicitly: divide by the number of months or quarters
  the evidence actually covers, then multiply by 12 or 4. Never write a
  scaling step that cancels itself out, like "* 12 / 12" -- that silently
  reports the partial-period total as if it were the annual figure.

Return ONLY a JSON object, no prose before or after, in this shape:
{
  "findings": [
    {
      "category": "<one of the category names from the list above>",
      "clause": "Section 5.3",
      "quote": "short exact quote from the contract",
      "issue": "plain-English explanation of the problem or opportunity",
      "annual_value_formula": "840000 * 0.03",
      "formula_notes": "explain what each number in the formula is and where it came from",
      "action": "what the client should do about it",
      "confidence": "high"
    }
  ]
}

confidence must be one of: high, medium, low.

CONTRACT (markdown transcription):
<contract>
__CONTRACT_MD__
</contract>
'''

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


def build_prompt(perspective: str, contract_md: str) -> str:
    if perspective not in _ROLE_FRAMING:
        raise ValueError(f"unknown perspective: {perspective!r} (want one of {sorted(_ROLE_FRAMING)})")
    body = _SHARED_INSTRUCTIONS.replace("__CONTRACT_MD__", contract_md)
    return f"You are a contract-recovery analyst. {_ROLE_FRAMING[perspective]}\n{body}"


def safe_eval(expr: str) -> float:
    """Evaluate plain arithmetic: numbers, + - * /, unary minus, parentheses.

    Anything else (names, calls, attributes, powers) is rejected, so model
    output can never execute code.
    """
    cleaned = (
        str(expr)
        .replace("$", "").replace(",", "").replace("USD", "")
        .replace("×", "*").replace("−", "-").replace("–", "-")
        .replace("%", "/100")
        .strip()
    )

    def _ev(node):
        if isinstance(node, ast.Expression):
            return _ev(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](_ev(node.left), _ev(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -_ev(node.operand)
        raise ValueError(f"disallowed element in formula: {type(node).__name__}")

    return float(_ev(ast.parse(cleaned, mode="eval")))


def finalize_findings(findings: list[dict]) -> list[dict]:
    """Compute each dollar value from its formula. Model arithmetic is discarded."""
    for f in findings:
        f.pop("estimated_annual_value_usd", None)
        f["estimated_annual_value_usd"] = None
        formula = f.get("annual_value_formula")
        if not formula:
            continue
        try:
            value = safe_eval(formula)
        except (ValueError, SyntaxError, ZeroDivisionError, TypeError) as exc:
            f["value_note"] = f"formula could not be evaluated ({type(exc).__name__}): {formula}"
            continue
        if value <= 0:
            f["value_note"] = f"formula evaluated to {value:,.0f}; needs review: {formula}"
            continue
        f["estimated_annual_value_usd"] = round(value)

    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(
        key=lambda f: (
            order.get(f.get("confidence", "low"), 3),
            -(f.get("estimated_annual_value_usd") or 0),
        )
    )
    return findings


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model response, tolerating fences."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"No JSON object found in model response:\n{text[:500]}")
    return json.loads(text[start : end + 1])


def analyze(client: OpenAI, model: str, contract_md: str, perspective: str = "provider",
            log=print, verbose: bool = False, audit=None) -> list[dict]:
    """Return the finalized list of findings for one transcribed contract."""
    text = chat(
        client, model,
        messages=[{"role": "user", "content": build_prompt(perspective, contract_md)}],
        purpose=f"find lost value ({perspective} perspective)",
        audit=audit, log=log, verbose=verbose,
    )
    data = extract_json(text)
    return finalize_findings(data.get("findings", []))
