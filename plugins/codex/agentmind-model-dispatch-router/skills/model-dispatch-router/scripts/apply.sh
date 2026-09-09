#!/bin/bash
# Usage: apply.sh <task-slug> [--allow-extra path1,path2]; review diff.sh first.
# Exit: 11 missing worktree, 13 invalid scope, 16 collision/drift/apply failure.
#
# --allow-extra is a deliberate, ORCHESTRATOR-typed widening of scope for
# this one apply call — never something the dispatched agent can trigger.
# Use it when diff.sh's "OUT OF SCOPE" section shows a change you've reviewed
# and judge to be a necessary companion to the task (e.g. the test file a
# new function required) rather than scope creep; anything not listed here
# still gets refused. Every use is appended to
# .agent-logs/$TASK.scope-override for audit — this is a recorded exception
# to the manifest contract, not a silent bypass of it.
set -uo pipefail
TASK="${1:?Usage: apply.sh TASK [--allow-extra path1,path2]}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=dispatch-common.sh
source "$SCRIPT_DIR/dispatch-common.sh"
dispatch_common_valid_task_id "$TASK" || { echo "Invalid task identifier" >&2; exit 1; }
shift
EXTRA=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --allow-extra) EXTRA="${2:?error: --allow-extra needs a comma-separated path list}"; shift 2 ;;
    *) echo "error: unknown argument '$1'" >&2; exit 1 ;;
  esac
done
REPO_ROOT="$(git rev-parse --show-toplevel)" || exit 1
WORKTREE_DIR="$REPO_ROOT/.worktrees/$TASK"
LOG_DIR="$REPO_ROOT/.agent-logs"
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
if [ -n "$EXTRA" ]; then
  printf '%s allow-extra: %s\n' "$(date -u +%FT%TZ)" "$EXTRA" >> "$LOG_DIR/$TASK.scope-override"
  echo "orchestrator override: widening scope for this apply to include: $EXTRA (recorded in $LOG_DIR/$TASK.scope-override)" >&2
fi
node "$SCRIPT_DIR/snapshot.js" apply "$REPO_ROOT" "$WORKTREE_DIR" "$LOG_DIR/$TASK.scope" "$LOG_DIR/$TASK.snapshot.json" "$EXTRA" || exit $?
printf 'pending\n' > "$LOG_DIR/$TASK.gate-pending"
echo "Verification gate queued. Review the checkout and run verify.sh."
echo "This did NOT stage, commit, or push anything."
