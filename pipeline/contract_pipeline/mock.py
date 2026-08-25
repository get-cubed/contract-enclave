"""Canned transcripts and findings so the pipeline plumbing runs with no model.

Two sets, matching the two --perspective modes. Dollar values are computed
by analyze.finalize_findings from the formulas, exactly as for real model
output, so these exercise the same code path.
"""

# --- provider (default): revenue the contract entitles them to but they
# aren't collecting -----------------------------------------------------

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
        "clause": "Section 5.2",
        "quote": "Provider shall apply a discount of five percent (5%) to fees "
        "invoiced during the first twelve (12) months of the Initial Term "
        "only, through December 31, 2024",
        "issue": "The introductory discount expired at the end of 2024, but "
        "invoices through 2026 still reflect the discounted rate.",
        "annual_value_formula": "840000 * 0.05",
        "formula_notes": "5% of the $840,000 base fee, still being given away "
        "two years after the discount's contractual end date",
        "action": "Revert invoicing to the full rate and back-bill the gap "
        "for 2025 and 2026.",
        "confidence": "high",
    },
    {
        "category": "unbilled_escalation",
        "clause": "Section 5.3",
        "quote": "Provider may increase the annual base fee once per "
        "contract year by up to three percent (3%)",
        "issue": "No annual increase has ever been applied, despite the "
        "contract permitting one every year since the Effective Date.",
        "annual_value_formula": "840000 * 0.03",
        "formula_notes": "3% escalation the contract allows on the $840,000 "
        "base fee, never invoiced",
        "action": "Apply the escalation at the next contract anniversary and "
        "invoice accordingly.",
        "confidence": "high",
    },
]

# --- customer (--perspective customer): money they're overpaying or not
# claiming ----------------------------------------------------------------

MOCK_TRANSCRIPT_CUSTOMER = """\
# MASTER SERVICES AGREEMENT (MOCK)

## 3. Term and Renewal
3.2 This Agreement automatically renews for successive twelve (12) month
terms at 105% of current fees unless either party gives written notice at
least ninety (90) days prior to the end of the then-current term.

## 5. Fees
5.1 Annual base fee: $840,000.
5.3 Annual rate increases shall not exceed three percent (3%).
"""

MOCK_FINDINGS_CUSTOMER = [
    {
        "category": "auto_renewal",
        "clause": "Section 3.2",
        "quote": "automatically renews for successive twelve (12) month "
        "terms at 105% of current fees unless either party gives written "
        "notice",
        "issue": "The renewal notice window closes soon; missing it locks "
        "in another 12 months at a 5% uplift.",
        "annual_value_formula": "840000 * 5 / 100",
        "formula_notes": "$840,000 annual base fee times the 5% renewal uplift",
        "action": "Calendar the notice deadline and open renegotiation now.",
        "confidence": "high",
    },
    {
        "category": "price_escalation",
        "clause": "Section 5.3",
        "quote": "Annual rate increases shall not exceed three percent (3%)",
        "issue": "Invoice history shows 6% increases applied in each of the "
        "last two years, above the contractual cap.",
        "annual_value_formula": "(890400 - 865200) + (943824 - 891156)",
        "formula_notes": "2025 invoiced $890,400 vs $865,200 at the 3% cap; "
        "2026 invoiced $943,824 vs $891,156 at the cap",
        "action": "Demand a retroactive credit for the overage and "
        "corrected rates going forward.",
        "confidence": "medium",
    },
]
