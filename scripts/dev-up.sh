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
if ! pgrep -x ollama >/dev/null; then
  if [ "$DESKTOP" = 1 ]; then
    nohup ollama serve > "$HOME/.ollama-serve.log" 2>&1 &
  else
    OLLAMA_HOST=0.0.0.0:11434 nohup ollama serve > "$HOME/.ollama-serve.log" 2>&1 &
  fi
  sleep 3
fi
ollama list | grep -q "$MODEL" || { echo "    pulling $MODEL (several GB)"; ollama pull "$MODEL"; }

echo "==> Enclave network '$NET' (internal: no NAT, no default route)"
docker network inspect "$NET" >/dev/null 2>&1 || docker network create --internal "$NET" >/dev/null

echo "==> Workspace image (also hosts the model relay)"
cp pipeline/pyproject.toml pipeline/uv.lock coder-template/build/
docker build -q -t contract-enclave-workspace:latest coder-template/build >/dev/null

# Allowlist gateways: the ONLY things a workspace can reach. Each forwards a
# single port to a service on this machine, via the host-gateway mapping
# (built into Docker Desktop; explicit on Linux). Recreated on every run so
# flag changes take effect. They sit on the enclave *and* the default
# bridge; on a server install the real services join the enclave directly
# and these are not needed.
#   - coder: raw TCP relay (socat); the agent tunnel is plain HTTP/websocket.
#   - model: HTTP relay (scripts/model-relay.py) that rewrites the Host header,
#     because Ollama 403s any request whose Host isn't localhost-like. It runs
#     on the workspace image so no extra image pull is needed.
gateway_tcp() {  # name alias port
  docker rm -f "$1" >/dev/null 2>&1 || true
  docker run -d --name "$1" --restart unless-stopped --network "$NET" --network-alias "$2" \
    --add-host host.docker.internal:host-gateway \
    alpine/socat "TCP-LISTEN:$3,fork,reuseaddr" "TCP:host.docker.internal:$3" >/dev/null
  docker network connect bridge "$1"
}
gateway_http() {  # name alias port
  docker rm -f "$1" >/dev/null 2>&1 || true
  docker run -d --name "$1" --restart unless-stopped --network "$NET" --network-alias "$2" \
    --add-host host.docker.internal:host-gateway \
    -v "$REPO/scripts/model-relay.py:/relay.py:ro" contract-enclave-workspace:latest \
    python3 /relay.py "$3" host.docker.internal "$3" >/dev/null
  docker network connect bridge "$1"
}
echo "==> Allowlist gateways: coder:3000 (tcp) and model:11434 (http)"
gateway_tcp  enclave-gw-coder coder 3000
gateway_http enclave-gw-model model 11434

probe() { docker run --rm --network "$NET" contract-enclave-workspace:latest curl -sf --max-time 8 "$1" >/dev/null 2>&1; }

echo "==> Smoke check: model reachable through its gateway"
if ! probe http://model:11434/v1/models; then
  echo "    FAIL: cannot reach Ollama through the enclave gateway."
  if [ "$DESKTOP" = 0 ]; then
    cat <<'MSG'
    On Linux, Ollama must listen on all interfaces. If it runs as a systemd
    service (the installer sets one up), fix it with:
        sudo systemctl edit ollama    # add the two lines:
            [Service]
            Environment="OLLAMA_HOST=0.0.0.0"
        sudo systemctl restart ollama
    A host firewall (ufw) blocking the Docker bridge causes the same failure.
MSG
  fi
  exit 1
fi

echo "==> Coder server"
if ! curl -sf http://localhost:3000/healthz >/dev/null 2>&1; then
  if [ "$DESKTOP" = 1 ]; then
    nohup coder server --access-url http://localhost:3000 > "$HOME/.coder-server.log" 2>&1 &
  else
    nohup coder server --access-url http://localhost:3000 --http-address 0.0.0.0:3000 > "$HOME/.coder-server.log" 2>&1 &
  fi
  echo -n "    waiting for Coder"
  until curl -sf http://localhost:3000/healthz >/dev/null 2>&1; do echo -n "."; sleep 2; done
  echo
fi
probe http://coder:3000/healthz || { echo "    FAIL: Coder is up but not reachable through its gateway."; exit 1; }

if coder whoami >/dev/null 2>&1; then
  echo "==> Pushing template (all variables passed explicitly; Coder persists them)"
  coder templates push contract-workspace -d coder-template --yes \
    --variable repo_host_path="$REPO" \
    --variable model_base_url=http://model:11434/v1 \
    --variable model_name="$MODEL" \
    --variable enclave_network="$NET" \
    --variable agent_coder_url=http://coder:3000
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
