#!/bin/bash
# Usage: apply.sh <task-slug>
# Exit codes: 0 ok | 11 worktree not found | 16 patch failed to apply (nothing written)
# Copies the dispatched agent's uncommitted worktree changes (tracked edits +
# new untracked files) into the main checkout's working tree. Does NOT stage,
# commit, or push. Review with diff.sh BEFORE running this.
set -uo pipefail
TASK="$1"
REPO_ROOT="$(git rev-parse --show-toplevel)"
WORKTREE_DIR="$REPO_ROOT/.worktrees/$TASK"
LOG_DIR="$REPO_ROOT/.agent-logs"

if [ ! -d "$WORKTREE_DIR" ]; then
  if [ -f "$LOG_DIR/$TASK.meta" ] && grep -q '^no_worktree=1' "$LOG_DIR/$TASK.meta"; then
    echo "no_worktree: task '$TASK' ran directly in the main checkout (dispatch.sh no-worktree=1) — nothing to apply, its changes are already in place."
    exit 0
  fi
  echo "not_found: no worktree for task '$TASK' at $WORKTREE_DIR" >&2
  exit 11
fi

PATCH_FILE="$(mktemp)"
git -C "$WORKTREE_DIR" diff > "$PATCH_FILE"
if [ -s "$PATCH_FILE" ]; then
  # `git apply` is all-or-nothing across every file in the patch — if ANY file's
  # hunks fail to match (e.g. that file was independently edited in the main
  # checkout since this worktree branched), the WHOLE patch is rejected and NOT
  # ONE byte is written, even for files that would have applied cleanly. Must
  # check the exit code explicitly: with only `set -uo pipefail` (no `-e`), a
  # failed `git apply` does not stop the script, so the fixed "Applied..."
  # message below would print unconditionally — a false success report over a
  # no-op. (Found 2026-07-13: this silently dropped an entire dispatched task's
  # changes while reporting success; caught only by re-grepping for expected
  # content in the "applied" files.)
  if ! git -C "$REPO_ROOT" apply "$PATCH_FILE" 2>"$PATCH_FILE.err"; then
    echo "FAILED: patch from '$TASK' did not apply — repo unchanged (all-or-nothing)." >&2
    cat "$PATCH_FILE.err" >&2
    echo "Likely cause: a file this task touched was independently modified in the main checkout since the worktree branched." >&2
    echo "Fix manually: inspect diff.sh $TASK, then either hand-merge the conflicting file(s) or resolve the base drift and retry." >&2
    rm -f "$PATCH_FILE" "$PATCH_FILE.err"
    exit 16
  fi
  rm -f "$PATCH_FILE.err"
  echo "Applied tracked-file changes from $TASK."
else
  echo "No tracked-file changes to apply for $TASK."
fi
rm -f "$PATCH_FILE"

# --untracked-files=all: plain `--porcelain` collapses a new directory into a
# single `?? dir/` line — `cp` (no -r) on that silently no-ops (found 2026-07-14:
# a new component file was dropped this way while the script printed "Copied new
# file", a false success identical in spirit to the git-apply bug above). `=all`
# lists every file inside individually, so each `cp` target is always a real file.
UNTRACKED="$(git -C "$WORKTREE_DIR" status --porcelain --untracked-files=all | grep '^??' | cut -c4- || true)"
if [ -n "$UNTRACKED" ]; then
  while IFS= read -r f; do
    mkdir -p "$REPO_ROOT/$(dirname "$f")"
    if cp "$WORKTREE_DIR/$f" "$REPO_ROOT/$f"; then
      echo "Copied new file: $f"
    else
      echo "FAILED to copy new file: $f" >&2
      exit 1
    fi
  done <<< "$UNTRACKED"
else
  echo "No new untracked files for $TASK."
fi

echo
echo "Done. Review with: git -C \"$REPO_ROOT\" status --short"
echo "This did NOT stage, commit, or push anything."
exit 0
