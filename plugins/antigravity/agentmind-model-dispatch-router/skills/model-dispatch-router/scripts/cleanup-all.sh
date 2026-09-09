#!/bin/bash
# Usage: cleanup-all.sh --yes <task-id> [task-id2 ...]
#        cleanup-all.sh --applied --yes
#        cleanup-all.sh <task-id> [task-id2 ...]   (dry-run: lists only, no --yes)
#
# Bulk version of cleanup.sh — one call instead of N. DESTRUCTIVE (removes
# worktrees, local branches, .agent-logs artifacts) — same rule as
# cleanup.sh: only after apply.sh (or discarding), and only after the USER
# has confirmed. Never call this from inside a dispatched agent's own run.
#
# No interactive y/N prompt — this runs through a non-interactive Bash tool
# call with no TTY attached, so a `read` prompt would just hang or silently
# read EOF. Confirmation is the ORCHESTRATOR's job (ask the user in chat,
# same as any other destructive git action), THEN pass --yes. Without
# --yes this only lists what it would remove and exits 1 — safe to run
# any time just to preview.
#
# --applied: instead of naming tasks, targets every task whose worktree has
# ZERO uncommitted diff (i.e. apply.sh already copied everything out, or
# there was never anything to apply) — the common "I just committed N
# applied tasks, sweep them all" case. Still requires --yes to actually act.
set -uo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$REPO_ROOT/.agent-logs"

YES=0
ARGS=()
for a in "$@"; do
  if [ "$a" = "--yes" ]; then
    YES=1
  else
    ARGS+=("$a")
  fi
done
set -- "${ARGS[@]}"

if [ "${1:-}" = "--applied" ]; then
  TASKS=()
  for wt in "$REPO_ROOT"/.worktrees/*/; do
    [ -d "$wt" ] || continue
    T="$(basename "$wt")"
    BRANCH="agent/$T"
    # Uncommitted/uncommitted-relative-to-branch-point diff still in the
    # worktree? If apply.sh hasn't run (or found conflicts), skip it —
    # cleaning it now would silently discard unapplied work.
    if [ -n "$(git -C "$wt" status --porcelain 2>/dev/null)" ]; then
      continue
    fi
    # Branch's own commits (it has none — dispatched agents never commit,
    # see the skill's core rule) plus worktree being clean is as much
    # "safe to remove" signal as this script can get without knowing
    # whether YOU actually ran apply.sh yet — that's still on you to have
    # verified via diff.sh/git log before running this flag.
    TASKS+=("$T")
  done
  if [ "${#TASKS[@]}" -eq 0 ]; then
    echo "no worktrees with a clean (fully-applied-or-untouched) tree found."
    exit 0
  fi
else
  TASKS=("$@")
fi

if [ "${#TASKS[@]}" -eq 0 ]; then
  echo "usage: cleanup-all.sh [--yes] <task-id> [task-id2 ...]  |  cleanup-all.sh [--yes] --applied" >&2
  exit 1
fi

echo "Worktree + branch + logs for ${#TASKS[@]} task(s):"
for T in "${TASKS[@]}"; do
  echo "  - $T (worktree:$([ -d "$REPO_ROOT/.worktrees/$T" ] && echo yes || echo no), branch:agent/$T)"
done

if [ "$YES" != "1" ]; then
  echo "dry-run: nothing removed (no --yes). Confirm with the user, then re-run with --yes." >&2
  exit 1
fi

for T in "${TASKS[@]}"; do
  bash "$SCRIPT_DIR/cleanup.sh" "$T"
done
