# Contract Enclave: Contract Value Recovery, Inside the Firewall

Finds money a business is owed under its own old contracts — a missed
escalation, work delivered but never billed, a discount still running after
it expired — by reading the contracts with an AI model that runs entirely
inside your network. **No document content ever leaves the network it runs
in, and no calls go to external AI APIs.**

That's built for the real use case: a vendor or service provider who has
delivered work for years and quietly stopped collecting everything their
contract entitles them to. (The mirror image — a customer checking whether
*they're* overpaying — is one flag away; see [docs/running-the-demo.md](docs/running-the-demo.md).)

**[See how it works →](docs/how-it-works.html)** — open directly in a
browser (`open docs/how-it-works.html`), no server needed. Start here.

## Run it

Prereqs: Docker plus `ollama`, `coder`, and `uv`. macOS: Docker Desktop, then
`brew install ollama coder/coder/coder uv`. Linux and Windows (WSL2):
see [docs/running-the-demo.md](docs/running-the-demo.md).

```bash
scripts/dev-up.sh
```

First run only: it'll ask you to create an account at http://localhost:3000,
then `coder login http://localhost:3000` and run the command again.

```bash
coder create demo --template contract-workspace -y
```

Open the `demo` workspace at http://localhost:3000, click **code-server**,
and in its terminal:

```bash
cd ~/contract-enclave/pipeline
uv run -m contract_pipeline.cli analyze ../sample-contracts/*.pdf --out ../reports
```

Click the **Reports** button on the workspace page to see the results —
including `*.model-log.md`, a complete audit of every prompt and response,
kept on local disk.

## Prove it's actually sealed

```bash
scripts/verify-enclave.sh demo
```

Confirms the workspace has no route to the internet at all — only the AI
model and the Coder control plane it needs. Non-zero exit if anything fails.

## More detail

- [CLAUDE.md](CLAUDE.md) — working on this repo with an AI agent? Start it there.
- [docs/architecture.md](docs/architecture.md) — the network boundary, and what's in this repo
- [docs/running-the-demo.md](docs/running-the-demo.md) — full walkthrough, options, tests
- [docs/notes.md](docs/notes.md) — model choices, what's synthetic, context limits
