# Running the demo locally

## Prereqs

Docker, plus three CLIs: `ollama`, `coder`, and `uv`.

- **macOS** — Docker Desktop, then:
  ```bash
  brew install ollama coder/coder/coder uv
  ```
- **Linux** — [Docker Engine](https://docs.docker.com/engine/install/), then:
  ```bash
  curl -fsSL https://ollama.com/install.sh | sh
  curl -fsSL https://coder.com/install.sh | sh
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
  Ollama's installer registers a systemd service that listens on localhost
  only; `dev-up.sh` detects that and prints the two-line override to make it
  reachable from the enclave gateways.
- **Windows** — use WSL2: install Docker Desktop with WSL integration
  enabled, open the WSL (Ubuntu) shell, and follow the Linux steps there —
  the same `dev-up.sh` runs unchanged. NVIDIA GPUs are available to Ollama
  inside WSL2 automatically.

A GPU makes OCR quick (Apple Silicon, NVIDIA, or AMD — Ollama picks up
whichever is there); CPU-only works but is slow. `--mock` (below) needs no
model at all.

## Bring everything up

```bash
scripts/dev-up.sh
```

First run only: open http://localhost:3000, create an account, then run
`coder login http://localhost:3000` and re-run the command above — it
creates the internal `enclave` network, the two single-port relays
(`coder:3000`, `model:11434` → services running natively on the host, which
is where the laptop's GPU is), and pushes the workspace template.

```bash
coder create demo --template contract-workspace -y
scripts/verify-enclave.sh demo        # the proof: egress fails, pipeline works
```

## Run the pipeline

Inside the workspace terminal (code-server, or `coder ssh demo`):

```bash
cd ~/contract-enclave/pipeline
uv run -m contract_pipeline.cli analyze ../sample-contracts/*.pdf --out ../reports
```

Every model exchange is narrated live with sizes, timing, and token counts,
and findings print as they're computed (this is real output):

```
[meridian-msa]
    -> OCR page 1/3  [225 chars + 1 page image (402 KB)]
    <- OCR page 1/3  20.7s, 2,667 tokens in / 598 out, 2,584 chars back
    ...
    -> find lost value (provider perspective)  [8,651 chars]
    <- find lost value (provider perspective)  14.1s, 2,192 tokens in / 763 out, 2,878 chars back
    1. [expired_discount_continued] Section 5.2 — $42,000/yr (high confidence)
    2. [unbilled_services] Section 4.2 — $7,294/yr (high confidence)
    => 2 findings, est. $49,294/yr at stake
```

Reports land in `reports/` — `summary.md` plus per-contract `*.report.html`,
served by the workspace's **Reports** app button. Each real run also writes
`<name>.model-log.md` there: the complete audit of every model exchange —
full prompts and responses, timings, token counts — kept on local disk,
because in this product the model's traffic is *supposed* to be inspectable.

## Options worth knowing about

- **`--perspective customer`** — the default (`provider`) looks for revenue
  a vendor has stopped collecting on its own contracts (missed escalations,
  unbilled overage, expired discounts still applied). `customer` flips it to
  the buyer's side of the same contracts: overpayments, unclaimed credits.
- **`--mock`** — skips the model, returns canned output instantly. Good for
  iterating on report formatting without waiting on inference.
- **`--verbose`** — additionally streams each raw model response into the
  terminal as it lands. The same content is always in `<name>.model-log.md`,
  so this is for watching, not for record-keeping.
- **A real contract** — drop any PDF under `~/contract-enclave` and point the
  command at it instead of the sample contracts.

## How dollar figures are computed

The model is asked for a formula built from numbers in the contract (e.g.
`840000 * 0.03` for a missed 3% escalation), not a total. The pipeline
evaluates that formula with a restricted arithmetic evaluator (no code
execution possible) and prints the math next to every value in the report.
Findings the contract can't quantify get `n/a` rather than an invented
number. Model-supplied totals are always discarded.

The pipeline talks to one OpenAI-compatible endpoint (`MODEL_BASE_URL`):
Ollama serving `qwen3-vl:8b-instruct` locally; any other OpenAI-compatible
server (vLLM on a GPU box, say) works unchanged. (Careful if you experiment
with Ollama tags: the bare `qwen3-vl:8b` tag is the *thinking* variant,
which burns its token budget reasoning and returns empty content.)

## Tests

```bash
cd pipeline && uv run -m pytest          # pipeline unit tests (no model needed)
scripts/verify-enclave.sh demo           # live enclave checks against a workspace
```

`verify-enclave.sh` asserts: the network is internal; the workspace is on
that network only; five egress targets and public DNS all fail from inside;
the model endpoint and Coder route work; the pipeline runs with
`UV_OFFLINE=1`; and the image's pinned lockfile matches the pipeline's.
Non-zero exit on any failure, so it can gate a demo or a CI run.
