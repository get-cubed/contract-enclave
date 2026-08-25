"""Unit tests for the pipeline plumbing. Run:  cd pipeline && uv run -m pytest"""

import json
from pathlib import Path

import pytest

from contract_pipeline import analyze, mock, model, ocr, report
from contract_pipeline.cli import main


def test_chat_narrates_and_records_the_exchange():
    from types import SimpleNamespace as NS

    sent = {}

    class _Completions:
        def create(self, **kw):
            sent.update(kw)
            return NS(choices=[NS(message=NS(content="  hello back  "))],
                      usage=NS(prompt_tokens=12, completion_tokens=3))

    fake_client = NS(chat=NS(completions=_Completions()))
    audit, lines = [], []
    out = model.chat(fake_client, "test-model", [{"role": "user", "content": "hi"}],
                     purpose="unit probe", audit=audit, log=lines.append,
                     response_format={"type": "json_object"})

    assert out == "hello back"                        # stripped
    assert sent["temperature"] == 0.0                 # determinism preserved
    assert sent["response_format"] == {"type": "json_object"}
    assert audit[0]["purpose"] == "unit probe"
    assert audit[0]["request_text"] == "hi"
    assert audit[0]["prompt_tokens"] == 12
    assert any("-> unit probe" in l for l in lines)   # request narrated
    assert any("<- unit probe" in l for l in lines)   # completion narrated with timing

    md = model.render_audit_md("demo", audit)
    assert "hello back" in md and "test-model" in md and "unit probe" in md


def test_chat_records_failed_exchange_before_reraising():
    from types import SimpleNamespace as NS

    class _Completions:
        def create(self, **kw):
            raise TimeoutError("model timed out")

    audit = []
    with pytest.raises(TimeoutError):
        model.chat(NS(chat=NS(completions=_Completions())), "test-model",
                   [{"role": "user", "content": "hi"}], purpose="failure",
                   audit=audit, log=lambda _: None)
    assert audit[0]["error"] == "TimeoutError: model timed out"


def test_audit_fence_cannot_be_closed_by_model_output():
    audit = [{
        "purpose": "probe", "model": "model", "seconds": 0.1,
        "sent": "1 char", "prompt_tokens": 1, "completion_tokens": 1,
        "request_text": "x", "response_text": "````\n<script>x</script>",
        "error": None,
    }]
    md = model.render_audit_md("demo", audit)
    assert "`````\n````\n<script>x</script>\n`````" in md


def test_extract_json_handles_fences_and_prose():
    text = 'Sure, here you go:\n```json\n{"findings": [{"category": "x"}]}\n```\nDone.'
    assert analyze.extract_json(text) == {"findings": [{"category": "x"}]}


def test_extract_json_rejects_empty_response():
    # This is exactly what the thinking-variant model returned.
    with pytest.raises(ValueError):
        analyze.extract_json("")


def test_sample_pdf_renders_every_page_as_png():
    pdf = Path(__file__).parents[2] / "sample-contracts" / "meridian-msa.pdf"
    pages = list(ocr.render_pages(str(pdf), dpi=72))
    assert len(pages) == ocr.page_count(str(pdf)) == 3
    assert [number for number, _ in pages] == [1, 2, 3]
    assert all(png.startswith(b"\x89PNG\r\n\x1a\n") for _, png in pages)


def test_safe_eval_does_arithmetic():
    assert analyze.safe_eval("(250 - 178) * 95 * 12") == 82080
    assert analyze.safe_eval("$840,000 * 5%") == 42000
    assert analyze.safe_eval("-(10 - 4) * -2") == 12


@pytest.mark.parametrize(
    "expr",
    ["__import__('os')", "a * 2", "2 ** 64", "(1).real", "[1,2]", "1e309"],
)
def test_safe_eval_rejects_anything_but_arithmetic(expr):
    with pytest.raises((ValueError, SyntaxError)):
        analyze.safe_eval(expr)


def test_finalize_computes_value_and_discards_model_arithmetic():
    f = [{"monthly_value_formula": "(250 - 178) * 95",
          "estimated_annual_value_usd": 117600,  # wrong number from the model
          "confidence": "high"}]
    out = analyze.finalize_findings(f, "250 seats, 178 used, at $95 per month")
    assert out[0]["estimated_annual_value_usd"] == 82080
    assert out[0]["annual_value_formula"] == "((250 - 178) * 95) * 12"


