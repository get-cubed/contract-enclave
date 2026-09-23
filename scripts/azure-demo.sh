#!/usr/bin/env bash
# Hosted demo environment on Azure: one VM that plays the client's server and
# runs the same stack as scripts/dev-up.sh, with HTTPS in front of Coder.
# See docs/azure-demo.md.
#
#   AZURE_SUBSCRIPTION="<name or id>" scripts/azure-demo.sh up
#   scripts/azure-demo.sh verify | info | ssh [cmd] | stop | start | down
#
# `up` is re-runnable. It applies Terraform (you approve the plan; AUTO_APPROVE=1
# skips the prompt), installs or updates the host services, syncs this
# checkout, runs dev-up.sh on the VM, creates or updates the `demo` workspace,
# and runs the verification. The first `up` remembers its settings. To change
# one later, set it on another `up`: VM_SIZE, AZURE_LOCATION, or
# EXTRA_HTTPS_CIDRS (comma-separated; "" clears). Your current public IP is
# always the SSH/HTTPS allowlist entry; `up` and `start` refresh it.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
TF_DIR="$REPO/deploy/azure"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/contract-enclave/azure"
SETTINGS="$STATE/settings"
KEY="$STATE/id_ed25519"
PASSWORD_FILE="$STATE/coder-admin-password"
KNOWN_HOSTS="$STATE/known_hosts"
TFVARS="$STATE/terraform.tfvars.json"
export TF_DATA_DIR="$STATE/tf-data"
WS=demo
CODER_ADMIN="admin"
REMOTE_REPO=contract-enclave   # under the VM admin user's home
MODEL="${MODEL_NAME:-qwen3-vl:8b-instruct}"

die() { echo "ERROR: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "missing '$1' ($2)"; }

mkdir -p "$STATE"
chmod 700 "$STATE"

load_settings() {
  SAVED_SUBSCRIPTION="" SAVED_LOCATION="" SAVED_VM_SIZE="" SAVED_EXTRA_HTTPS_CIDRS=""
  # shellcheck disable=SC1090
  if [ -f "$SETTINGS" ]; then . "$SETTINGS"; fi
  SUBSCRIPTION="${AZURE_SUBSCRIPTION:-$SAVED_SUBSCRIPTION}"
  LOCATION="${AZURE_LOCATION:-${SAVED_LOCATION:-southcentralus}}"
  VM_SIZE="${VM_SIZE:-${SAVED_VM_SIZE:-Standard_NC4as_T4_v3}}"
  EXTRA_HTTPS_CIDRS="${EXTRA_HTTPS_CIDRS-$SAVED_EXTRA_HTTPS_CIDRS}"
}

save_settings() {
  {
    printf 'SAVED_SUBSCRIPTION=%q\n' "$SUBSCRIPTION"
    printf 'SAVED_LOCATION=%q\n' "$LOCATION"
    printf 'SAVED_VM_SIZE=%q\n' "$VM_SIZE"
    printf 'SAVED_EXTRA_HTTPS_CIDRS=%q\n' "$EXTRA_HTTPS_CIDRS"
  } > "$SETTINGS"
}

require_subscription() {
  need az "https://learn.microsoft.com/cli/azure/install-azure-cli"
  [ -n "$SUBSCRIPTION" ] || die 'set AZURE_SUBSCRIPTION="<subscription name or id>" (remembered after the first up)'
  local name
  name="$(az account show --subscription "$SUBSCRIPTION" --query name -o tsv 2>/dev/null)" \
    || die "cannot use subscription '$SUBSCRIPTION' (run az login, or check the name)"
  SUBSCRIPTION="$(az account show --subscription "$SUBSCRIPTION" --query id -o tsv)"
  echo "==> Azure subscription: $name"
}

# JSON array from a comma-separated CIDR list; rejects anything but a.b.c.d/n.
cidr_json() {
  local out="" item
  local -a items=()
  IFS=',' read -ra items <<< "$1"
  for item in ${items[@]+"${items[@]}"}; do
    item="${item// /}"
    [ -z "$item" ] && continue
    [[ "$item" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}/[0-9]{1,2}$ ]] || die "not an IPv4 CIDR: '$item'"
    out="${out:+$out,}\"$item\""
  done
  printf '[%s]' "$out"
}

