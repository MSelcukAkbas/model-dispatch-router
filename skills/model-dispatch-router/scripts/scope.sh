#!/bin/bash
# Shared scope-manifest helpers for dispatch.sh, diff.sh and apply.sh.
# A scope entry is either an exact repository-relative path or a directory
# prefix ending in '/'.  The manifest is deliberately simple, reviewable text:
# one normalized entry per line.

scope_normalize_entry() {
  local value="$1"
  value="$(printf '%s' "$value" | tr '\\' '/')"
  value="${value#./}"
  if [ -z "$value" ] || [[ "$value" = *:* ]] || [[ "$value" = /* ]] || [[ "$value" = *"//"* ]] || [[ "/$value/" = *"/../"* ]] || [[ "/$value/" = *"/./"* ]] || [[ "${value,,}" = .git* ]] || [[ "/${value,,}/" = *"/.git/"* ]]; then
    return 1
  fi
  printf '%s\n' "$value"
}

scope_is_allowed() {
  local manifest="$1" path="$2" entry
  [ -f "$manifest" ] || return 1
  while IFS= read -r entry; do
    [ -n "$entry" ] || continue
    if [ "$path" = "$entry" ] || { [[ "$entry" = */ ]] && [[ "$path" = "$entry"* ]]; }; then
      return 0
    fi
  done < "$manifest"
  return 1
}

scope_entries_overlap() {
  local left="$1" right="$2"
  [ "$left" = "$right" ] && return 0
  [[ "$left" = */ ]] && [[ "$right" = "$left"* ]] && return 0
  [[ "$right" = */ ]] && [[ "$left" = "$right"* ]] && return 0
  return 1
}

scope_reserve() {
  local logs="$1" task="$2" scripts="$3" other other_task state mine theirs
  for other in "$logs"/*.scope; do
    [ -f "$other" ] || continue
    other_task="$(basename "$other" .scope)"
    [ "$other_task" != "$task" ] || continue
    state=11
    if [ -d "$logs/$other_task.launch-lock" ]; then
      state=10
    else
      node "$scripts/lifecycle.js" status "$logs" "$other_task" >/dev/null 2>&1
      state=$?
    fi
    # A crashed owner is not proof that its descendants stopped writing.
    [ "$state" = 10 ] || [ "$state" = 23 ] || continue
    while IFS= read -r mine; do
      while IFS= read -r theirs; do
        if scope_entries_overlap "$mine" "$theirs"; then
          echo "refused: scope '$mine' overlaps active or orphaned task '$other_task'" >&2
          return 12
        fi
      done < "$other"
    done < "$logs/$task.scope"
  done
}

scope_snapshot() {
  # Prints "<blob-hash>  <path>" for every file the scope manifest currently
  # matches, tracked or untracked, sorted by path. Used to baseline a
  # no-worktree task's scope at dispatch start and to re-measure it later —
  # diffing two snapshots (rather than just reading "git status" at the end)
  # is what lets a no-worktree report say WHICH scoped paths actually moved,
  # since there is no isolated worktree copy to `git diff` against.
  local repo_root="$1" manifest="$2"
  [ -s "$manifest" ] || return 0
  local specs=()
  while IFS= read -r entry; do
    [ -n "$entry" ] && specs+=("$entry")
  done < "$manifest"
  [ "${#specs[@]}" -gt 0 ] || return 0
  { git -C "$repo_root" ls-files -- "${specs[@]}"
    git -C "$repo_root" ls-files --others --exclude-standard -- "${specs[@]}"
  } | sort -u | while IFS= read -r path; do
    [ -f "$repo_root/$path" ] || continue
    printf '%s  %s\n' "$(git -C "$repo_root" hash-object "$path")" "$path"
  done
}

scope_assert_paths() {
  local manifest="$1" path failed=0
  if [ ! -s "$manifest" ]; then
    echo "refused: missing or empty scope manifest '$manifest'. Re-dispatch with a non-empty # FILES: header." >&2
    return 13
  fi
  while IFS= read -r path; do
    [ -n "$path" ] || continue
    if ! scope_is_allowed "$manifest" "$path"; then
      echo "scope_violation: '$path' is outside the task manifest ($manifest)." >&2
      failed=1
    fi
  done
  [ "$failed" = 0 ] || return 13
}
