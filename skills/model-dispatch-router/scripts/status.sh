#!/bin/bash
# Exit codes: 0 done, 10 running/finalizing, 11 absent, 14 timeout, 17 quota,
# 20 budget, 21 missing result, 22 partial/blocked, 23 orphaned, 24 hook failure.
set -uo pipefail
[ "$#" -eq 1 ] || { echo 'usage: status.sh TASK' >&2; exit 1; }
REPO_ROOT="$(git rev-parse --show-toplevel)" || exit 1
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec node "$SCRIPT_DIR/lifecycle.js" status "$REPO_ROOT/.agent-logs" "$1"
