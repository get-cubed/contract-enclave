#!/usr/bin/env bash
# Turns a fresh Ubuntu 24.04 Azure VM into the host that scripts/dev-up.sh
# expects, with everything running as system services so it survives the
# nightly auto-shutdown: Docker Engine, the NVIDIA driver (GPU sizes only),
# Ollama, Coder, uv, and Caddy for HTTPS. Re-runnable.
#
# Run as root on the VM (scripts/azure-demo.sh does this over SSH):
#   sudo deploy/azure/host-setup.sh <admin-user> <public-hostname>
# Exit code 100 means a newly installed GPU driver needs a reboot; reboot and
# run it again.
#
# Only the host is online. Workspaces still sit on the internal Docker network
# that dev-up.sh creates, exactly as on a laptop.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
[ $# = 2 ] || { echo "usage: $0 <admin-user> <public-hostname>"; exit 2; }
DEMO_USER="$1"
PUBLIC_HOST="$2"
id "$DEMO_USER" >/dev/null

# Pinned to what the laptop demo was validated with.
OLLAMA_VERSION=0.32.14
CODER_VERSION=2.35.4
UV_VERSION=0.12.5          # keep in step with coder-template/build/Dockerfile
# The advertised model context is far larger, but Ollama sizes its default to
# the GPU (4k on a 16 GB T4), which would silently truncate long contracts.
OLLAMA_CONTEXT_LENGTH=32768

export DEBIAN_FRONTEND=noninteractive
apt_get() { apt-get -y -q -o DPkg::Lock::Timeout=600 "$@"; }

# write_if_changed <path> <mode>  (content on stdin); returns 0 when changed
write_if_changed() {
  local tmp
  tmp="$(mktemp)"
  cat > "$tmp"
  if [ -f "$1" ] && cmp -s "$tmp" "$1"; then rm -f "$tmp"; return 1; fi
  install -D -m "$2" "$tmp" "$1"
  rm -f "$tmp"
}

echo "==> Base packages"
apt_get update
# zstd: Ollama's Linux release archives are .tar.zst.
apt_get install ca-certificates curl gnupg pciutils zstd

# Prints e.g. "570-server" for an installed NVIDIA driver package, else nothing.
installed_nvidia_driver() {
  dpkg-query -W -f '${Package} ${Status}\n' 'nvidia-headless-*' 'nvidia-driver-*' 2>/dev/null \
    | awk '/install ok installed/ && match($1, /-[0-9]+(-server)?/) { print substr($1, RSTART + 1, RLENGTH - 1); exit }'
}

GPU=0
if lspci | grep -qi nvidia; then GPU=1; fi
if [ "$GPU" = 1 ]; then
  echo "==> NVIDIA driver"
  if ! nvidia-smi >/dev/null 2>&1; then
    if [ -z "$(installed_nvidia_driver)" ]; then
      # Canonical's prebuilt, signed modules for the linux-azure kernel.
      apt_get install ubuntu-drivers-common
      ubuntu-drivers install --gpgpu
    fi
    DRIVER="$(installed_nvidia_driver)"
    [ -n "$DRIVER" ] || { echo "    FAIL: ubuntu-drivers installed no NVIDIA driver"; exit 1; }
    # --gpgpu leaves out nvidia-smi, which Ollama's installer and we both use.
    command -v nvidia-smi >/dev/null 2>&1 || apt_get install "nvidia-utils-${DRIVER}"
    modprobe nvidia 2>/dev/null || true
    if ! nvidia-smi >/dev/null 2>&1; then
      echo "    driver ${DRIVER} installed; reboot required to load it"
      exit 100
    fi
  fi
  nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader | sed 's/^/    /'
fi

echo "==> Docker Engine"
if ! command -v docker >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  # shellcheck disable=SC1091
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt_get update
  apt_get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin
fi
systemctl enable --now docker >/dev/null
usermod -aG docker "$DEMO_USER"

echo "==> Ollama $OLLAMA_VERSION"
if ! ollama --version 2>/dev/null | grep -q "$OLLAMA_VERSION"; then
  curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION="$OLLAMA_VERSION" sh
fi
# The enclave gateway reaches Ollama over the Docker bridge, so it listens on
# all interfaces; the NSG keeps 11434 closed to everything outside the VM.
# KEEP_ALIVE keeps the model resident, so nobody waits on a cold load mid-demo.
OLLAMA_CHANGED=0
write_if_changed /etc/systemd/system/ollama.service.d/contract-enclave.conf 0644 <<EOF && OLLAMA_CHANGED=1
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
Environment="OLLAMA_KEEP_ALIVE=24h"
Environment="OLLAMA_CONTEXT_LENGTH=${OLLAMA_CONTEXT_LENGTH}"
Environment="OLLAMA_NUM_PARALLEL=1"
EOF
systemctl daemon-reload
systemctl enable ollama >/dev/null
# Ollama detects GPUs at startup: restart after a config change, and when a GPU
# is present but the running server was started without one.
if [ "$OLLAMA_CHANGED" = 1 ] || ! systemctl is-active -q ollama \
  || { [ "$GPU" = 1 ] && ! journalctl -u ollama -b --no-pager 2>/dev/null | grep -qi 'library=cuda'; }; then
  systemctl restart ollama
fi

echo "==> uv $UV_VERSION"
if [ "$(uv --version 2>/dev/null | awk '{print $2}')" != "$UV_VERSION" ]; then
  curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" \
    | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
fi

echo "==> Coder $CODER_VERSION"
if ! coder version 2>/dev/null | grep -q "v${CODER_VERSION}"; then
  curl -fsSL https://coder.com/install.sh | sh -s -- --method standalone --version "$CODER_VERSION"
fi
# Runs as the admin user, like `coder server` on a laptop: its built-in
# database and the CLI session dev-up.sh uses share ~/.config/coderv2.
# Listens on all interfaces for the enclave gateway; Caddy is the only public
# front door (the NSG never opens 3000).
CODER_CHANGED=0
write_if_changed /etc/systemd/system/contract-enclave-coder.service 0644 <<EOF && CODER_CHANGED=1
[Unit]
Description=Coder server for the contract-enclave demo
Wants=network-online.target
After=network-online.target docker.service

[Service]
User=${DEMO_USER}
SupplementaryGroups=docker
Environment=CODER_ACCESS_URL=https://${PUBLIC_HOST}
Environment=CODER_HTTP_ADDRESS=0.0.0.0:3000
Environment=CODER_SECURE_AUTH_COOKIE=true
Environment=CODER_PROXY_TRUSTED_HEADERS=X-Forwarded-For
Environment=CODER_PROXY_TRUSTED_ORIGINS=127.0.0.1/32
Environment=CODER_TELEMETRY_ENABLE=false
Environment=CODER_UPDATE_CHECK=false
ExecStart=/usr/local/bin/coder server
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable contract-enclave-coder >/dev/null
if [ "$CODER_CHANGED" = 1 ] || ! systemctl is-active -q contract-enclave-coder; then
  systemctl restart contract-enclave-coder
fi

echo "==> Caddy (HTTPS for $PUBLIC_HOST)"
command -v caddy >/dev/null 2>&1 || apt_get install caddy
# HTTP-01 only: 443 is allowlisted, so Let's Encrypt cannot reach TLS-ALPN.
CADDY_CHANGED=0
write_if_changed /etc/caddy/Caddyfile 0644 <<EOF && CADDY_CHANGED=1
${PUBLIC_HOST} {
	tls {
		issuer acme {
			disable_tlsalpn_challenge
		}
	}
	reverse_proxy 127.0.0.1:3000
}
EOF
systemctl enable caddy >/dev/null
if [ "$CADDY_CHANGED" = 1 ] || ! systemctl is-active -q caddy; then
  systemctl restart caddy
fi

echo "==> Waiting for services"
for ((attempt = 0; attempt < 90; attempt++)); do
  curl -sf http://localhost:3000/healthz >/dev/null 2>&1 && curl -sf http://localhost:11434/api/version >/dev/null 2>&1 && break
  sleep 2
done
curl -sf http://localhost:3000/healthz >/dev/null || { echo "    FAIL: Coder not healthy"; journalctl -u contract-enclave-coder -n 30 --no-pager; exit 1; }
curl -sf http://localhost:11434/api/version >/dev/null || { echo "    FAIL: Ollama not answering"; journalctl -u ollama -n 30 --no-pager; exit 1; }
echo "    Coder, Ollama, Docker, and Caddy are running"
