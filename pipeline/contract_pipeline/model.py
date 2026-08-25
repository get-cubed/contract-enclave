"""The one door to the model. Every request the pipeline makes goes through
chat(), which times the call, narrates progress to the terminal, and records
the full exchange for a per-contract audit log written beside the reports.

The audit log is part of the product story: the enclave proves document
content *can't* leave the network, and this file shows exactly what the
model was asked and answered -- the whole exchange, reviewable on local disk.
"""

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
         verbose=False, max_tokens=4096):
    """Send one chat request and return the stripped response text.

    purpose -- short label for the terminal line and the audit log entry
    audit   -- list that collects one dict per exchange (None to skip)
    verbose -- also print the raw model output to the terminal
    """
    sent, request_text = _describe(messages)
    log(f"    -> {purpose}  [{sent}]")
    start = time.monotonic()
    resp = client.chat.completions.create(
        model=model, messages=messages, temperature=0.0, max_tokens=max_tokens
    )
    elapsed = time.monotonic() - start
    text = (resp.choices[0].message.content or "").strip()
    usage = getattr(resp, "usage", None)
    in_tok = getattr(usage, "prompt_tokens", None)
    out_tok = getattr(usage, "completion_tokens", None)
    tokens = f", {in_tok:,} tokens in / {out_tok:,} out" if in_tok is not None else ""
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
        })
    return text


def render_audit_md(contract_name: str, audit: list[dict]) -> str:
    """The audit log as markdown: every exchange for one contract, in full."""
    total = sum(a["seconds"] for a in audit)
    lines = [
        f"# Model Audit Log: {contract_name}",
        "",
        f"{len(audit)} model calls, {total:.0f}s total, all to the in-network "
        "endpoint. This file is the complete record of what the model was "
        "sent and what it answered; no other AI traffic exists.",
        "",
    ]
    for i, a in enumerate(audit, 1):
        tokens = ""
        if a["prompt_tokens"] is not None:
            tokens = f" · {a['prompt_tokens']:,} tokens in / {a['completion_tokens']:,} out"
        # four-backtick fences so fenced blocks inside model output can't break out
        lines += [
            f"## {i}. {a['purpose']}",
            "",
            f"`{a['model']}` · {a['seconds']}s · sent {a['sent']}{tokens}",
            "",
            "**Request (text sent; images summarized):**",
            "````", a["request_text"], "````",
            "",
            "**Response:**",
            "````", a["response_text"], "````",
            "",
        ]
    return "\n".join(lines)
