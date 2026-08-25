"""Unit tests for the pipeline plumbing. Run:  cd pipeline && uv run -m pytest"""

import json
from pathlib import Path

import pytest

from contract_pipeline import analyze, mock, model, report
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
                     purpose="unit probe", audit=audit, log=lines.append)

    assert out == "hello back"                        # stripped
    assert sent["temperature"] == 0.0                 # determinism preserved
    assert audit[0]["purpose"] == "unit probe"
    assert audit[0]["request_text"] == "hi"
    assert audit[0]["prompt_tokens"] == 12
    assert any("-> unit probe" in l for l in lines)   # request narrated
    assert any("<- unit probe" in l for l in lines)   # completion narrated with timing

    md = model.render_audit_md("demo", audit)
    assert "hello back" in md and "test-model" in md and "unit probe" in md


def test_extract_json_handles_fences_and_prose():
    text = 'Sure, here you go:\n```json\n{"findings": [{"category": "x"}]}\n```\nDone.'
    assert analyze.extract_json(text) == {"findings": [{"category": "x"}]}


def test_extract_json_rejects_empty_response():
    # This is exactly what the thinking-variant model returned.
    with pytest.raises(ValueError):
        analyze.extract_json("")


def test_safe_eval_does_arithmetic():
    assert analyze.safe_eval("(250 - 178) * 95 * 12") == 82080
    assert analyze.safe_eval("$840,000 * 5%") == 42000
    assert analyze.safe_eval("-(10 - 4) * -2") == 12


@pytest.mark.parametrize("expr", ["__import__('os')", "a * 2", "2 ** 64", "(1).real", "[1,2]"])
def test_safe_eval_rejects_anything_but_arithmetic(expr):
    with pytest.raises((ValueError, SyntaxError)):
        analyze.safe_eval(expr)


def test_finalize_computes_value_and_discards_model_arithmetic():
    f = [{"annual_value_formula": "(250 - 178) * 95 * 12",
          "estimated_annual_value_usd": 117600,  # wrong number from the model
          "confidence": "high"}]
    out = analyze.finalize_findings(f)
    assert out[0]["estimated_annual_value_usd"] == 82080


def test_finalize_flags_bad_or_nonpositive_formulas():
    out = analyze.finalize_findings([
        {"annual_value_formula": "rm -rf /", "confidence": "high"},
        {"annual_value_formula": "178 - 250", "confidence": "high"},
        {"annual_value_formula": None, "confidence": "low"},
    ])
    assert all(f["estimated_annual_value_usd"] is None for f in out)
    assert "could not be evaluated" in out[0]["value_note"]
    assert "needs review" in out[1]["value_note"]
    assert "value_note" not in out[2]


def test_finalize_sorts_by_confidence_then_value():
    out = analyze.finalize_findings([
        {"annual_value_formula": "10", "confidence": "low"},
        {"annual_value_formula": "5", "confidence": "high"},
        {"annual_value_formula": "50", "confidence": "high"},
    ])
    assert [f["estimated_annual_value_usd"] for f in out] == [50, 5, 10]


def test_total_value_ignores_nulls():
    findings = [{"estimated_annual_value_usd": 100}, {"estimated_annual_value_usd": None}, {}]
    assert report.total_value(findings) == 100


def test_markdown_report_shows_the_math():
    import copy
    findings = analyze.finalize_findings(copy.deepcopy(mock.MOCK_FINDINGS))
    md = report.render_markdown("demo", findings)
    for f in findings:
        assert f["clause"] in md
        assert f["annual_value_formula"] in md
    assert "$42,000" in md          # 840000 * 0.05, expired discount
    assert "$25,200" in md          # 840000 * 0.03, unbilled escalation
    assert "$67,200" in md          # total


def test_html_report_escapes_content():
    html = report.render_html("demo", [{"issue": "<script>alert(1)</script>", "quote": "", "category": "x"}])
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_cli_mock_end_to_end(tmp_path: Path):
    pdf = tmp_path / "some-contract.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")  # mock mode never opens it
    out = tmp_path / "out"
    assert main(["analyze", str(pdf), "--mock", "--out", str(out)]) == 0
    for suffix in ("transcript.md", "findings.json", "report.md", "report.html"):
        assert (out / f"some-contract.{suffix}").exists()
    findings = json.loads((out / "some-contract.findings.json").read_text())
    assert len(findings) == len(mock.MOCK_FINDINGS)
    assert "some-contract" in (out / "summary.md").read_text()


def test_cli_mock_customer_perspective(tmp_path: Path):
    pdf = tmp_path / "some-contract.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    out = tmp_path / "out"
    assert main(["analyze", str(pdf), "--mock", "--perspective", "customer", "--out", str(out)]) == 0
    findings = json.loads((out / "some-contract.findings.json").read_text())
    assert len(findings) == len(mock.MOCK_FINDINGS_CUSTOMER)
    assert {f["category"] for f in findings} == {"auto_renewal", "price_escalation"}


def test_provider_and_customer_prompts_differ():
    provider = analyze.build_prompt("provider", "CONTRACT TEXT")
    customer = analyze.build_prompt("customer", "CONTRACT TEXT")
    assert "unbilled_escalation" in provider
    assert "unbilled_escalation" not in customer
    assert "auto_renewal" in customer
    assert "CONTRACT TEXT" in provider and "CONTRACT TEXT" in customer
