#!/bin/bash
# Usage: list.sh
# Shows every dispatched task this repo knows about (from .agent-logs/), with
# status and dispatch time. Prevents losing track of an in-flight or
# forgotten dispatch (happened once this session with a manually-run batch).
set -uo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$REPO_ROOT/.agent-logs"

if [ ! -d "$LOG_DIR" ]; then
  echo "No dispatched tasks recorded."
  exit 0
fi

printf "%-24s %-20s %-8s %-20s %-10s %s\n" "TASK" "STATUS" "PID" "DISPATCHED_AT" "ACCOUNT" "WORKTREE"
shopt -s nullglob
declare -A SEEN_TASKS
for pidfile in "$LOG_DIR"/*.pid "$LOG_DIR"/*.run.json "$LOG_DIR"/*.exitcode "$LOG_DIR"/*.final-status.json; do
  TASK="$(basename "$pidfile")"
  TASK="${TASK%.final-status.json}"; TASK="${TASK%.run.json}"
  TASK="${TASK%.exitcode}"; TASK="${TASK%.pid}"; TASK="${TASK%.agy}"
  [ -n "${SEEN_TASKS[$TASK]:-}" ] && continue
  SEEN_TASKS[$TASK]=1
  PID="$(cat "$LOG_DIR/$TASK.pid" 2>/dev/null || cat "$LOG_DIR/$TASK.agy.pid" 2>/dev/null || echo '?')"
  WORKTREE="$REPO_ROOT/.worktrees/$TASK"
  ACCOUNT="$(grep '^account=' "$LOG_DIR/$TASK.meta" 2>/dev/null | cut -d= -f2)"
  [ -f "$LOG_DIR/$TASK.agy.meta" ] && ACCOUNT="agy"
  [ -z "$ACCOUNT" ] && ACCOUNT="current-claude-session"

  # Reuse status.sh's own classification (2026-07-30 fix — H7) instead of
  # re-implementing exitcode/.err parsing here — the old inline version
  # didn't know about budget_capped (exit 20), so a task that hit its
  # --max-budget-usd cap showed up here as a generic "failed(N)" while
  # status.sh (and resume.sh, which trusts status.sh) correctly called it
  # out as resumable. Two tools disagreeing on the same task's state is
  # exactly the kind of thing that leads to wrong triage.
  STATUS_OUT="$(bash "$SCRIPT_DIR/status.sh" "$TASK" 2>&1)"
  STATUS_CODE=$?
  case "$STATUS_CODE" in
    0) STATUS="done(0)" ;;
    10) STATUS="running" ;;
    14) STATUS="timeout(124)" ;;
    17) STATUS="quota_out(resume.sh)" ;;
    20) STATUS="budget_capped(resume.sh)" ;;
    21) STATUS="result_missing" ;;
    22) STATUS="partial/blocked" ;;
    23) STATUS="orphaned" ;;
    24) STATUS="hook_incomplete" ;;
    11) STATUS="not_found" ;;
    *) STATUS="failed($STATUS_CODE)" ;;
  esac

  DISPATCHED_AT="$(date -r "$pidfile" '+%Y-%m-%d %H:%M' 2>/dev/null || echo '?')"
  WT_EXISTS="no"
  [ -d "$WORKTREE" ] && WT_EXISTS="yes"

  printf "%-24s %-20s %-8s %-20s %-10s %s\n" "$TASK" "$STATUS" "$PID" "$DISPATCHED_AT" "$ACCOUNT" "worktree:$WT_EXISTS"
done
