#!/bin/bash
# Usage: cleanup.sh <task-slug>
# Removes a task's worktree and local branch, and its logs. DESTRUCTIVE —
# only run this after apply.sh (or after deciding to discard the task's
# output) and after confirming with the user, same as any other destructive
# git operation. Never call this from inside a dispatched agent's own run.
set -euo pipefail
TASK="$1"
SCRIPT_DIR_EARLY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=dispatch-common.sh
source "$SCRIPT_DIR_EARLY/dispatch-common.sh"
dispatch_common_valid_task_id "$TASK" || { echo "error: invalid task identifier" >&2; exit 1; }
REPO_ROOT="$(git rev-parse --show-toplevel)"
WORKTREE_DIR="$REPO_ROOT/.worktrees/$TASK"
BRANCH="agent/$TASK"
LOG_DIR="$REPO_ROOT/.agent-logs"

# A dirty-snapshot baseline is deliberately pinned under refs/agentmind so
# Git pruning cannot erase a reviewable patch. Release only while destroying
# the corresponding task record.
if [ -f "$LOG_DIR/$TASK.snapshot.json" ]; then
  SNAPSHOT_REF="$(node -e 'try { console.log(JSON.parse(require("fs").readFileSync(process.argv[1], "utf8")).ref || "") } catch {}' "$LOG_DIR/$TASK.snapshot.json")"
  [[ "$SNAPSHOT_REF" =~ ^refs/agentmind/snapshots/[a-f0-9]{64}$ ]] && git -C "$REPO_ROOT" update-ref -d "$SNAPSHOT_REF" || true
fi

git -C "$REPO_ROOT" worktree remove --force "$WORKTREE_DIR" 2>/dev/null || echo "Worktree already gone or not found."
git -C "$REPO_ROOT" branch -D "$BRANCH" 2>/dev/null || echo "Branch already gone or not found."
# Glob (not a fixed list) so this also catches artifacts added after this
# script was first written — .meta/.files/.prompt.orig/.prompt.tmp, and any
# *.prev-<timestamp> archives resume.sh leaves behind. Safe: task-ids never
# contain a literal '.', so "$TASK".* can't accidentally prefix-match a
# different task's files (e.g. "fe-1".* does not match "fe-171.json").
rm -f "$LOG_DIR/$TASK".*
rmdir "$LOG_DIR/runtimes/$TASK"/* 2>/dev/null || rm -rf "$LOG_DIR/runtimes/$TASK"
rmdir "$LOG_DIR/runtimes" 2>/dev/null || true
echo "Cleaned up task '$TASK' (worktree, branch, all .agent-logs/$TASK.* artifacts)."
