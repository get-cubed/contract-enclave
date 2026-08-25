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
  reachable from the enclave gateways. On native Linux, that override and the
  local Coder process listen on all host interfaces; restrict ports 11434 and
  3000 with the host firewall and run the demo only on a trusted network.
- **Windows** — use WSL2: install Docker Desktop with WSL integration
  enabled, open the WSL (Ubuntu) shell, and follow the Linux steps there —
  the same `dev-up.sh` runs there. It binds the WSL-side Ollama and Coder
  services so the Docker Desktop gateways can reach them, then proves the
  route with smoke checks; keep ports 11434 and 3000 restricted in the Windows
  firewall. Enterprise WSL/firewall policies can block localhost forwarding,
  in which case setup stops instead of claiming success. GPU acceleration is not automatic:
  install a current supported Windows GPU driver, update WSL, and confirm the
  GPU is visible inside WSL (for NVIDIA, `nvidia-smi`) before relying on it.
  CPU fallback still works. Docker Desktop's license terms may require a paid
  subscription for commercial use at larger organizations; see Docker's
  [Windows install and licensing note](https://docs.docker.com/desktop/setup/install/windows-install/).

A supported GPU makes OCR quick. Ollama supports Apple Metal and documented
NVIDIA/AMD configurations, but Linux/Windows driver support varies by device;
check the [Ollama hardware support matrix](https://docs.ollama.com/gpu) and
verify with `ollama ps` during a run. CPU-only works but is slow. `--mock`
(below) needs no model at all.

## Bring everything up

```bash
scripts/dev-up.sh
```

First run only: open http://localhost:3000, create an account, then run
`coder login http://localhost:3000` and re-run the command above — it
creates the internal `enclave` network, the two single-port relays
(`coder:3000`, `model:11434` → services running natively on the host, which
is where the laptop's GPU is), and pushes the workspace template. The model
relay permits only `GET /v1/models` and `POST /v1/chat/completions`; Ollama's
pull/push/create management API is deliberately blocked. A brand-new local
Coder server may also download its built-in PostgreSQL binaries during this
online setup step.

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
and findings print as they're computed (sample output from a real run):

```
[meridian-msa]
    -> OCR page 1/3  [225 chars + 1 page image (402 KB)]
    <- OCR page 1/3  20.7s, 2,667 tokens in / 598 out, 2,584 chars back
    ...
    -> find lost value (provider perspective)  [8,651 chars]
    <- find lost value (provider perspective)  14.1s, 2,192 tokens in / 763 out, 2,878 chars back
    -> normalize monthly value formula (2/2)  [8,885 chars]
    <- normalize monthly value formula (2/2)  2.9s, 2,513 tokens in / 127 out, 402 chars back
    1. [expired_discount_continued] Section 5.2 — $42,000/yr (high confidence)
    2. [unbilled_services] Section 4.2 — $7,294/yr (high confidence)
    => 2 findings, est. $49,294/yr at stake
```

Reports land in `reports/` — `summary.md` plus per-contract `*.report.html`,
served by the workspace's **Reports** app button. Each real run also writes
`<name>.model-log.md` there: a ledger of every successful or failed model call,
with full text prompts/responses, timings, and token counts. Page images are
identified by size instead of duplicated as base64; the source PDF remains the
image record. These logs contain contract text and must receive the same access,
retention, and deletion controls as the source contracts.

## Options worth knowing about

- **`--mock`** — skips the model, returns canned output instantly. Good for
  iterating on report formatting without waiting on inference.
- **`--verbose`** — additionally streams each raw model response into the
  terminal as it lands. The same content is always in `<name>.model-log.md`,
  so this is for watching, not for record-keeping.
- **A real contract** — drop any PDF under `~/contract-enclave` and point the
  command at it instead of the sample contracts.

## How dollar figures are computed

One model pass discovers clauses and evidence without doing math. A separate,
strictly structured pass proposes a one-month formula built from contract
numbers (e.g. `840000 * 3 / 100 / 12` for the monthly value of a missed 3%
annual escalation), not a dollar total. The pipeline rejects formula numbers
absent from the transcript and findings whose action would benefit the
customer rather than the provider. For unambiguous evidence it derives an
explicit average times a single quoted rate,
or inserts the missing `/ 12` when every monetary input is annual. It then
evaluates only numeric literals and `+ - * /` in a bounded AST and multiplies
the monthly value by twelve in code. The supporting quote must also match the
transcript; if it does not, the candidate stays visible but cannot contribute a
dollar value. Findings the contract cannot quantify get `n/a` rather than an
invented number; partially quantified portfolios are labeled as such.
Model-supplied totals are always discarded. All findings remain candidates for
human review, not legal or accounting advice.

The pipeline talks to one OpenAI-compatible endpoint (`MODEL_BASE_URL`):
Ollama serving `qwen3-vl:8b-instruct` locally. A replacement endpoint must
support chat completions, vision inputs, JSON mode, and strict JSON-schema
`response_format`; verify those capabilities rather than assuming every
partially compatible server is interchangeable. (Careful if you experiment
with Ollama tags: the bare `qwen3-vl:8b` tag is the *thinking* variant,
which burns its token budget reasoning and returns empty content.)

## Tests

```bash
cd pipeline && uv run -m pytest          # pipeline unit tests (no model needed)
scripts/verify-enclave.sh demo           # live enclave checks against a workspace
```

`verify-enclave.sh` asserts: the network is internal; the workspace is on
that network only with all Linux capabilities dropped and no-new-privileges;
both gateways are read-only, capability-free, and no-new-privileges; no
unexpected peers or default route exist; five egress targets and public DNS all
fail from inside; the model endpoint and Coder route work while Ollama
management is blocked; the pipeline runs with `UV_OFFLINE=1`; and the image's
pinned lockfile matches the pipeline's. Non-zero exit on any failure, so it can
gate a demo or CI run.

## Production boundary

This repo demonstrates the workspace boundary on one laptop. A client install
still needs its own production controls: TLS and identity at the Coder front
door, a managed database, private image/provider/module mirrors, per-tenant
network isolation where required, host-level egress policy, backups, and log
retention. Replace the demo's read/write host repository mount with immutable
application code and dedicated least-privilege input/output storage. Configure
a wildcard access URL, push the template with
`app_subdomain=true`, and disable path apps for browser-origin isolation; the
localhost demo deliberately keeps path apps enabled. Follow Coder's
[air-gapped deployment guide](https://coder.com/docs/install/airgap) rather
than treating `dev-up.sh` as a production installer.
