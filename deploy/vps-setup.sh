#!/bin/bash
# One-time VPS prep (Ubuntu/Debian). Run as root: bash vps-setup.sh
set -euo pipefail
apt-get update && apt-get install -y ca-certificates curl git ufw
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
mkdir -p /opt/sinceai
echo "Done. Next: clone the repo into /opt/sinceai, create .env (with DOMAIN=...), run deploy."
