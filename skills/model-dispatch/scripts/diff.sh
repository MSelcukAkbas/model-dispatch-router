#!/bin/bash
# Usage: diff.sh <task-slug>
# Exit codes: 0 ok | 11 worktree not found
set -uo pipefail
TASK="$1"
REPO_ROOT="$(git rev-parse --show-toplevel)"
WORKTREE_DIR="$REPO_ROOT/.worktrees/$TASK"
LOG_DIR="$REPO_ROOT/.agent-logs"

if [ ! -d "$WORKTREE_DIR" ]; then
  if [ -f "$LOG_DIR/$TASK.meta" ] && grep -q '^no_worktree=1' "$LOG_DIR/$TASK.meta"; then
    echo "no_worktree: task '$TASK' ran directly in the main checkout (dispatch.sh no-worktree=1) — there is no separate worktree copy to diff."
    echo "Any changes it made are already live on disk. Review directly, e.g.:"
    echo "  git -C \"$REPO_ROOT\" status --short          (main-repo-tracked files)"
    echo "  Inspect the target repository directly; this task ran without a worktree."
    exit 0
  fi
  echo "not_found: no worktree for task '$TASK' at $WORKTREE_DIR" >&2
  exit 11
fi

echo "== git status ($TASK) =="
git -C "$WORKTREE_DIR" status --short
echo
echo "== git diff ($TASK) =="
git -C "$WORKTREE_DIR" diff
exit 0
