#!/bin/bash
# Stable recovery entry point: task.sh status|collect|wait|diff|apply|resume TASK [args]
set -uo pipefail
ACTION="${1:-}" TASK="${2:-}"
case "$ACTION" in status|collect|wait|diff|apply|resume) ;; *) echo 'usage: task.sh status|collect|wait|diff|apply|resume TASK [args]' >&2; exit 1 ;; esac
[[ "$TASK" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$ ]] || exit 1
shift 2
ROOT="$(git rev-parse --show-toplevel)" || exit 1
RUNTIME="$(cat "$ROOT/.agent-logs/$TASK.runtime" 2>/dev/null)"
if [ -n "$RUNTIME" ] && [ -f "$RUNTIME/scripts/$ACTION.sh" ]; then
  exec bash "$RUNTIME/scripts/$ACTION.sh" "$TASK" "$@"
fi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/$ACTION.sh" "$TASK" "$@"
