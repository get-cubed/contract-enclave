"""Canned provider-recovery findings so the plumbing runs with no model.

Dollar values are computed by analyze.finalize_findings from the formulas,
exactly as for real model output, so these exercise the same code path.
"""

# Revenue the provider may be entitled to but is not collecting.

MOCK_TRANSCRIPT = """\
# MASTER SERVICES AGREEMENT (MOCK)

## 5. Fees
5.1 Annual base fee: $840,000.
5.2 Provider shall apply a discount of five percent (5%) to fees invoiced
during the first twelve (12) months of the Initial Term only, through
December 31, 2024. Invoicing thereafter reverts to the full fee schedule.
5.3 Provider may increase the annual base fee once per contract year by up
to three percent (3%).

## Exhibit B - Invoice History
2024: $798,000 (5% discount correctly applied)
2025: $798,000 (discount continued past expiration; no escalation applied)
2026: $798,000 (discount continued past expiration; no escalation applied)
"""

MOCK_FINDINGS = [
    {
        "category": "expired_discount_continued",
        "beneficiary_role": "provider",
        "clause": "Section 5.2",
        "quote": "Provider shall apply a discount of five percent (5%) to fees "
        "invoiced during the first twelve (12) months of the Initial Term "
        "only, through December 31, 2024",
        "issue": "The introductory discount expired at the end of 2024, but "
        "invoices through 2026 still reflect the discounted rate.",
        "monthly_value_formula": "840000 * 5 / 100 / 12",
        "formula_notes": "5% of the $840,000 base fee, still being given away "
        "two years after the discount's contractual end date",
        "action": "Revert invoicing to the full rate and back-bill the gap "
        "for 2025 and 2026.",
        "confidence": "high",
    },
    {
        "category": "unbilled_escalation",
        "beneficiary_role": "provider",
        "clause": "Section 5.3",
        "quote": "Provider may increase the annual base fee once per "
        "contract year by up to three percent (3%)",
        "issue": "No annual increase has ever been applied, despite the "
        "contract permitting one every year since the Effective Date.",
        "monthly_value_formula": "840000 * 3 / 100 / 12",
        "formula_notes": "3% escalation the contract allows on the $840,000 "
        "base fee, never invoiced",
        "action": "Apply the escalation at the next contract anniversary and "
        "invoice accordingly.",
        "confidence": "high",
    },
]
