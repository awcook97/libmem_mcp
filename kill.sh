#!/usr/bin/env bash
# kill.sh — emergency hard kill.
#
# Sets the kill bit (drops all future AI input immediately) then kills the
# daemon process. Two-stage so input is cut even before the process dies.
#
# Usage:
#   ./kill.sh           # hard kill (bit + kill daemon)
#   ./kill.sh --soft    # soft kill (bit only, daemon stays up)
#   ./kill.sh --clear   # clear the kill bit (re-enables AI input)

set -euo pipefail

KILL_BIT="${GAMEINPUT_KILL_BIT:-/tmp/SHUTDOWN_AI}"

case "${1:-}" in
  --clear)
    rm -f "$KILL_BIT"
    echo "Kill bit cleared. AI input re-enabled."
    ;;
  --soft)
    touch "$KILL_BIT"
    echo "Kill bit SET. All AI input blocked. Daemon still running."
    echo "Run './kill.sh --clear' to re-enable."
    ;;
  *)
    touch "$KILL_BIT"
    echo "Kill bit SET."
    pkill -f "gameinput.daemon" 2>/dev/null || pkill -f "gameinput-daemon" 2>/dev/null || true
    echo "gameinput-daemon killed."
    ;;
esac
chmod +w .gameinput/config.json  # allow edits again after killing
chmod +w kill.sh # allow edits again after killing
chmod +w start.sh # allow edits again after killing
chmod +x kill.sh start.sh # make sure they're executable