operator_ip() {
  local ip
  ip="$(curl -4 -fsS --max-time 10 https://api.ipify.org 2>/dev/null \
    || curl -4 -fsS --max-time 10 https://checkip.amazonaws.com 2>/dev/null)" || return 1
  ip="$(printf '%s' "$ip" | tr -d '[:space:]')"
  [[ "$ip" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || return 1
  printf '%s' "$ip"
}

tf() {
  need terraform "https://developer.hashicorp.com/terraform/install"
  if [ ! -d "$TF_DATA_DIR" ]; then
    terraform -chdir="$TF_DIR" init -input=false -backend-config="path=$STATE/terraform.tfstate" >/dev/null
  fi
  terraform -chdir="$TF_DIR" "$@"
}

load_outputs() {
  [ -s "$STATE/terraform.tfstate" ] || die "no deployment yet; run: scripts/azure-demo.sh up"
  FQDN="$(tf output -raw fqdn)"
  IP="$(tf output -raw public_ip)"
  ADMIN="$(tf output -raw admin_username)"
  RG="$(tf output -raw resource_group)"
  VM="$(tf output -raw vm_name)"
}

# Create or update the Azure resources. Terraform shows the plan and asks
# before changing anything unless AUTO_APPROVE=1.
apply_infra() {
  require_subscription
  save_settings
  need ssh-keygen "OpenSSH"
  [ -f "$KEY" ] || ssh-keygen -q -t ed25519 -N "" -C "contract-enclave-demo" -f "$KEY"
  local my_ip
  my_ip="$(operator_ip)" || die "could not detect this machine's public IPv4 address"
  cat > "$TFVARS" <<EOF
{
  "subscription_id": "$SUBSCRIPTION",
  "location": "$LOCATION",
  "vm_size": "$VM_SIZE",
  "ssh_public_key": "$(cat "$KEY.pub")",
  "operator_cidrs": ["$my_ip/32"],
  "extra_https_cidrs": $(cidr_json "$EXTRA_HTTPS_CIDRS")
}
EOF
  echo "==> Terraform: $VM_SIZE in $LOCATION; SSH+HTTPS from $my_ip/32${EXTRA_HTTPS_CIDRS:+; HTTPS also from $EXTRA_HTTPS_CIDRS}"
  if [ "${AUTO_APPROVE:-0}" = 1 ]; then
    tf apply -input=false -auto-approve -var-file="$TFVARS"
  else
    tf apply -var-file="$TFVARS"
  fi
  load_outputs
}

# ssh_base [ssh options...] destination [command]; ssh_vm [command]
ssh_base() {
  ssh -i "$KEY" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new \
    -o UserKnownHostsFile="$KNOWN_HOSTS" -o ConnectTimeout=10 -o ServerAliveInterval=30 "$@"
}
ssh_vm() { ssh_base "$ADMIN@$IP" "$@"; }

wait_ssh() {
  echo -n "    waiting for SSH"
  for ((attempt = 0; attempt < 60; attempt++)); do
    if ssh_base -o BatchMode=yes "$ADMIN@$IP" true >/dev/null 2>&1; then echo; return; fi
    echo -n "."
    sleep 5
  done
  echo
  die "VM did not accept SSH at $IP (if your public IP changed, run: scripts/azure-demo.sh up)"
}

# Tracked and unignored files only: no .git, reports, state, or local secrets.
sync_repo() {
  echo "==> Syncing this checkout to the VM (~/$REMOTE_REPO)"
  local -a tar_flags=()
  if tar --version 2>/dev/null | grep -qi bsdtar; then tar_flags=(--no-mac-metadata --no-xattrs); fi
  git -C "$REPO" ls-files -z --cached --others --exclude-standard \
    | while IFS= read -r -d '' f; do if [ -e "$f" ]; then printf '%s\0' "$f"; fi; done \
    | COPYFILE_DISABLE=1 tar ${tar_flags[@]+"${tar_flags[@]}"} --null -T - -czf - \
    | ssh_vm "mkdir -p ~/$REMOTE_REPO/reports && tar -xzf - -C ~/$REMOTE_REPO --warning=no-unknown-keyword"
}

host_setup() {
  echo "==> Host services (Docker, Ollama, Coder, Caddy; NVIDIA driver on GPU sizes)"
  local rc=0
  ssh_vm "sudo bash ~/$REMOTE_REPO/deploy/azure/host-setup.sh $ADMIN $FQDN" || rc=$?
  if [ "$rc" = 100 ]; then
    echo "==> Rebooting once to load the NVIDIA driver"
    ssh_vm "sudo systemctl reboot" >/dev/null 2>&1 || true
    sleep 30
    wait_ssh
    ssh_vm "sudo bash ~/$REMOTE_REPO/deploy/azure/host-setup.sh $ADMIN $FQDN"
  elif [ "$rc" != 0 ]; then
    die "host setup failed (exit $rc)"
  fi
}

coder_login() {
  if ssh_vm "coder whoami" >/dev/null 2>&1; then return; fi
  local email
  email="${CODER_ADMIN_EMAIL:-$(git config user.email || true)}"
  [ -n "$email" ] || die "set CODER_ADMIN_EMAIL for the Coder admin account"
  if [ ! -s "$PASSWORD_FILE" ]; then
    # Bounded read: `tr < /dev/urandom | head` dies of SIGPIPE under pipefail.
    (umask 077; head -c 48 /dev/urandom | base64 | LC_ALL=C tr -dc 'A-Za-z0-9' | cut -c1-24 > "$PASSWORD_FILE")
  fi
  echo "==> Coder admin login ($CODER_ADMIN, $email)"
  printf '%s\n%s\n' "$(cat "$PASSWORD_FILE")" "$email" \
    | ssh_vm "bash ~/$REMOTE_REPO/deploy/azure/coder-login.sh $CODER_ADMIN" >/dev/null \
    || die "Coder login on the VM failed"
}

workspace_up() {
  echo "==> Workspace '$WS'"
  ssh_vm "if coder show $WS >/dev/null 2>&1; then coder update $WS; else coder create $WS --template contract-workspace -y; fi"
  echo -n "    waiting for the workspace agent"
  ssh_vm "for i in \$(seq 60); do timeout 30 coder ssh $WS -- true >/dev/null 2>&1 && exit 0; printf .; sleep 5; done; exit 1" \
    || die "workspace agent did not connect"
  echo
}

# After a stop/start the VM boots with Coder believing the workspace is still
# running, but its container is gone. Restart it so the agent reconnects.
workspace_recover() {
  ssh_vm "for i in \$(seq 90); do curl -sf http://localhost:3000/healthz >/dev/null && break; sleep 2; done
    if ! docker ps --format '{{.Names}}' | grep -Eq '^coder-.+-$WS\$'; then
      echo '==> Restarting workspace $WS (its container did not survive the VM stop)'
      coder restart $WS -y
    fi"
  echo -n "    waiting for the workspace agent"
  ssh_vm "for i in \$(seq 60); do timeout 30 coder ssh $WS -- true >/dev/null 2>&1 && exit 0; printf .; sleep 5; done; exit 1" \
    || die "workspace agent did not connect"
  echo
}

# Load the model now so the first OCR call of the demo is not a cold start.
warm_model() {
  echo "==> Loading $MODEL"
  ssh_vm "curl -sf --max-time 600 http://localhost:11434/api/generate -d '{\"model\":\"$MODEL\",\"keep_alive\":\"24h\"}' >/dev/null && ollama ps"
}

external_checks() {
  local pass=0 fail=0 redirect
  ok() { echo "  PASS  $1"; pass=$((pass + 1)); }
  ko() { echo "  FAIL  $1"; fail=$((fail + 1)); }
  echo "== Public exposure (probed from this machine) =="
  for ((attempt = 0; attempt < 24; attempt++)); do
    curl -sf --max-time 10 "https://$FQDN/healthz" >/dev/null 2>&1 && break
    sleep 5
  done
  if curl -sf --max-time 10 "https://$FQDN/healthz" >/dev/null 2>&1; then
    ok "https://$FQDN serves Coder with a trusted certificate"
  else
    ko "https://$FQDN serves Coder with a trusted certificate"
  fi
  redirect="$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' --max-time 10 "http://$FQDN/" 2>/dev/null || true)"
  if [ "$redirect" = "308 https://$FQDN/" ]; then
    ok "port 80 only redirects to HTTPS"
  else
    ko "port 80 only redirects to HTTPS (got: ${redirect:-no answer})"
  fi
  if curl -s --max-time 5 "http://$IP:3000/healthz" >/dev/null 2>&1; then
    ko "raw Coder port 3000 is closed to the internet"
  else
    ok "raw Coder port 3000 is closed to the internet"
  fi
  if curl -s --max-time 5 "http://$IP:11434/api/version" >/dev/null 2>&1; then
    ko "Ollama port 11434 is closed to the internet"
  else
    ok "Ollama port 11434 is closed to the internet"
  fi
  echo "== Model placement =="
  local processor
  processor="$(ssh_vm "ollama ps" 2>/dev/null | awk -v m="$MODEL" '$1 == m { for (i = 1; i <= NF; i++) if ($i ~ /GPU|CPU/) { print $(i-1), $i; exit } }')"
  if ssh_vm "lspci | grep -qi nvidia" 2>/dev/null; then
    if [[ "$processor" == "100% GPU" ]]; then ok "$MODEL is loaded entirely on the GPU"; else ko "$MODEL is loaded entirely on the GPU (got: ${processor:-not loaded})"; fi
  else
    echo "  NOTE  CPU-only VM size: $MODEL runs on CPU (${processor:-not loaded}); expect minutes per page"
  fi
  echo
  echo "$pass passed, $fail failed"
  [ "$fail" -eq 0 ]
}

verify() {
  local rc=0
  echo "==> Enclave verification on the VM"
  ssh_vm "cd ~/$REMOTE_REPO && scripts/verify-enclave.sh $WS" || rc=1
  echo
  external_checks || rc=1
  return $rc
}

print_info() {
  local power
  power="$(az vm get-instance-view --subscription "$SUBSCRIPTION" -g "$RG" -n "$VM" \
    --query "instanceView.statuses[?starts_with(code,'PowerState/')].displayStatus | [0]" -o tsv 2>/dev/null || echo unknown)"
  cat <<EOF

Demo:        https://$FQDN
Login:       $CODER_ADMIN / password in $PASSWORD_FILE
Workspace:   $WS  (Coder UI -> $WS -> code-server; results under Reports)
VM:          $VM, $(tf output -raw vm_size), $power; auto-shutdown $(tf output -raw auto_shutdown)
SSH:         scripts/azure-demo.sh ssh
Stop billing for compute:  scripts/azure-demo.sh stop    (start: scripts/azure-demo.sh start)
Tear it all down:          scripts/azure-demo.sh down
EOF
}

cmd="${1:-}"
[ $# -gt 0 ] && shift
case "$cmd" in
  up)
    need ssh "OpenSSH"; need git "git"; need curl "curl"
    load_settings
    apply_infra
    wait_ssh
    ssh_vm "cloud-init status --wait" >/dev/null 2>&1 || true
    sync_repo
    host_setup
    coder_login
    echo "==> dev-up.sh on the VM (model, enclave network, image, gateways, template)"
    ssh_vm "cd ~/$REMOTE_REPO && scripts/dev-up.sh"
    workspace_up
    warm_model
    verify || echo "VERIFICATION FAILED -- see FAIL lines above"
    print_info
    ;;
  start)
    load_settings
    apply_infra      # refreshes the IP allowlist; no-op when nothing changed
    echo "==> Starting $VM"
    az vm start --subscription "$SUBSCRIPTION" -g "$RG" -n "$VM" -o none
    wait_ssh
    workspace_recover
    warm_model
    verify || echo "VERIFICATION FAILED -- see FAIL lines above"
    print_info
    ;;
  stop)
    load_settings; require_subscription; load_outputs
    echo "==> Deallocating $VM (disk and IP remain; compute billing stops)"
    az vm deallocate --subscription "$SUBSCRIPTION" -g "$RG" -n "$VM" -o none
    echo "    stopped. Resume with: scripts/azure-demo.sh start"
    ;;
  verify)
    load_settings; load_outputs
    verify
    ;;
  info)
    load_settings; load_outputs
    print_info
    ;;
  ssh)
    load_settings; load_outputs
    if [ $# -gt 0 ]; then ssh_vm "$@"; else ssh_base -t "$ADMIN@$IP"; fi
    ;;
  down)
    load_settings; require_subscription
    [ -f "$TFVARS" ] || die "no deployment settings found in $STATE"
    if [ "${AUTO_APPROVE:-0}" = 1 ]; then
      tf destroy -input=false -auto-approve -var-file="$TFVARS"
    else
      tf destroy -var-file="$TFVARS"
    fi
    # A re-created VM gets new host keys at the same address.
    rm -f "$KNOWN_HOSTS"
    echo "==> Destroyed. Local state (SSH key, admin password) remains in $STATE"
    ;;
  *)
    awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
    exit 2
    ;;
esac
