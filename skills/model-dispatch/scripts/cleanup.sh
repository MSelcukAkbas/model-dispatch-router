#!/bin/bash
# Usage: cleanup.sh <task-slug>
# Removes a task's worktree and local branch, and its logs. DESTRUCTIVE —
# only run this after apply.sh (or after deciding to discard the task's
# output) and after confirming with the user, same as any other destructive
# git operation. Never call this from inside a dispatched agent's own run.
set -euo pipefail
TASK="$1"
REPO_ROOT="$(git rev-parse --show-toplevel)"
WORKTREE_DIR="$REPO_ROOT/.worktrees/$TASK"
BRANCH="agent/$TASK"
LOG_DIR="$REPO_ROOT/.agent-logs"

git -C "$REPO_ROOT" worktree remove --force "$WORKTREE_DIR" 2>/dev/null || echo "Worktree already gone or not found."
git -C "$REPO_ROOT" branch -D "$BRANCH" 2>/dev/null || echo "Branch already gone or not found."
# Glob (not a fixed list) so this also catches artifacts added after this
# script was first written — .meta/.files/.prompt.orig/.prompt.tmp, and any
# *.prev-<timestamp> archives resume.sh leaves behind. Safe: task-ids never
# contain a literal '.', so "$TASK".* can't accidentally prefix-match a
# different task's files (e.g. "fe-1".* does not match "fe-171.json").
rm -f "$LOG_DIR/$TASK".*
echo "Cleaned up task '$TASK' (worktree, branch, all .agent-logs/$TASK.* artifacts)."
