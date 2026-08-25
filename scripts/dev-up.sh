#!/usr/bin/env bash
# Local demo bring-up: Ollama + model + enclave network + Coder server.
# Works on macOS and Linux; on Windows run it inside WSL2 (see
# docs/running-the-demo.md). Re-runnable.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
# The bare qwen3-vl:8b tag is the thinking variant -- keep -instruct.
MODEL="${MODEL_NAME:-qwen3-vl:8b-instruct}"
NET="${ENCLAVE_NETWORK:-enclave}"
IMAGE="contract-enclave-workspace:latest"
RELAY_IMAGE="contract-enclave-relay:latest"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/contract-enclave"
mkdir -p "$STATE_DIR"

need() {  # command install-hint
  command -v "$1" >/dev/null 2>&1 && return
  echo "Missing '$1'. Install it first:  $2"
  exit 1
}
case "$(uname -s)" in
  Darwin)
    need docker "Docker Desktop (docker.com), then start it"
    need ollama "brew install ollama"
    need coder  "brew install coder/coder/coder"
    need uv     "brew install uv"
    ;;
  Linux)
    need docker "https://docs.docker.com/engine/install/ (or enable Docker Desktop's WSL integration)"
    need ollama "curl -fsSL https://ollama.com/install.sh | sh"
    need coder  "curl -fsSL https://coder.com/install.sh | sh"
    need uv     "curl -LsSf https://astral.sh/uv/install.sh | sh"
    ;;
  *) echo "Unsupported OS '$(uname -s)'. On Windows, run this inside WSL2."; exit 1 ;;
esac
need curl "your operating system's curl package"

IS_WSL=0
if [ -r /proc/sys/kernel/osrelease ] && grep -qi microsoft /proc/sys/kernel/osrelease; then
  IS_WSL=1
  echo "==> Windows/WSL2 detected (Docker Desktop WSL integration must be enabled)"
fi

echo "==> Docker"
docker info >/dev/null 2>&1 || { echo "Docker is not running"; exit 1; }
# Docker Desktop (macOS/Windows) lets containers reach services the host has
# bound to localhost. A native Linux engine does not -- there, Ollama and
# Coder must listen on all interfaces for the enclave gateways to reach them.
if docker info --format '{{.OperatingSystem}}' 2>/dev/null | grep -qi 'docker desktop'; then
  DESKTOP=1
else
  DESKTOP=0
fi

echo "==> Ollama"
OLLAMA_LOG="$STATE_DIR/ollama.log"
if ! ollama list >/dev/null 2>&1; then
  if [ "$DESKTOP" = 1 ] && [ "$IS_WSL" = 0 ]; then
    nohup ollama serve > "$OLLAMA_LOG" 2>&1 &
  else
    OLLAMA_HOST=0.0.0.0:11434 nohup ollama serve > "$OLLAMA_LOG" 2>&1 &
  fi
  echo -n "    waiting for Ollama"
  for ((attempt = 0; attempt < 30; attempt++)); do
    ollama list >/dev/null 2>&1 && break
    echo -n "."
    sleep 2
  done
  echo
fi
if ! ollama list >/dev/null 2>&1; then
  echo "    FAIL: Ollama did not become ready. Last log lines:"
  tail -20 "$OLLAMA_LOG" 2>/dev/null || true
  exit 1
fi
if ! ollama list | awk -v model="$MODEL" 'NR > 1 && $1 == model { found = 1 } END { exit !found }'; then
  echo "    pulling $MODEL (several GB)"
  ollama pull "$MODEL"
fi

echo "==> Enclave network '$NET' (internal: no NAT, no default route)"
if docker network inspect "$NET" >/dev/null 2>&1; then
  if [ "$(docker network inspect -f '{{.Internal}}' "$NET")" != "true" ]; then
    echo "    FAIL: Docker network '$NET' already exists but is not internal."
    echo "    Stop/remove its containers and delete it, or choose another ENCLAVE_NETWORK."
    exit 1
  fi
else
  docker network create --internal "$NET" >/dev/null
fi

echo "==> Workspace image (also supplies the separately tagged relay image)"
cp pipeline/pyproject.toml pipeline/uv.lock coder-template/build/
docker build -q -t "$IMAGE" coder-template/build >/dev/null
docker tag "$IMAGE" "$RELAY_IMAGE"

