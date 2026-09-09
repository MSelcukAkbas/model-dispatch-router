#!/bin/bash
# Usage: apply.sh <task-slug>; review diff.sh first.
# Exit: 11 missing worktree, 13 invalid scope, 16 collision/drift/apply failure.
set -uo pipefail
TASK="${1:?Usage: apply.sh TASK}"
[[ "$TASK" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || { echo "Invalid task identifier" >&2; exit 1; }
REPO_ROOT="$(git rev-parse --show-toplevel)" || exit 1
WORKTREE_DIR="$REPO_ROOT/.worktrees/$TASK"
LOG_DIR="$REPO_ROOT/.agent-logs"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -d "$WORKTREE_DIR" ]; then
  if [ -f "$LOG_DIR/$TASK.meta" ] && grep -q '^no_worktree=1' "$LOG_DIR/$TASK.meta"; then
    echo "no_worktree: '$TASK' ran in the main checkout; changes are already in place."
    exit 0
  fi
  echo "not_found: no worktree for '$TASK'" >&2
  exit 11
fi
# One binary patch includes staged/unstaged edits, deletions AND new files.
# Check all scope, target drift and new-file collisions before writes.
if [ -f "$LOG_DIR/$TASK.meta" ] && grep -q '^snapshot=1$' "$LOG_DIR/$TASK.meta" && [ ! -s "$LOG_DIR/$TASK.snapshot.json" ]; then
  echo "refused: snapshot baseline is missing" >&2
  exit 16
fi
node "$SCRIPT_DIR/snapshot.js" apply "$REPO_ROOT" "$WORKTREE_DIR" "$LOG_DIR/$TASK.scope" "$LOG_DIR/$TASK.snapshot.json" || exit $?
printf 'pending\n' > "$LOG_DIR/$TASK.gate-pending"
echo "Verification gate queued. Review the checkout and run verify.sh."
echo "This did NOT stage, commit, or push anything."
