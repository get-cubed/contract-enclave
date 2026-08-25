"""The one door to the model. Every request the pipeline makes goes through
chat(), which times the call, narrates progress to the terminal, and records
the full exchange for a per-contract audit log written beside the reports.

The call ledger is part of the product story: in the verified demo enclave,
document traffic is confined to the configured model route, and this file
shows the full text sent and returned, reviewable on local disk.
"""

import html
import re
import time


def _describe(messages):
    """(size note, request text) for a request's messages.

    The note is what the terminal shows ("1,214 chars + 1 page image (312 KB)");
    the request text is what the audit log stores -- all text parts verbatim,
    with attached images summarized rather than dumped as base64.
    """
    chars, parts = 0, []
    images, image_kb = 0, 0
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            chars += len(content)
            parts.append(content)
            continue
        for part in content:
            if part.get("type") == "text":
                chars += len(part["text"])
                parts.append(part["text"])
            elif part.get("type") == "image_url":
                images += 1
                kb = int(len(part["image_url"]["url"]) * 3 / 4 / 1024)  # data: URI -> raw KB
                image_kb += kb
                parts.append(f"[attached page image, PNG, {kb:,} KB]")
    note = f"{chars:,} chars"
    if images:
        note += f" + {images} page image ({image_kb:,} KB)"
    return note, "\n\n".join(parts)


def chat(client, model, messages, *, purpose, audit=None, log=print,
         verbose=False, max_tokens=4096, response_format=None):
    """Send one chat request and return the stripped response text.

    purpose -- short label for the terminal line and the audit log entry
    audit   -- list that collects one dict per exchange (None to skip)
    verbose -- also print the raw model output to the terminal
    """
    sent, request_text = _describe(messages)
    log(f"    -> {purpose}  [{sent}]")
    start = time.monotonic()
    request = {
        "model": model,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": max_tokens,
    }
    if response_format is not None:
        request["response_format"] = response_format
    try:
        resp = client.chat.completions.create(**request)
    except Exception as exc:
        elapsed = time.monotonic() - start
        log(f"    !! {purpose}  failed after {elapsed:.1f}s ({type(exc).__name__})")
        if audit is not None:
            audit.append({
                "purpose": purpose,
                "model": model,
                "seconds": round(elapsed, 1),
                "sent": sent,
                "prompt_tokens": None,
                "completion_tokens": None,
                "request_text": request_text,
                "response_text": "",
                "error": f"{type(exc).__name__}: {exc}",
            })
        raise

    elapsed = time.monotonic() - start
    text = (resp.choices[0].message.content or "").strip()
    usage = getattr(resp, "usage", None)
    in_tok = getattr(usage, "prompt_tokens", None)
    out_tok = getattr(usage, "completion_tokens", None)
    tokens = (
        f", {in_tok:,} tokens in / {out_tok:,} out"
        if in_tok is not None and out_tok is not None else ""
    )
    log(f"    <- {purpose}  {elapsed:.1f}s{tokens}, {len(text):,} chars back")
    if verbose:
        log("    ┌─ raw model output " + "─" * 41)
        for line in text.splitlines() or ["(empty response)"]:
            log("    │ " + line)
        log("    └" + "─" * 60)
    if audit is not None:
        audit.append({
            "purpose": purpose,
            "model": model,
            "seconds": round(elapsed, 1),
            "sent": sent,
            "prompt_tokens": in_tok,
            "completion_tokens": out_tok,
            "request_text": request_text,
            "response_text": text,
            "error": None,
        })
    return text


def _safe_markdown_text(value) -> str:
    """Neutralize raw HTML while preserving readable Markdown text."""
    return " ".join(html.escape(str(value), quote=False).splitlines())


def _fenced(value) -> list[str]:
    """Fence arbitrary model text without assuming it uses <=3 backticks."""
    text = str(value)
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(4, longest + 1)
    return [fence, text, fence]


def render_audit_md(contract_name: str, audit: list[dict]) -> str:
    """Render a call ledger with full text prompts/responses and image metadata."""
    total = sum(a["seconds"] for a in audit)
    lines = [
        f"# Model Audit Log: {_safe_markdown_text(contract_name)}",
        "",
        f"{len(audit)} model calls, {total:.0f}s total, all to the model "
        "endpoint configured for this run. This ledger preserves every full "
        "text prompt and response (including failures). Page images are "
        "identified by size rather than duplicated as base64; the source PDF "
        "remains the image record.",
        "",
    ]
    for i, a in enumerate(audit, 1):
        tokens = ""
        if a["prompt_tokens"] is not None and a["completion_tokens"] is not None:
            tokens = f" · {a['prompt_tokens']:,} tokens in / {a['completion_tokens']:,} out"
        purpose = _safe_markdown_text(a["purpose"])
        model = _safe_markdown_text(a["model"])
        lines += [
            f"## {i}. {purpose}",
            "",
            f"Model: {model} · {a['seconds']}s · sent {_safe_markdown_text(a['sent'])}{tokens}",
            "",
            "**Request (text sent; images summarized):**",
        ]
        lines += _fenced(a["request_text"])
        lines.append("")
        if a.get("error"):
            lines += ["**Error:**"] + _fenced(a["error"]) + [""]
        else:
            lines += ["**Response:**"] + _fenced(a["response_text"]) + [""]
    return "\n".join(lines)