# Allowlist gateways: the ONLY things a workspace can reach. Each forwards a
# single port to a service on this machine, via the host-gateway mapping
# (built into Docker Desktop; explicit on Linux). Recreated on every run so
# flag changes take effect. They sit on the enclave *and* the default
# bridge; on a server install the real services join the enclave directly
# and these are not needed.
#   - coder: raw TCP relay (socat); the agent tunnel is plain HTTP/websocket.
#   - model: HTTP relay (scripts/model-relay.py) that rewrites the Host header,
#     and allows only model listing + chat completions. Both relays use the
#     separately tagged copy of the workspace image so there is no second
#     mutable image dependency and Terraform can replace the workspace tag
#     while the gateways are running.
gateway_tcp() {  # name alias port
  docker rm -f "$1" >/dev/null 2>&1 || true
  docker run -d --name "$1" --restart unless-stopped --network "$NET" --network-alias "$2" \
    --read-only --cap-drop ALL --security-opt no-new-privileges \
    --add-host host.docker.internal:host-gateway \
    "$RELAY_IMAGE" socat "TCP-LISTEN:$3,fork,reuseaddr" "TCP:host.docker.internal:$3" >/dev/null
  docker network connect bridge "$1"
}
gateway_http() {  # name alias port
  docker rm -f "$1" >/dev/null 2>&1 || true
  docker run -d --name "$1" --restart unless-stopped --network "$NET" --network-alias "$2" \
    --read-only --cap-drop ALL --security-opt no-new-privileges \
    --add-host host.docker.internal:host-gateway \
    -v "$REPO/scripts/model-relay.py:/relay.py:ro" "$RELAY_IMAGE" \
    python3 /relay.py "$3" host.docker.internal "$3" >/dev/null
  docker network connect bridge "$1"
}
echo "==> Allowlist gateways: coder:3000 (tcp) and model:11434 (http)"
gateway_tcp  enclave-gw-coder coder 3000
gateway_http enclave-gw-model model 11434

probe() { docker run --rm --network "$NET" "$RELAY_IMAGE" curl -sf --max-time 8 "$1" >/dev/null 2>&1; }

echo "==> Smoke check: model reachable through its gateway"
if ! probe http://model:11434/v1/models; then
  echo "    FAIL: cannot reach Ollama through the enclave gateway."
  if [ "$DESKTOP" = 0 ] || [ "$IS_WSL" = 1 ]; then
    cat <<'MSG'
    On native Linux and WSL2, Ollama must listen on all interfaces so the
    gateway can reach it. If it runs as a systemd service, fix it with:
        sudo systemctl edit ollama    # add the two lines:
            [Service]
            Environment="OLLAMA_HOST=0.0.0.0"
        sudo systemctl restart ollama
    A Linux/Windows firewall or enterprise WSL policy blocking the Docker
    bridge/localhost-forwarding path causes the same failure. Keep port 11434
    restricted to this trusted machine/network.
MSG
  fi
  exit 1
fi
if probe http://model:11434/api/tags; then
  echo "    FAIL: model relay exposed Ollama's management API; refusing to continue."
  exit 1
fi

echo "==> Coder server"
if ! curl -sf http://localhost:3000/healthz >/dev/null 2>&1; then
  CODER_LOG="$STATE_DIR/coder.log"
  if [ "$DESKTOP" = 1 ] && [ "$IS_WSL" = 0 ]; then
    nohup coder server --access-url http://localhost:3000 > "$CODER_LOG" 2>&1 &
  else
    echo "    NOTE: native Linux/WSL binds Coder to all interfaces so the gateway can reach it."
    echo "    Keep port 3000 restricted to this trusted host/network with the host firewall."
    nohup coder server --access-url http://localhost:3000 --http-address 0.0.0.0:3000 > "$CODER_LOG" 2>&1 &
  fi
  echo -n "    waiting for Coder"
  for ((attempt = 0; attempt < 90; attempt++)); do
    curl -sf http://localhost:3000/healthz >/dev/null 2>&1 && break
    echo -n "."
    sleep 2
  done
  echo
  if ! curl -sf http://localhost:3000/healthz >/dev/null 2>&1; then
    echo "    FAIL: Coder did not become ready. Last log lines:"
    tail -20 "$CODER_LOG" 2>/dev/null || true
    exit 1
  fi
fi
if ! probe http://coder:3000/healthz; then
  echo "    FAIL: Coder is up but not reachable through its gateway."
  if [ "$DESKTOP" = 0 ] || [ "$IS_WSL" = 1 ]; then
    echo "    On native Linux/WSL, restart Coder with --http-address 0.0.0.0:3000"
    echo "    and restrict port 3000 with the host firewall."
  fi
  exit 1
fi

if coder whoami >/dev/null 2>&1; then
  echo "==> Pushing template (all variables passed explicitly; Coder persists them)"
  coder templates push contract-workspace -d coder-template --yes \
    --variable repo_host_path="$REPO" \
    --variable model_base_url=http://model:11434/v1 \
    --variable model_name="$MODEL" \
    --variable enclave_network="$NET" \
    --variable agent_coder_url=http://coder:3000 \
    --variable app_subdomain=false
  echo "==> Done. Create/update a workspace:  coder create demo --template contract-workspace -y"
  echo "    Then prove the enclave:            scripts/verify-enclave.sh demo"
else
  cat <<MSG

Coder is up: http://localhost:3000
First time only:
  1. Open http://localhost:3000 and create the admin account
  2. coder login http://localhost:3000
  3. Re-run scripts/dev-up.sh (it will push the template)
MSG
fi

if [ "$IS_WSL" = 1 ]; then
  echo "Windows note: GPU acceleration requires a supported Windows driver and a working GPU inside WSL."
fi