def test_finalize_rejects_formula_numbers_not_in_contract():
    out = analyze.finalize_findings([
        {"monthly_value_formula": "840000 * 7 / 100 / 12",
         "confidence": "high"},
    ], "Annual fee $840,000; discount 5%.")
    assert out[0]["estimated_annual_value_usd"] is None
    assert "could not be evaluated" in out[0]["value_note"]


def test_finalize_rejects_gross_fee_as_expired_discount_value():
    out = analyze.finalize_findings([{
        "category": "expired_discount_continued",
        "quote": "A ten percent (10%) discount expired.",
        "issue": "Invoices show $85.50 instead of the full $95.00 rate.",
        "monthly_value_formula": "250 * 95",
        "confidence": "high",
    }], "250 seats; $95.00 full rate; $85.50 invoice; 10% discount.")
    assert out[0]["estimated_annual_value_usd"] is None
    assert "expired-discount formula" in out[0]["value_note"]


def test_finalize_allows_month_count_written_as_a_word():
    out = analyze.finalize_findings([
        {"monthly_value_formula": "(110 * 4 + 110 * 11 + 110 * 18) / 3",
         "confidence": "high"},
    ], "Rate $110; overages were 4, 11, and 18 seats for the last three months.")
    assert out[0]["estimated_annual_value_usd"] == 14520
    assert out[0]["annual_value_formula"] == "((110 * 4 + 110 * 11 + 110 * 18) / 3) * 12"


def test_explicit_average_formula_uses_transcript_average_and_single_rate():
    finding = {
        "category": "unbilled_services",
        "quote": "Overages are billed at $110 per seat for that month.",
        "issue": "Active seats exceeded the commitment for three months.",
    }
    formula, notes, action = analyze._explicit_average_formula(
        finding, "Usage was averaging approximately 11 seats over the commitment."
    )
    assert formula == "11 * 110"
    assert "explicit transcript average" in notes
    assert "actual quantity" in action

    hours = {
        "category": "unbilled_services",
        "quote": "Emergency work is billed at $185 per hour.",
        "issue": "Emergency hours were not billed.",
    }
    formula, _, _ = analyze._explicit_average_formula(
        hours, "The log was averaging 23 / 7 hours per month."
    )
    assert formula == "23 / 7 * 185"


def test_formula_cadence_normalizes_annual_but_not_monthly_rates():
    formula, changed = analyze._normalize_formula_cadence(
        "840000 * 5 / 100",
        "Customer pays an annual base fee of $840,000; discount is 5%.",
    )
    assert changed is True
    assert formula == "(840000 * 5 / 100) / 12"

    formula, changed = analyze._normalize_formula_cadence(
        "250 * 95 * 10 / 100",
        "The rate is $95 per Committed Seat per month for 250 seats, less 10%.",
    )
    assert changed is False
    assert formula == "250 * 95 * 10 / 100"

    formula, changed = analyze._normalize_formula_cadence(
        "23 / 7 * 185",
        "Calls are separate from the annual base fee at $185 per hour; "
        "23 hours were logged over seven months.",
    )
    assert changed is False
    assert formula == "23 / 7 * 185"


def test_finalize_discards_superseded_period_schema():
    out = analyze.finalize_findings([
        {"value_formula": "1000", "value_period_months": 1,
         "estimated_annual_value_usd": 12000, "confidence": "high"},
    ], "Value $1,000 per month.")
    assert out[0]["estimated_annual_value_usd"] is None
    assert "value_formula" not in out[0] and "value_period_months" not in out[0]


def test_finalize_filters_findings_for_the_selected_beneficiary():
    findings = [
        {"beneficiary_role": "provider", "quote": "Provider value is 10.",
         "monthly_value_formula": "10", "confidence": "high"},
        {"beneficiary_role": "customer", "quote": "Customer value is 20.",
         "monthly_value_formula": "20", "confidence": "high"},
    ]
    provider = analyze.finalize_findings(
        findings, "Provider value is 10. Customer value is 20.", perspective="provider"
    )
    assert len(provider) == 1
    assert provider[0]["beneficiary_role"] == "provider"
    assert provider[0]["estimated_annual_value_usd"] == 120


def test_provider_scope_rejects_explicit_customer_credit_despite_model_label():
    finding = {
        "category": "missed_true_up",
        "beneficiary_role": "provider",  # model classified the direction incorrectly
        "quote": "Customer is entitled to a service credit equal to five percent.",
        "issue": "No credit was issued.",
        "action": "Issue a true-up for the credit.",
        "monthly_value_formula": "100",
        "confidence": "high",
    }
    assert analyze.finalize_findings(
        [finding], "Customer is entitled to a service credit equal to five percent. 100",
        perspective="provider",
    ) == []


