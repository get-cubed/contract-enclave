# Contract Enclave — agent notes

Demo that finds money a service provider is owed under its own contracts
(missed escalations, unbilled work, expired discounts still applied), using
a vision model that runs entirely inside the network. Two invariants shape
everything here — never trade them away to fix a symptom:

1. **Nothing inside a workspace may reach the internet.** Workspaces live on
   an internal Docker network (`enclave`); their only neighbours are the
   Coder server and the model endpoint. Never fix a problem by attaching a
   workspace to another network, adding a runtime download, or calling an
   external AI API — sealing is the product. `scripts/verify-enclave.sh`
   must pass after any change to networking, the template, or the image.
2. **The model never does arithmetic.** It returns a formula built from
   numbers quoted out of the contract; `analyze.safe_eval` (restricted AST:
   `+ - * /` and parentheses only) computes the value. Model-supplied totals
   are discarded — keep it that way.

## Run / develop

- Bring-up: `scripts/dev-up.sh` (macOS/Linux; on Windows run it inside
  WSL2). Re-runnable; it prints the exact fix when something is missing.
  First run: create the account at http://localhost:3000, then
  `coder login http://localhost:3000`, then re-run the script.
- Workspace: `coder create demo --template contract-workspace -y`, then open
  http://localhost:3000 → **code-server**. Inside the workspace terminal:
  `cd ~/contract-enclave/pipeline && uv run -m contract_pipeline.cli analyze ../sample-contracts/*.pdf --out ../reports`
- After the template or image changes: `coder update demo` (or delete and
  recreate) so the workspace picks up the new build.
- Tests: `cd pipeline && uv run -m pytest` — no model needed.
- Fast iteration on report formatting: add `--mock` to the analyze command
  (skips the model entirely). `--perspective customer` flips the analysis to
  the buyer's side.

## Gotchas that already burned time

- Ollama model tag: `qwen3-vl:8b-instruct`, never bare `qwen3-vl:8b` — the
  bare tag is the *thinking* variant and returns empty content on
  JSON-extraction prompts.
- `coder-template/build/{pyproject.toml,uv.lock}` must stay byte-identical
  to `pipeline/`'s copies: the image is built from them. `dev-up.sh` copies
  them before every build, and `verify-enclave.sh` fails on drift.
- Workspaces run uv with `UV_OFFLINE=1 UV_FROZEN=1` against `/opt/venv`
  baked into the image. If `uv sync` fails inside a workspace, the image is
  stale — re-run `dev-up.sh` and `coder update` — do not relax the offline
  flags.
- Ollama returns 403 for requests whose Host header isn't localhost-like;
  `scripts/model-relay.py` rewrites the header. Don't swap it for a plain
  TCP proxy (that's what the coder gateway uses, and it only works there
  because Coder doesn't check Host).
- On a native Linux Docker engine (not Docker Desktop), containers cannot
  reach host-loopback services: Ollama and Coder must listen on 0.0.0.0.
  `dev-up.sh` detects this, and prints the systemd override if Ollama was
  installed as a service. A ufw firewall blocking the Docker bridge shows up
  the same way.
- Reports land in `reports/` (gitignored) and are served by the workspace's
  **Reports** app button. `summary.md` is the portfolio view.
- Dollar values of `n/a` are correct behavior when the contract gives no
  defensible numbers — don't "fix" them into estimates.

## Layout

- `pipeline/` — PDF → per-page OCR (vision model) → findings JSON → md/html
  reports. Entry point: `contract_pipeline/cli.py`; prompts and the safe
  evaluator: `contract_pipeline/analyze.py`. Every model call goes through
  `model.py`'s `chat()`, which narrates progress and feeds the per-contract
  `model-log.md` audit file — route any new model call through it so the
  audit stays complete.
- `coder-template/` — the Coder workspace template; `build/` is the offline
  workspace image.
- `sample-contracts/` — synthetic and watermarked; regenerate with
  `uv run generate.py` in that directory.
- `scripts/` — bring-up, enclave verification, model relay.
- `docs/how-it-works.html` — visual walkthrough; open directly in a browser.
