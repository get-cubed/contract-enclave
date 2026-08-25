# /// script
# requires-python = ">=3.10"
# dependencies = ["fpdf2>=2.7"]
# ///
"""Generate synthetic contract PDFs with planted revenue leakage for the demo.

The client in both contracts is the PROVIDER (Meridian, Northgate) -- the
party delivering the work -- because that's who this tool is actually built
for: vendors who aren't collecting everything their own contracts entitle
them to. The exhibits also plant customer-side findings so the
--perspective flag has something to find in both directions. Every document
is clearly footered as fictitious.

The ANSWER KEY comment at the top of each build_* function lists what was
planted and the expected math -- use it to grade the model's findings.

Run with:  uv run generate.py
"""

from fpdf import FPDF
from fpdf.enums import XPos, YPos

FOOTER = (
    "SYNTHETIC SAMPLE - All parties, terms, and amounts are fictitious. "
    "Generated for product demo."
)


class ContractPDF(FPDF):
    def __init__(self):
        super().__init__(orientation="P", format="Letter")
        self.set_auto_page_break(auto=True, margin=25)
        self.set_margins(22, 20, 22)

    def footer(self):
        self.set_y(-16)
        self.set_font("helvetica", "I", 7.5)
        self.set_text_color(120, 120, 120)
        self.cell(0, 4, FOOTER, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.cell(0, 4, f"Page {self.page_no()}", align="C")
        self.set_text_color(0, 0, 0)

    def block(self, h, text, align="J"):
        self.multi_cell(0, h, text, align=align, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def title_block(self, title, subtitle):
        self.set_font("helvetica", "B", 15)
        self.block(7, title, align="C")
        self.set_font("helvetica", "", 10.5)
        self.block(5.5, subtitle, align="C")
        self.ln(4)

    def heading(self, text):
        self.ln(2)
        self.set_font("helvetica", "B", 11)
        self.block(6, text)
        self.ln(1)

    def para(self, text):
        self.set_font("helvetica", "", 10)
        self.block(5.2, text)
        self.ln(1.5)

    def table(self, headers, rows, widths):
        self.set_font("helvetica", "B", 9)
        for h, w in zip(headers, widths):
            self.cell(w, 6, h, border=1)
        self.ln()
        self.set_font("helvetica", "", 9)
        for row in rows:
            for v, w in zip(row, widths):
                self.cell(w, 6, str(v), border=1)
            self.ln()
        self.ln(2)


def build_msa(path):
    # ANSWER KEY -- planted findings, with the math a correct run shows.
    # Provider perspective (default; client = Meridian):
    #   §5.2 + Exh B: New Facility Discount expired Dec 2024, still applied
    #                 in 2025/2026 ................. 840000 * 0.05 = $42,000/yr
    #   §5.3 + Exh B: 3% annual escalation allowed, never invoiced
    #                 ............................. 840000 * 0.03 = $25,200/yr
    #                 ("may increase" is permissive, not automatic -- a model
    #                 that calls this discretionary and skips it has a point;
    #                 that's a good talking point, not a bug)
    #   §4.2 + Exh C: 23.0 emergency hours delivered Jan-Jul 2026, never
    #                 billed ......... 23 * 185 / 7 * 12 = ~$7,294/yr annualized
    # Customer perspective (--perspective customer; client = Bluegrass):
    #   §6.2 + Exh D: Q1/Q2 2026 availability below 99.5%, credits unclaimed
    #   §7.1 + Exh D: every quarter tops 1,200 service-hours; 8% volume
    #                 discount never applied
    #   §3.1: 90-day renewal-notice window approaching
    #   §11.2: 25% termination charge constrains renegotiation
    pdf = ContractPDF()
    pdf.add_page()
    pdf.title_block(
        "MASTER SERVICES AGREEMENT",
        'between Meridian Field Services LLC ("Provider") and '
        'Bluegrass Bottling Company ("Customer")\nEffective Date: January 1, 2024',
    )
    pdf.heading("1. Services")
    pdf.para(
        "Provider shall furnish industrial equipment maintenance, calibration, and "
        "field engineering services to Customer's bottling facilities as described "
        "in Exhibit A (Statement of Services), at the service levels set out in "
        "Section 6."
    )
    pdf.heading("2. Term")
    pdf.para(
        "2.1 The Initial Term of this Agreement begins on the Effective Date and "
        "continues through December 31, 2026."
    )
    pdf.heading("3. Renewal")
    pdf.para(
        "3.1 Following the Initial Term, this Agreement automatically renews for "
        "successive twelve (12) month Renewal Terms at the fee schedule then in "
        "effect under Section 5. Either party may decline renewal by delivering "
        "written notice at least ninety (90) days prior to the end of the "
        "then-current term."
    )
    pdf.heading("4. Emergency Services")
    pdf.para(
        "4.1 In addition to the Services described in Exhibit A, Provider shall "
        "respond to Customer requests for after-hours or emergency equipment "
        "service outside of standard business hours (Monday-Friday, 8:00am-6:00pm)."
    )
    pdf.para(
        "4.2 Emergency service calls are billed separately from the annual base "
        "fee at a rate of $185 per hour, in thirty (30) minute increments, and "
        "shall be invoiced as a separate line item on the invoice for the month "
        "following the service call."
    )
    pdf.heading("5. Fees")
    pdf.para(
        "5.1 Customer shall pay Provider an annual base fee of Eight Hundred "
        "Forty Thousand Dollars ($840,000), invoiced monthly in equal "
        "installments, subject to the adjustments in this Section 5."
    )
    pdf.para(
        "5.2 In recognition of Customer's status as a new facility as of the "
        "Effective Date, Provider shall apply a New Facility Discount of five "
        "percent (5%) to the fees invoiced during the first twelve (12) months "
        "of the Initial Term only, through December 31, 2024. Unless otherwise "
        "agreed in writing, invoicing after that date reverts to the full fee "
        "schedule in this Section 5, as adjusted under Section 5.3."
    )
    pdf.para(
        "5.3 Provider may increase the annual base fee once per contract year, "
        "effective on the anniversary of the Effective Date, by up to three "
        "percent (3%)."
    )
    pdf.heading("6. Service Levels")
    pdf.para(
        "6.1 Provider guarantees Covered Equipment monitoring platform availability "
        "of at least 99.5% per calendar quarter."
    )
    pdf.para(
        "6.2 If availability falls below 99.5% in any quarter, Customer is entitled "
        "to a service credit equal to five percent (5%) of the fees for each month "
        "of that quarter, upon written request within ninety (90) days of the end "
        "of the affected quarter."
    )
    pdf.heading("7. Volume Discount")
    pdf.para(
        "7.1 In any calendar quarter in which Customer purchases more than one "
        "thousand two hundred (1,200) service-hours, Provider shall apply a "
        "discount of eight percent (8%) to that quarter's invoices."
    )
    pdf.heading("11. Termination")
    pdf.para(
        "11.2 Customer may terminate this Agreement for convenience on sixty (60) "
        "days' written notice, subject to a termination charge equal to twenty-five "
        "percent (25%) of the fees remaining in the then-current term."
    )

    pdf.add_page()
    pdf.heading("EXHIBIT B - Rate and Invoice History (through July 2026)")
    pdf.para("Summary of annual base fees invoiced by Provider:")
    pdf.table(
        ["Contract Year", "Annual Fee Invoiced", "Change vs Prior Year"],
        [
            ["2024", "$798,000", "-"],
            ["2025", "$798,000", "0.0%"],
            ["2026", "$798,000", "0.0%"],
        ],
        [45, 60, 55],
    )
    pdf.para(
        "Note: the 2024 fee reflects the New Facility Discount (Section 5.2) "
        "correctly applied for that year only. Invoices for 2025 and 2026 "
        "continue to reflect the discounted rate, though the discount expired "
        "December 31, 2024. No annual escalation under Section 5.3 has been "
        "applied in any year since the Effective Date."
    )
    pdf.heading("EXHIBIT C - Emergency Service Call Log (2026)")
    pdf.table(
        ["Date", "Hours", "Reason"],
        [
            ["Jan 14, 2026", "3.0", "Chiller failure, night shift"],
            ["Feb 22, 2026", "2.5", "Line down, weekend call"],
            ["Mar 30, 2026", "4.0", "Compressor alarm"],
            ["Apr 18, 2026", "3.5", "Emergency calibration"],
            ["May 9, 2026", "2.0", "After-hours safety inspection"],
            ["Jun 25, 2026", "5.0", "Weekend outage response"],
            ["Jul 11, 2026", "3.0", "Holiday coverage call"],
        ],
        [40, 25, 95],
    )
    pdf.para(
        "23.0 emergency service hours were logged January-July 2026, averaging "
        "3.3 hours per month. None of these calls appear as a separate line "
        "item on any invoice in Exhibit B; only the flat monthly base fee was "
        "billed in each of those months."
    )
    pdf.heading("EXHIBIT D - Service and Availability Report (Q1 2025 - Q2 2026)")
    pdf.table(
        ["Quarter", "Service-Hours", "Discount Applied", "Platform Availability"],
        [
            ["Q1 2025", "1,310", "None", "99.7%"],
            ["Q2 2025", "1,345", "None", "99.6%"],
            ["Q3 2025", "1,420", "None", "99.5%"],
            ["Q4 2025", "1,390", "None", "99.6%"],
            ["Q1 2026", "1,455", "None", "98.9%"],
            ["Q2 2026", "1,505", "None", "99.1%"],
        ],
        [30, 40, 45, 55],
    )
    pdf.output(path)


def build_saas(path):
    # ANSWER KEY -- planted findings, with the math a correct run shows.
    # Provider perspective (default; client = Northgate):
    #   §5.2 + Exh A: Early Adopter Discount expired Dec 2024, invoices still
    #                 show $85.50 vs the $95.00 contract rate
    #                 ................. 250 * (95 - 85.50) * 12 = $28,500/yr
    #   §2.4 + Exh B: ~11 seats over the 250 commitment May-Jul 2026, overage
    #                 never billed ......... 110 * 11 * 12 = $14,520/yr
    # Customer perspective (--perspective customer; client = Bluegrass):
    #   §4.2 + Exh A: Premium Support billed $18,000/yr though the Enterprise
    #                 tier includes it (billing overlap)
    #   §5.3 + Exh B: Feb-Apr active seats ~180 vs 250 committed -- the
    #                 seat-reduction right at renewal is going unused
    #   §2.3: 60-day renewal-notice window
    pdf = ContractPDF()
    pdf.add_page()
    pdf.title_block(
        "SOFTWARE SUBSCRIPTION AGREEMENT",
        'between Northgate Analytics, Inc. ("Northgate") and '
        'Bluegrass Bottling Company ("Customer")\nSubscription Start: July 1, 2024',
    )
    pdf.heading("2. Subscription")
    pdf.para(
        "2.1 Northgate grants Customer a subscription to the Northgate Analytics "
        "Platform, Enterprise tier, for two hundred fifty (250) Committed Seats."
    )
    pdf.para(
        "2.3 The Initial Term runs from the Subscription Start through June 30, "
        "2027, renewing annually thereafter unless either party gives written "
        "notice of non-renewal at least sixty (60) days before the end of the "
        "then-current term."
    )
    pdf.para(
        "2.4 Active Seats in excess of the 250 Committed Seats in any calendar "
        "month are billed at One Hundred Ten Dollars ($110) per seat for that "
        "month, in addition to the Committed Seat fee, and shall appear as a "
        "separate line item on the following month's invoice."
    )
    pdf.heading("4. Support")
    pdf.para(
        "4.2 Premium Support (24x7 response, named technical account manager) is "
        "included in the Enterprise tier at no additional charge."
    )
    pdf.heading("5. Fees")
    pdf.para(
        "5.1 Subscription fees are Ninety-Five Dollars ($95) per Committed Seat "
        "per month, invoiced annually in advance ($285,000 per year)."
    )
    pdf.para(
        "5.2 Northgate applied an Early Adopter Discount of ten percent (10%) to "
        "fees invoiced during the first six (6) months of the Subscription Term "
        "only, through December 31, 2024. Invoicing thereafter reverts to the "
        "full per-seat rate in Section 5.1."
    )
    pdf.para(
        "5.3 Once per year at renewal, Customer may request a reduction of "
        "Committed Seats to no less than the trailing three-month average of "
        "Active Seats, upon written request."
    )

    pdf.add_page()
    pdf.heading("EXHIBIT A - Order Form and Invoice Summary (current)")
    pdf.table(
        ["Line Item", "Qty", "Unit Price", "Annual Total"],
        [
            ["Enterprise Subscription", "250 seats", "$85.50/seat/mo*", "$256,500"],
            ["Premium Support", "1", "$18,000/yr", "$18,000"],
            ["TOTAL INVOICED", "", "", "$274,500"],
        ],
        [70, 30, 35, 35],
    )
    pdf.para(
        "*The Early Adopter Discount (Section 5.2) continues to appear on "
        "invoices through July 2026, though it expired December 31, 2024. "
        "Invoices reflect $85.50/seat/mo (a 10% discount from the $95.00 "
        "contract rate in Section 5.1) rather than the full rate."
    )
    pdf.heading("EXHIBIT B - Platform Usage Report (Feb 2026 - Jul 2026)")
    pdf.table(
        ["Month", "Active Seats", "Committed Seats", "Overage Billed"],
        [
            ["February 2026", "181", "250", "N/A"],
            ["March 2026", "178", "250", "N/A"],
            ["April 2026", "186", "250", "N/A"],
            ["May 2026", "254", "250", "None"],
            ["June 2026", "261", "250", "None"],
            ["July 2026", "268", "250", "None"],
        ],
        [42, 35, 38, 40],
    )
    pdf.para(
        "Active Seats have exceeded the 250 Committed Seats for the last three "
        "consecutive months (May-July 2026), averaging approximately 11 seats "
        "over the commitment. No seat overage charges under Section 2.4 appear "
        "on any invoice in Exhibit A for these months."
    )
    pdf.output(path)


if __name__ == "__main__":
    import pathlib

    here = pathlib.Path(__file__).parent
    build_msa(str(here / "meridian-msa.pdf"))
    build_saas(str(here / "northgate-saas.pdf"))
    print("Wrote meridian-msa.pdf and northgate-saas.pdf")