def test_finalize_flags_quote_not_found_in_transcript():
    out = analyze.finalize_findings([
        {"quote": "language the contract does not contain", "confidence": "high"},
    ], "Actual contract language.")
    assert "not found verbatim" in out[0]["evidence_note"]


def test_selected_perspective_does_not_quantify_an_unsupported_quote():
    out = analyze.finalize_findings([{
        "beneficiary_role": "provider",
        "quote": "Invented supporting language.",
        "monthly_value_formula": "10",
        "confidence": "high",
    }], "Actual contract value is 10.", perspective="provider")
    assert out[0]["estimated_annual_value_usd"] is None
    assert out[0]["monthly_value_formula"] is None
    assert "quote failed validation" in out[0]["value_note"]


def test_finalize_flags_bad_or_nonpositive_formulas():
    out = analyze.finalize_findings([
        {"monthly_value_formula": "rm -rf /", "confidence": "high"},
        {"monthly_value_formula": "178 - 250", "confidence": "high"},
        {"monthly_value_formula": None, "confidence": "low"},
    ], "178 250")
    assert all(f["estimated_annual_value_usd"] is None for f in out)
    assert "could not be evaluated" in out[0]["value_note"]
    assert "non-positive monthly value" in out[1]["value_note"]
    assert "value_note" not in out[2]


def test_finalize_sorts_by_confidence_then_value():
    out = analyze.finalize_findings([
        {"monthly_value_formula": "10", "confidence": "low"},
        {"monthly_value_formula": "5", "confidence": "high"},
        {"monthly_value_formula": "50", "confidence": "high"},
    ], "10 5 50")
    assert [f["estimated_annual_value_usd"] for f in out] == [600, 60, 120]


def test_total_value_ignores_nulls():
    findings = [{"estimated_annual_value_usd": 100}, {"estimated_annual_value_usd": None}, {}]
    assert report.total_value(findings) == 100
    assert report.fmt_total(findings) == "$100 quantified"
    assert report.fmt_total([{"estimated_annual_value_usd": None}]) == "n/a"


def test_markdown_report_shows_the_math():
    import copy
    findings = analyze.finalize_findings(copy.deepcopy(mock.MOCK_FINDINGS), mock.MOCK_TRANSCRIPT)
    md = report.render_markdown("demo", findings)
    for f in findings:
        assert f["clause"] in md
        assert f["annual_value_formula"] in md
    assert "$42,000" in md          # 840000 * 5 / 100, expired discount
    assert "$25,200" in md          # 840000 * 3 / 100, unbilled escalation
    assert "$67,200" in md          # total


def test_html_report_escapes_content():
    html = report.render_html("demo", [{"issue": "<script>alert(1)</script>", "quote": "", "category": "x"}])
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_markdown_report_neutralizes_raw_html():
    md = report.render_markdown("demo", [{
        "issue": "<script>alert(1)</script>", "quote": "ok", "category": "x",
    }])
    assert "<script>" not in md
    assert "&lt;script&gt;" in md


def test_markdown_report_neutralizes_links_images_and_table_breakout():
    attack = "[click](https://example.com) ![pixel](https://example.com/p) | extra"
    md = report.render_markdown("demo | injected", [{
        "issue": attack, "quote": "> fake quote", "category": "# heading",
    }])
    summary = report.render_summary([("demo | injected", [])])
    assert "[click](https://example.com)" not in md
    assert "![pixel](https://example.com/p)" not in md
    assert r"\[click\]\(https://example.com\)" in md
    assert r"\!\[pixel\]\(https://example.com/p\)" in md
    assert r"demo \| injected" in md
    assert r"demo \| injected" in summary


def test_cli_mock_end_to_end(tmp_path: Path):
    pdf = tmp_path / "some-contract.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")  # mock mode never opens it
    out = tmp_path / "out"
    assert main(["analyze", str(pdf), "--mock", "--out", str(out)]) == 0
    for suffix in ("transcript.md", "findings.json", "report.md", "report.html"):
        assert (out / f"some-contract.{suffix}").exists()
    findings = json.loads((out / "some-contract.findings.json").read_text(encoding="utf-8"))
    assert len(findings) == len(mock.MOCK_FINDINGS)
    assert "some-contract" in (out / "summary.md").read_text(encoding="utf-8")


