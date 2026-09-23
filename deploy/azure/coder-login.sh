#!/usr/bin/env bash
# Logs the VM admin's Coder CLI in to the local Coder server, creating the
# first (admin) user on a fresh deployment. dev-up.sh needs this session to
# push the template. Runs on the VM as the admin user; scripts/azure-demo.sh
# pipes the password and email on stdin so neither appears on a command line.
#   printf '%s\n%s\n' "$password" "$email" | deploy/azure/coder-login.sh <username>
set -euo pipefail
USERNAME="$1"
IFS= read -r PASSWORD
IFS= read -r EMAIL
URL=http://localhost:3000

if curl -sf "$URL/api/v2/users/first" >/dev/null; then
  # Deployment already has its admin: exchange the saved password for a token.
  TOKEN="$(EMAIL="$EMAIL" PASSWORD="$PASSWORD" python3 -c '
import json, os, sys, urllib.request
body = json.dumps({"email": os.environ["EMAIL"], "password": os.environ["PASSWORD"]}).encode()
req = urllib.request.Request(sys.argv[1] + "/api/v2/users/login", data=body,
                             headers={"Content-Type": "application/json"})
print(json.load(urllib.request.urlopen(req))["session_token"])
' "$URL")"
  CODER_SESSION_TOKEN="$TOKEN" coder login "$URL" >/dev/null
else
  CODER_FIRST_USER_PASSWORD="$PASSWORD" coder login "$URL" \
    --first-user-username "$USERNAME" --first-user-email "$EMAIL" \
    --first-user-full-name "Demo Admin" --first-user-trial=false >/dev/null
fi
coder whoami
