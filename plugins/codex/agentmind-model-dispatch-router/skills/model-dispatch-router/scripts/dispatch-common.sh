#!/bin/bash
# Shared helpers between dispatch.sh (Claude) and dispatch-agy.sh (agy) —
# only the parts that are genuinely identical text, not a forced merge of the
# two engines. Each engine's account/quota/budget/MCP/session machinery stays
# in its own script because the other engine has no equivalent for most of it
# (verified live against `agy --help` — see dispatch-agy.sh's header comment).
# Both callers already `source scope.sh` before this file for the
# scope_normalize_entry/scope_reserve primitives used below.

# dispatch_common_require_goal PROMPT_FILE CONTEXT_NOTE
# Prints the '# GOAL:' line to stdout, or prints an error to stderr and
# returns 1. CONTEXT_NOTE is appended to the error so each caller keeps its
# own reasoning (dispatch.sh: no back-and-forth is impossible mid-run for
# agy either, but the two personas explain it differently to the model).
dispatch_common_require_goal() {
  local prompt_file="$1" context_note="$2" goal_line
  goal_line="$(grep -m1 '^# GOAL:' "$prompt_file" || true)"
  if [ -z "$goal_line" ]; then
    echo "error: prompt file must start with a '# GOAL: <one sentence>' header — exactly one objective${context_note:+, $context_note}." >&2
    return 1
  fi
  printf '%s\n' "$goal_line"
}

# dispatch_common_ensure_worktree REPO_ROOT WORKTREE_DIR BRANCH
# Reuses an existing worktree (logs a note) or creates one from HEAD. Callers
# choose their own exit code on failure (dispatch.sh uses 1, dispatch-agy.sh
# uses 11) since the two scripts document different codes to their callers.
dispatch_common_ensure_worktree() {
  local repo_root="$1" worktree_dir="$2" branch="$3"
  if [ -d "$worktree_dir" ]; then
    echo "note: worktree $worktree_dir already exists — reusing." >&2
    return 0
  fi
  if ! git -C "$repo_root" worktree add -b "$branch" "$worktree_dir" HEAD; then
    echo "error: git worktree add failed for branch '$branch' (may already exist — check 'git branch -a' / 'git worktree list', likely a prior run's leftover; cleanup.sh removes both). Refusing to silently fall back to the main checkout for a role that expects isolation." >&2
    return 1
  fi
}

# dispatch_common_build_scope LOG_DIR TASK SCRIPT_DIR FILES_VALUE
# FILES_VALUE is the '# FILES:' header with the 'FILES:' prefix already
# stripped. Writes the normalized, sorted manifest to $LOG_DIR/$TASK.scope
# and reserves it against other in-flight tasks via scope_reserve (which
# already covers launch-locked and orphaned owners — this is the ONLY
# cross-task scope check; there used to be a second, weaker one duplicated
# in dispatch.sh that only looked at state 10, see removal note in
# dispatch.sh's git history). Returns scope_reserve's exit code on conflict
# (12), or 1 if the header contained no valid entry.
dispatch_common_build_scope() {
  local log_dir="$1" task="$2" script_dir="$3" files_value="$4"
  local scope_tmp entry normalized
  scope_tmp="$(mktemp)"
  local entries=()
  IFS=',' read -ra entries <<< "$files_value"
  for entry in "${entries[@]}"; do
    entry="$(printf '%s' "$entry" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    normalized="$(scope_normalize_entry "$entry")" || { rm -f "$scope_tmp"; echo "error: invalid # FILES scope entry '$entry'" >&2; return 1; }
    echo "$normalized" >> "$scope_tmp"
  done
  if [ ! -s "$scope_tmp" ]; then
    rm -f "$scope_tmp"
    echo "error: # FILES: header produced no valid scope entries" >&2
    return 1
  fi
  sort -u "$scope_tmp" > "$log_dir/$task.scope"
  rm -f "$scope_tmp"
  scope_reserve "$log_dir" "$task" "$script_dir"
}

# dispatch_common_valid_task_id TASK
# The one task-id shape, used everywhere. Previously duplicated across six
# scripts as two DIFFERENT patterns — dispatch_bootstrap (runtime.sh, the
# only place a task-id is ever actually minted) enforced this strict one,
# while diff.sh/apply.sh independently wrote a looser one that also allowed
# dots and unbounded length, accepting task-ids no real dispatch could ever
# produce. Not a live security hole (lifecycle.js's own path-building has its
# own independent traversal check), but needless drift for the same concept —
# every real task-id on disk is `T-NNNNNN` or a hand-picked slug, never a dot.
dispatch_common_valid_task_id() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$ ]]
}

# dispatch_common_archive_stale LOG_DIR TASK EXT...
# Moves any leftover artifact from a prior attempt at the same task-id out of
# the way before relaunching, so status.sh/get_result never read a dead run's
# output as if it belonged to the new one (2026-07-27/07-30 fixes — see
# dispatch.sh's "Stale-artifact guard" comment for the incident this
# prevents). Each caller passes only the extensions it actually produces.
dispatch_common_archive_stale() {
  local log_dir="$1" task="$2" ts ext
  shift 2
  ts="$(date +%s)"
  for ext in "$@"; do
    [ -f "$log_dir/$task.$ext" ] && mv "$log_dir/$task.$ext" "$log_dir/$task.$ext.prev-$ts"
  done
  return 0
}
