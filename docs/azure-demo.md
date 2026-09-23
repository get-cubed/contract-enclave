# Hosted demo on Azure

For live sessions where a laptop is not the right venue, one Azure VM can play
the part of the client's server. It runs the same stack as the laptop demo:
`scripts/dev-up.sh` on the VM builds the internal `enclave` network, the two
single-port gateways, and the workspace template. `scripts/verify-enclave.sh`
checks it the same way. The only additions are HTTPS in front of Coder and an
Azure firewall (NSG) around the VM.

What this does and doesn't show: it demonstrates the workspace boundary on a
real server, but that server sits in **our** Azure tenant, not behind the
client's firewall. Anything uploaded to it lives in our subscription. Use the
synthetic sample contracts unless the client explicitly agrees otherwise.

```
 you, co-presenters ── HTTPS :443 (allowlisted IPs) ──┐
 Let's Encrypt ─────── HTTP :80 (ACME + redirect) ────┤
                                                      ▼
 ┌─ Azure VM: Ubuntu 24.04, T4 GPU ─────────────────────────────────┐
 │  Caddy :443 ──► Coder :3000           Ollama :11434 (GPU)        │
 │                    ▲                        ▲                    │
 │ ┌─ Docker network "enclave" (internal) ──────────────────────┐   │
 │ │ demo workspace ──► coder gateway     model gateway         │   │
 │ │                    (raw TCP)         (inference only)      │   │
 │ └────────────────────────────────────────────────────────────┘   │
 └──────────────────────────────────────────────────────────────────┘
   NSG inbound: 22 and 443 from allowlisted IPs, 80 from anywhere.
```

## Prereqs

- `az` (logged in: `az login`), `terraform`, `ssh`, `git`, `curl`.
- **GPU quota.** Pay-as-you-go subscriptions start at 0 GPU vCPUs. In the portal,
  go to **Quotas → Compute**, pick the subscription and region (default South
  Central US), and raise **Standard NCASv3_T4 Family vCPUs** to 4. Without it,
  run on a CPU size (below): everything works, but OCR takes minutes per page.
- The subscription must already have the Microsoft.Compute, Microsoft.Network,
  and Microsoft.DevTestLab (auto-shutdown) providers registered. Terraform is
  set to never register providers on its own.

## Bring it up

```bash
AZURE_SUBSCRIPTION="<subscription name or id>" scripts/azure-demo.sh up
```

Terraform shows its plan and waits for `yes`. The script then installs Docker,
Ollama, Coder, and Caddy on the VM (plus the NVIDIA driver, with one reboot, on
GPU sizes). It syncs this checkout and runs `dev-up.sh` there, which pulls the
model and builds the image. It creates the Coder admin and the `demo`
workspace, loads the model, and runs every check. The first run takes about
10 minutes on a CPU size, plus a few more for the GPU driver and its reboot.
It ends by printing the URL and where the admin password is saved.

Settings are remembered, so later runs are just `scripts/azure-demo.sh up`. It
is re-runnable after any change to this repo: it re-syncs, rebuilds, and runs
`coder update demo`.

- **No GPU quota yet?** `VM_SIZE=Standard_D8as_v4 scripts/azure-demo.sh up`.
  When the quota lands, `VM_SIZE=Standard_NC4as_T4_v3 scripts/azure-demo.sh up`
  resizes the same VM in place, installs the driver, and moves Ollama to the GPU.
- **Letting someone else in** (a co-presenter, or the client's office):
  `EXTRA_HTTPS_CIDRS="203.0.113.7/32" scripts/azure-demo.sh up`. That opens HTTPS
  only. SSH stays limited to the machine running the script.
- **Changed networks?** Your current public IP is the allowlist entry.
  `up` or `start` refreshes it.

## Day of the demo

```bash
scripts/azure-demo.sh start     # boots the VM, recovers the workspace, loads the model, verifies
```

Log in at the printed `https://…cloudapp.azure.com` URL as `admin`. The
password is in `~/.local/state/contract-enclave/azure/coder-admin-password`.
Open **demo → code-server**, and in its terminal:

```bash
cd ~/contract-enclave/pipeline
uv run -m contract_pipeline.cli analyze ../sample-contracts/*.pdf --out ../reports
```

Results appear under the workspace's **Reports** button. To show another PDF,
drag it into the code-server file explorer: that is a browser upload through
Coder, not a route out of the workspace.

`scripts/azure-demo.sh verify` re-runs the proof at any time. It runs
`verify-enclave.sh` on the VM, then probes from your machine that HTTPS works
with a trusted certificate, port 80 only redirects, Coder's raw port and Ollama
are unreachable from the internet, and (on GPU sizes) the model is fully on the
GPU.

## Cost and teardown

| | South Central US, pay-as-you-go |
|---|---|
| `Standard_NC4as_T4_v3` (T4 16 GB, 4 vCPU, 28 GB) | ~$0.63/hour while running |
| `Standard_D8as_v4` (CPU fallback, 8 vCPU, 32 GB) | ~$0.46/hour while running |
| 128 GB Premium SSD + static IP | ~$22/month, charged even while stopped |

The VM deallocates itself every night at 22:00 US Central. Stop it yourself
with `scripts/azure-demo.sh stop`. When the engagement is over, remove
everything (resource group `rg-contract-enclave-demo`) with:

```bash
scripts/azure-demo.sh down
```

## Where things live

- `deploy/azure/main.tf` holds the infrastructure. `deploy/azure/host-setup.sh`
  is the on-VM service setup (pinned Ollama, Coder, and uv versions).
- Local state, including Terraform state, the SSH key, and the admin password,
  lives in `~/.local/state/contract-enclave/azure/`, outside the repo. Anyone
  else operating the same environment needs a copy of that directory.
- On the VM: the repo is at `~/contract-enclave`, Coder runs as the
  `contract-enclave-coder` systemd unit, and `ollama`, `caddy`, and `docker`
  are regular services. `scripts/azure-demo.sh ssh` opens a shell there.

## Unlike a client install

The VM itself has internet egress: it pulls packages, the model, and images
during setup. Only the workspace is sealed. A client install would also close
server egress and use private mirrors (see [architecture](architecture.md)).
Workspace apps use path-based routing on the single hostname, the same as
the laptop demo, rather than wildcard subdomains.
