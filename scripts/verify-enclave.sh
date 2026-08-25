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
# coder ssh hands its arguments to the remote shell, so pass one quoted string.
ws() { coder ssh "$WS" -- "$1"; }

echo "== Topology (${DOCKER_HOST:-local Docker}) =="
check "enclave network '$NET' is internal (no NAT, no default route)" \
  test "$(docker network inspect -f '{{.Internal}}' "$NET" 2>/dev/null)" = "true"
CID="$(docker ps --format '{{.Names}}' | grep -E "^coder-.+-${WS}$" | head -1)"
check "workspace container '$CID' is running" test -n "$CID"
NETS="$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$CID" 2>/dev/null | xargs)"
check "workspace is attached ONLY to '$NET' (attached: ${NETS:-none})" test "$NETS" = "$NET"

echo "== Egress from inside the workspace (every one of these must fail) =="
for target in https://api.openai.com https://api.anthropic.com https://huggingface.co https://pypi.org http://1.1.1.1; do
  check_fails "cannot reach $target" ws "curl -sS -o /dev/null --max-time 6 $target"
done
check_fails "cannot resolve public DNS (example.com)" ws "getent hosts example.com"

echo "== Allowlisted services (must work) =="
check "model endpoint answers at \$MODEL_BASE_URL/models" ws 'curl -sf --max-time 10 "$MODEL_BASE_URL/models"'
check "Coder server reachable via enclave route (http://coder:3000/healthz)" ws 'curl -sf --max-time 10 http://coder:3000/healthz'
check "pipeline runs with UV_OFFLINE=1 (mock mode)" \
  ws 'cd ~/contract-enclave/pipeline && uv run -m contract_pipeline.cli analyze ../sample-contracts/meridian-msa.pdf --mock --out /tmp/verify-enclave'

echo "== Build hygiene (image is built from the pinned lockfile) =="
check "coder-template/build/uv.lock matches pipeline/uv.lock" diff -q pipeline/uv.lock coder-template/build/uv.lock
check "coder-template/build/pyproject.toml matches pipeline/pyproject.toml" diff -q pipeline/pyproject.toml coder-template/build/pyproject.toml

echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
