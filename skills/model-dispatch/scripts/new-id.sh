#!/bin/bash
# Usage: new-id.sh
# Allocates and prints the next T-NNNNNN task ID. Only use this for ad-hoc
# work with no existing ticket — if the task closes a KYC-/FE-/PLT-/SDK-
# ticket, use that ticket ID as the task-id instead (it's already the
# project's immutable identifier, no need for a second ID space).
set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel)"
COUNTER_FILE="$REPO_ROOT/.agent-logs/.task-counter"
mkdir -p "$REPO_ROOT/.agent-logs"

if [ ! -f "$COUNTER_FILE" ]; then
  echo "0" > "$COUNTER_FILE"
fi

N="$(cat "$COUNTER_FILE")"
N=$((N + 1))
echo "$N" > "$COUNTER_FILE"

printf "T-%06d\n" "$N"