def test_cli_rejects_unvalidated_customer_perspective(tmp_path: Path):
    pdf = tmp_path / "some-contract.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    with pytest.raises(SystemExit) as exc:
        main(["analyze", str(pdf), "--mock", "--perspective", "customer"])
    assert exc.value.code == 2


def test_prompt_is_provider_scoped_and_rejects_other_perspectives():
    provider = analyze.build_prompt("provider", "CONTRACT TEXT")
    assert "unbilled_escalation" in provider
    assert "CONTRACT TEXT" in provider
    assert "untrusted contract text" in provider
    assert "Do not calculate dollar values" in provider
    assert "entire relevant trend" in provider
    assert "monthly_value_formula" not in provider
    assert "at most five" in provider
    assert '"beneficiary_role": "provider"' in provider
    with pytest.raises(ValueError, match="unknown perspective"):
        analyze.build_prompt("customer", "CONTRACT TEXT")


def test_findings_response_format_is_strict_and_bounded():
    response_format = analyze._FINDINGS_RESPONSE_FORMAT
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    findings = response_format["json_schema"]["schema"]["properties"]["findings"]
    assert findings["maxItems"] == 5
    assert findings["items"]["additionalProperties"] is False
    assert "monthly_value_formula" not in findings["items"]["properties"]
    assert findings["items"]["properties"]["beneficiary_role"]["enum"] == ["provider"]
    assert not ({"auto_renewal", "unclaimed_credits"} & set(analyze._CATEGORIES))
    calculation = analyze._CALCULATION_RESPONSE_FORMAT
    assert calculation["type"] == "json_schema"
    calc_schema = calculation["json_schema"]["schema"]
    assert calc_schema["additionalProperties"] is False
    assert set(calc_schema["required"]) == {
        "monthly_value_formula", "formula_notes", "action"
    }


def test_analyze_uses_separate_discovery_and_calculation_passes():
    from types import SimpleNamespace as NS

    responses = [
        {
            "findings": [{
                "category": "unbilled_services",
                "beneficiary_role": "provider",
                "clause": "Section 1",
                "quote": "Rate is $10 per month.",
                "issue": "The monthly rate was not billed.",
                "action": "Invoice the missing monthly rate.",
                "confidence": "high",
            }],
        },
        {
            "monthly_value_formula": "10",
            "formula_notes": "$10 is already a monthly rate.",
            "action": "Invoice each affected month.",
        },
    ]
    requests = []

    class _Completions:
        def create(self, **kw):
            requests.append(kw)
            return NS(
                choices=[NS(message=NS(content=json.dumps(responses.pop(0))))],
                usage=NS(prompt_tokens=10, completion_tokens=10),
            )

    client = NS(chat=NS(completions=_Completions()))
    findings = analyze.analyze(
        client, "model", "Rate is $10 per month.", log=lambda _: None,
    )
    assert len(requests) == 2
    assert requests[0]["response_format"] == analyze._FINDINGS_RESPONSE_FORMAT
    assert requests[1]["response_format"] == analyze._CALCULATION_RESPONSE_FORMAT
    assert findings[0]["monthly_value_formula"] == "10"
    assert findings[0]["estimated_annual_value_usd"] == 120
    assert findings[0]["action"] == "Invoice each affected month."


def test_analyze_retries_once_when_formula_fails_provenance():
    from types import SimpleNamespace as NS

    responses = [
        {"findings": [{
            "category": "unbilled_services", "beneficiary_role": "provider",
            "clause": "Section 1", "quote": "Rate is $10 per month.",
            "issue": "The monthly rate was not billed.",
            "action": "Invoice it.", "confidence": "high",
        }]},
        {"monthly_value_formula": "99", "formula_notes": "invented", "action": "Invoice it."},
        {"monthly_value_formula": "10", "formula_notes": "supported", "action": "Invoice it."},
    ]
    requests = []

    class _Completions:
        def create(self, **kw):
            requests.append(kw)
            return NS(
                choices=[NS(message=NS(content=json.dumps(responses.pop(0))))],
                usage=NS(prompt_tokens=10, completion_tokens=10),
            )

    client = NS(chat=NS(completions=_Completions()))
    findings = analyze.analyze(
        client, "model", "Rate is $10 per month.", log=lambda _: None,
    )
    assert len(requests) == 3
    assert "failed deterministic validation" in requests[2]["messages"][0]["content"]
    assert findings[0]["estimated_annual_value_usd"] == 120
