#!/bin/bash
# Bootstrap before touching task artifacts. Runtime bundles survive plugin updates.
# shellcheck source=dispatch-common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/dispatch-common.sh"
dispatch_bootstrap() {
  local entry="$1" task="$2"; shift 2
  dispatch_common_valid_task_id "$task" || { echo 'error: invalid task ID' >&2; exit 1; }
  [ "${DISPATCH_PINNED_TASK:-}" = "$task" ] && return 0
  local root logs source_dir runtime rc
  root="$(git rev-parse --show-toplevel)" || exit 1
  logs="$root/.agent-logs"
  source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  mkdir -p "$logs" || exit 1
  # Atomic, shared by both engines; held through preflight and launch.
  mkdir "$logs/$task.launch-lock" 2>/dev/null || { echo "refused: task launch lock exists for $task; inspect its owner before recovery" >&2; exit 12; }
  trap 'rmdir "$logs/$task.launch-lock" 2>/dev/null || true' EXIT
  if [ -f "$logs/$task.run.json" ] || [ -f "$logs/$task.pid" ] || [ -f "$logs/$task.agy.pid" ]; then
    node "$source_dir/scripts/lifecycle.js" status "$logs" "$task" >/dev/null
    rc=$?
    if [ "$rc" = 10 ]; then echo "refused: task $task is running" >&2; exit 12; fi
  fi
  runtime="$(node "$source_dir/scripts/runtime.js" "$source_dir" "$logs" "$task")" || exit 1
  # Registry stays local; never bundle credentials into task runtime snapshots.
  export DISPATCH_ACCOUNT_SOURCE="$source_dir/scripts"
  export DISPATCH_PINNED_TASK="$task"
  bash "$runtime/scripts/$entry" "$@"
  rc=$?
  exit "$rc"
}
