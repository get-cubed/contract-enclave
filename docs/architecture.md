# Architecture

```
┌─ client network ──────────────────────────────────────────────────────┐
│                                                                       │
│   ┌─ Docker network "enclave" (internal: no NAT, no default route) ─┐ │
│   │                                                                 │ │
│   │   workspace(s) ──► Coder server   (agent tunnel: IDE, terminal) │ │
│   │   VS Code, pipeline                                             │ │
│   │        └─────────► model server   (vLLM / Ollama: Qwen3-VL)     │ │
│   │                                                                 │ │
│   │   ...and nothing else. No DNS, no internet, no AI APIs.   ✕ ────│─│──✕
│   └─────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│   contracts in ──► findings report out.                               │
└───────────────────────────────────────────────────────────────────────┘
```

Enforcement, not policy: workspaces sit on a Docker `internal` network, so the
container has no route to the outside at all. Their only neighbours are the
Coder control plane (required — it tunnels the IDE to your browser) and the
model endpoint. Everything a workspace needs at runtime (code-server, Python
deps) is baked into the image, so nothing ever needs to download. (A server
install inside a client's network would close the box's own egress at their
firewall as a second fence; the demo's guarantee is the Docker layer.)
`scripts/verify-enclave.sh` proves all of this and is meant to be re-run.

## Repo layout

| Path | What it is |
|---|---|
| `pipeline/` | Python pipeline: PDF → OCR (vision model) → lost-value findings → report |
| `sample-contracts/` | Synthetic contracts with planted findings (`uv run generate.py`) |
| `coder-template/` | Coder workspace template: internal-network workspaces, offline image |
| `scripts/` | Local bring-up, enclave verification, model relay |
| `docs/` | This folder — deeper detail than the README |
