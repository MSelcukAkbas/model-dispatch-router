#!/bin/bash
# Usage: diff.sh <task-slug> [--allow-extra path1,path2]; exit 11 missing
# worktree, 13 invalid scope. Out-of-scope changes are always shown (in a
# separate section, never merged into the in-scope patch) so the orchestrator
# can review them without --allow-extra; that flag only affects whether
# apply.sh may later write them.
set -uo pipefail
TASK="${1:?Usage: diff.sh TASK [--allow-extra path1,path2]}"
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
source "$SCRIPT_DIR/scope.sh"
if [ ! -d "$WORKTREE_DIR" ]; then
  if [ -f "$LOG_DIR/$TASK.meta" ] && grep -q '^no_worktree=1' "$LOG_DIR/$TASK.meta"; then
    echo "no_worktree: '$TASK' ran directly in the main checkout."
    BASELINE="$LOG_DIR/$TASK.no-worktree-baseline"
    if [ ! -f "$BASELINE" ]; then
      echo "No dispatch-start baseline; showing current status."
      git -C "$REPO_ROOT" status --short
      exit 0
    fi
    CURRENT="$(scope_snapshot "$REPO_ROOT" "$LOG_DIR/$TASK.scope")"
    echo "== scoped changes since dispatch start ($TASK) =="
    diff -u "$BASELINE" <(printf '%s\n' "$CURRENT") || true
    echo "Shared checkout: changes cannot be attributed exclusively to this task."
    exit 0
  fi
  echo "not_found: no worktree for '$TASK'" >&2
  exit 11
fi
echo "== task patch ($TASK): staged, unstaged, binary and new files =="
if [ -f "$LOG_DIR/$TASK.meta" ] && grep -q '^snapshot=1$' "$LOG_DIR/$TASK.meta" && [ ! -s "$LOG_DIR/$TASK.snapshot.json" ]; then
  echo "refused: snapshot baseline is missing" >&2
  exit 16
fi
node "$SCRIPT_DIR/snapshot.js" diff "$REPO_ROOT" "$WORKTREE_DIR" "$LOG_DIR/$TASK.scope" "$LOG_DIR/$TASK.snapshot.json" "$EXTRA" || exit $?
