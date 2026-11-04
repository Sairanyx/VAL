#!/bin/bash
# From your laptop: ./deploy/deploy.sh   (set VPS=user@host in .env or env)
set -euo pipefail
VPS=${VPS:?set VPS=user@host}
ssh "$VPS" 'cd /opt/sinceai && git pull && docker compose -f compose.prod.yaml up -d --build && docker compose -f compose.prod.yaml ps'
