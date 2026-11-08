#!/usr/bin/env bash
# One-command Entire setup: make entire [AGENT=claude-code]. Safe to re-run. See docs/ENTIRE.md.
set -euo pipefail

ENTIRE_VERSION=0.13.1
AGENT=${AGENT:-claude-code}
export PATH="$HOME/.local/bin:$PATH"

if ! command -v entire >/dev/null; then
    echo "Installing Entire $ENTIRE_VERSION..."
    curl -fsSL https://entire.com/install.sh | bash -s -- --version "$ENTIRE_VERSION"
fi

entire enable --agent "$AGENT" --yes --project --telemetry=false

if ! entire plugin list | grep -qw graph; then
    entire plugin install graph
fi
entire graph setup --repo .

entire status
echo "Entire is ready. Add ~/.local/bin to your PATH if 'entire' isn't found in a new terminal."
