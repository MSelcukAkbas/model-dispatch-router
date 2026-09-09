#!/bin/bash
# Usage: wait.sh <task-id> [task-id2 ...]
#   env: WAIT_POLL_SECONDS (default 30)
#
# dispatch.sh backgrounds itself internally and returns in under a second —
# from the orchestrator's Bash-tool perspective that call already finished,
# so there is nothing to be notified about later, ever. "I'll get notified
# when it's done" was false: nothing was actually watching the task.
#
# This script IS something to watch: it blocks (polling status.sh) until
# every given task reaches a terminal state, then exits. Run it through the
# Bash tool with run_in_background:true right after dispatching — THAT
# gives a real completion notification, because the harness notifies on
# background Bash processes finishing, not on dispatch.sh's instant return.
#
# Exit code: 0 if ALL tasks finished with exit 0, 1 if any did not
# (check each task's own status.sh/collect.sh for which one and why —
# this script only tells you "done, go look").
set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$REPO_ROOT/.agent-logs"
POLL="${WAIT_POLL_SECONDS:-30}"

if [ "$#" -eq 0 ]; then
  echo "usage: wait.sh <task-id> [task-id2 ...]" >&2
  exit 1
fi

# Safety cap so this can't hang forever if a task's own `timeout` wrapper
# somehow never fires: max of each task's recorded timeout + 10min buffer,
# falling back to 40min for any task with no meta on record.
CAP_MIN=0
for T in "$@"; do
  T_CAP=40
  if [ -f "$LOG_DIR/$T.meta" ]; then
    META_TO="$(grep '^timeout_min=' "$LOG_DIR/$T.meta" | cut -d= -f2)"
    [ -n "$META_TO" ] && T_CAP=$((META_TO + 10))
  fi
  [ "$T_CAP" -gt "$CAP_MIN" ] && CAP_MIN=$T_CAP
done
DEADLINE=$(( $(date +%s) + CAP_MIN * 60 ))

REMAINING=("$@")
declare -A FINAL_CODE
declare -A FINAL_OUT

while [ "${#REMAINING[@]}" -gt 0 ]; do
  NEXT=()
  for T in "${REMAINING[@]}"; do
    OUT="$(bash "$SCRIPT_DIR/status.sh" "$T" 2>&1)"
    CODE=$?
    if [ "$CODE" = "10" ]; then
      NEXT+=("$T")
    else
      FINAL_CODE[$T]=$CODE
      FINAL_OUT[$T]="$OUT"
      echo "finished: $T -> $OUT"
    fi
  done
  REMAINING=("${NEXT[@]}")
  [ "${#REMAINING[@]}" -eq 0 ] && break
  if [ "$(date +%s)" -ge "$DEADLINE" ]; then
    echo "wait_cap_exceeded: still waiting on [${REMAINING[*]}] after ${CAP_MIN}m — their own timeout wrapper should have ended them by now, check manually (status.sh/list.sh)." >&2
    for T in "${REMAINING[@]}"; do
      FINAL_CODE[$T]=1
    done
    break
  fi
  sleep "$POLL"
done

echo "== all $# task(s) reached a terminal state =="
FAIL=0
for T in "$@"; do
  [ "${FINAL_CODE[$T]:-1}" != "0" ] && FAIL=1
done
exit $FAIL
