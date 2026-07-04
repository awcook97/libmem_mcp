#!/usr/bin/env bash
# start.sh — launch gameinput-daemon (the kill switch).
#
# VS Code spawns libmem-mcp and gameinput-mcp automatically via .vscode/mcp.json.
# You only need to run this. Ctrl+C = AI cannot send any input.

set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  cat <<'EOF'
Usage: ./start.sh [OPTIONS]

Starts gameinput-daemon — the HTTP input bridge that the gameinput-mcp MCP
server talks to. Run this in your terminal before asking the AI to do anything.
Ctrl+C here = kill switch (AI gets connection refused on every input call).

Options are forwarded to gameinput-daemon:
EOF
  exec uv run gameinput-daemon --help
fi
chmod -w .gameinput/config.json  # prevent accidental edits to config while running
chmod -w kill.sh # stop the rogue AI from being stupid and deleting the kill script
chmod -w start.sh # stop the rogue AI from being stupid and deleting the start script
chmod +x kill.sh start.sh # make sure they're executable

exec uv run gameinput-daemon "$@"
