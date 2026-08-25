# Architecture

```
┌─ client network ──────────────────────────────────────────────────────┐
│                                                                       │
│   ┌─ Docker network "enclave" (internal: no NAT, no default route) ─┐ │
│   │                                                                 │ │
│   │   demo workspace ─► Coder server   (agent tunnel: IDE, terminal) │ │
│   │   VS Code, pipeline                                             │ │
│   │        └─────────► model server   (vLLM / Ollama: Qwen3-VL)     │ │
│   │                                                                 │ │
│   │   ...and nothing else. No DNS, no internet, no AI APIs.   ✕ ────│─│──✕
│   └─────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│   contracts in ──► findings report out.                               │
└───────────────────────────────────────────────────────────────────────┘
```

Enforcement, not policy: the demo workspace sits on a Docker `internal`
network. Docker configures no default route and drops traffic to other
networks. The only other containers allowed on that network are two hardened,
single-port gateways: the Coder control plane route (required to tunnel the IDE
to the browser) and an inference-only model relay that permits model discovery
and chat completions while rejecting Ollama's management API. Everything the
workspace needs at runtime (code-server, Python dependencies) is baked into
the image, so nothing needs to download. `scripts/verify-enclave.sh` checks the
live topology, capabilities, blocked egress, relay allowlist, and lockfile
drift; it exits non-zero on any miss.

## Scope of the demo boundary

This repository is a laptop demo, not a turn-key production deployment. The
verification proof assumes one running workspace in the `enclave` trust zone;
containers on the same Docker bridge can communicate with one another, so a
multi-tenant installation should give each tenant/workspace its own network or
enforce equivalent network policy. On a client server, Coder, the model server,
its database, registry/module mirrors, TLS ingress, identity, backups, log
retention, and host firewall policy must all be deployed inside the client's
controlled network. Coder's
[documented air-gapped settings](https://coder.com/docs/install/airgap) disable telemetry,
update checks, public STUN, and external provider/module downloads; those
server-side controls are outside this laptop template and are a necessary
second fence for a production claim. The localhost demo also uses path-based
workspace apps. A production deployment should configure Coder's
[wildcard access URL](https://coder.com/docs/admin/networking/wildcard-access-url),
set the template's `app_subdomain=true`, and disable path apps so workspace
JavaScript does not share the Coder API's browser origin.

For convenient local development, this template bind-mounts the repository
read/write from the host. That is not a host-hardening boundary. A production
template should bake reviewed application code into an immutable image and
mount only dedicated contract input and report output storage, read-only where
possible and without a Docker socket or host credentials.

## Repo layout

| Path | What it is |
|---|---|
| `pipeline/` | Python pipeline: PDF → OCR (vision model) → lost-value findings → report |
| `sample-contracts/` | Synthetic contracts with planted findings (`uv run generate.py`) |
| `coder-template/` | Coder workspace template: internal-network workspaces, offline image |
| `scripts/` | Local bring-up, enclave verification, model relay |
| `docs/` | This folder — deeper detail than the README |
