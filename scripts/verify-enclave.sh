#!/usr/bin/env bash
# Re-runnable proof that a workspace is sealed: no egress, allowlist only.
# Usage: scripts/verify-enclave.sh [workspace-name] [docker-ssh-target]
#   workspace-name     Coder workspace to check (default: demo)
#   docker-ssh-target  user@host of a remote machine running the stack (the
#                      user must be in its docker group). When set, the
#                      topology checks inspect that host's Docker over ssh;
#                      omit it for the local laptop demo. Workspace checks
#                      always target whatever `coder login` points at.
# Exit code is non-zero if any check fails.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
WS="${1:-demo}"
NET="${ENCLAVE_NETWORK:-enclave}"
[ -n "${2:-}" ] && export DOCKER_HOST="ssh://$2"
pass=0; fail=0
ok() { echo "  PASS  $1"; pass=$((pass + 1)); }
ko() { echo "  FAIL  $1"; fail=$((fail + 1)); }
check()       { local d="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$d"; else ko "$d"; fi; }
check_fails() { local d="$1"; shift; if "$@" >/dev/null 2>&1; then ko "$d"; else ok "$d"; fi; }
contains()    { case "$1" in *"$2"*) return 0 ;; *) return 1 ;; esac; }
gateway_hardened() {
  local name="$1" read_only cap_drop security_opt
  read_only="$(docker inspect -f '{{.HostConfig.ReadonlyRootfs}}' "$name" 2>/dev/null)" || return 1
  cap_drop="$(docker inspect -f '{{join .HostConfig.CapDrop " "}}' "$name" 2>/dev/null)" || return 1
  security_opt="$(docker inspect -f '{{join .HostConfig.SecurityOpt " "}}' "$name" 2>/dev/null)" || return 1
  test "$read_only" = "true" && test "$cap_drop" = "ALL" && contains "$security_opt" "no-new-privileges"
}
# coder ssh hands its arguments to the remote shell, so pass one quoted string.
ws() { coder ssh "$WS" -- "$1"; }
networks_for() {
  docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$1" 2>/dev/null \
    | xargs -n1 | sort | xargs
}

echo "== Topology (${DOCKER_HOST:-local Docker}) =="
check "enclave network '$NET' is internal (no NAT, no default route)" \
  test "$(docker network inspect -f '{{.Internal}}' "$NET" 2>/dev/null)" = "true"
CID="$(docker ps --format '{{.Names}}' | grep -E "^coder-.+-${WS}$" | head -1)"
check "workspace container '$CID' is running" test -n "$CID"
NETS="$(networks_for "$CID")"
check "workspace is attached ONLY to '$NET' (attached: ${NETS:-none})" test "$NETS" = "$NET"
check_fails "workspace has no default route" \
  ws "grep -Eq '^[^[:space:]]+[[:space:]]+00000000[[:space:]]' /proc/net/route"
PEERS="$(docker network inspect -f '{{range $id, $c := .Containers}}{{$c.Name}} {{end}}' "$NET" 2>/dev/null \
  | xargs -n1 | sort | xargs)"
EXPECTED_PEERS="$(printf '%s\n' "$CID" enclave-gw-coder enclave-gw-model | sort | xargs)"
check "enclave contains only this workspace and its two gateways (attached: ${PEERS:-none})" \
  test "$PEERS" = "$EXPECTED_PEERS"
CODER_GW_NETS="$(networks_for enclave-gw-coder)"
MODEL_GW_NETS="$(networks_for enclave-gw-model)"
check "Coder gateway bridges exactly '$NET' and 'bridge'" test "$CODER_GW_NETS" = "bridge $NET"
check "model gateway bridges exactly '$NET' and 'bridge'" test "$MODEL_GW_NETS" = "bridge $NET"
CAP_DROP="$(docker inspect -f '{{join .HostConfig.CapDrop " "}}' "$CID" 2>/dev/null)"
check "workspace drops all Linux capabilities" test "$CAP_DROP" = "ALL"
SECURITY_OPT="$(docker inspect -f '{{join .HostConfig.SecurityOpt " "}}' "$CID" 2>/dev/null)"
check "workspace enforces no-new-privileges" contains "$SECURITY_OPT" "no-new-privileges"
check "Coder gateway is read-only, capability-free, and no-new-privileges" gateway_hardened enclave-gw-coder
check "model gateway is read-only, capability-free, and no-new-privileges" gateway_hardened enclave-gw-model

echo "== Egress from inside the workspace (every one of these must fail) =="
for target in https://api.openai.com https://api.anthropic.com https://huggingface.co https://pypi.org http://1.1.1.1; do
  check_fails "cannot reach $target" ws "curl -sS -o /dev/null --max-time 6 $target"
done
check_fails "cannot resolve public DNS (example.com)" ws "getent hosts example.com"

echo "== Allowlisted services (must work) =="
# Expansion intentionally happens in the workspace.
# shellcheck disable=SC2016
check "model endpoint answers at \$MODEL_BASE_URL/models" ws 'curl -sf --max-time 10 "$MODEL_BASE_URL/models"'
check_fails "Ollama management API is blocked by the inference-only relay" \
  ws 'curl -sf --max-time 10 http://model:11434/api/tags'
check "Coder server reachable via enclave route (http://coder:3000/healthz)" ws 'curl -sf --max-time 10 http://coder:3000/healthz'
check "pipeline runs with UV_OFFLINE=1 (mock mode)" \
  ws 'cd ~/contract-enclave/pipeline && uv run -m contract_pipeline.cli analyze ../sample-contracts/meridian-msa.pdf --mock --out /tmp/verify-enclave'

echo "== Build hygiene (image is built from the pinned lockfile) =="
check "coder-template/build/uv.lock matches pipeline/uv.lock" diff -q pipeline/uv.lock coder-template/build/uv.lock
check "coder-template/build/pyproject.toml matches pipeline/pyproject.toml" diff -q pipeline/pyproject.toml coder-template/build/pyproject.toml

echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
