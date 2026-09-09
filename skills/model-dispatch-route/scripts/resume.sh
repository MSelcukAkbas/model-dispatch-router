#!/bin/bash
# Usage: resume.sh <task-id> [--timeout MINUTES] [--effort LEVEL] [--budget USD] [--amend-prompt FILE]
#
# budget-usd: human-supplied override for dispatch.sh's --max-budget-usd.
# Skips its no-progress clamp/halving AND the exit-19 refusal entirely — use
# only after checking WHY the clamp fired (usually: dispatch.sh's diffstat
# progress-measure undercounting, e.g. untracked-file-only progress before
# the 2026-07-26 fix — see dispatch.sh's diffstat comment). Not a routine arg.
#
# Re-dispatches a task that got cut off by quota exhaustion (status.sh exit
# 17), its own --max-budget-usd runaway guard (exit 20), or a plain timeout
# (exit 14) — same role, same worktree (dispatch.sh reuses it, so any
# partial edits from the earlier attempt are still there on disk), and the
# SAME conversation via `claude --resume <session-id>` — the model actually
# remembers what it already reasoned/did, this is not just a fresh run
# pointed at the same files. Falls back to a fresh conversation (still same
# worktree/prompt) only if the task predates the session-id feature (no
# session_id line in $TASK.meta).
#
# On a budget-capped(20)/no-progress resume, dispatch.sh's own budget-clamp
# logic takes over automatically — it will NOT just hand back the same
# dollar amount that already ran out; it checks whether the worktree diff
# grew since the last attempt and halves/quarters the budget if not (see
# dispatch.sh's "Budget clamp" block). After enough no-progress attempts it
# refuses outright (dispatch.sh exit 19) rather than burning more quota on
# a loop — that refusal propagates through this script's exit code too.
#
# Carries the original no-worktree mode forward automatically (read from
# $TASK.meta) — a task first dispatched with no-worktree=1 stays no-worktree
# on every resume, no need to re-specify it.
#
# Also carries the original account/CLAUDE_CONFIG_DIR forward automatically
# (read from $TASK.meta) — mandatory, not just a convenience: a session
# resume (`claude --resume <session-id>`) only finds that session under the
# CLAUDE_CONFIG_DIR it was created in, so re-dispatching under a different
# (or ambient-at-resume-time) account would silently fail to find the prior
# conversation. No way to override this on resume — if you need a genuinely
# different account, that's a fresh dispatch under a new task-id instead.
#
# Does NOT touch the worktree or its files. Archives the previous attempt's
# .json/.err/.exitcode/.pid (renamed with a timestamp suffix) so status.sh/
# collect.sh read the NEW run, not stale state from the cut-off one.
#
# Exit codes: 0 re-dispatched | 1 bad usage/missing meta | 11 task not found |
#             18 task is not in a resumable state (still running, or never
#                failed) | 19 dispatch.sh refused — no-progress budget clamp
#                exhausted, needs a human, not another auto-resume
set -uo pipefail

if [ "$#" -lt 1 ]; then
  echo "usage: resume.sh <task-id> [--timeout MINUTES] [--effort LEVEL] [--budget USD] [--amend-prompt FILE]" >&2
  exit 1
fi
TASK="$1"
[[ "$TASK" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$ ]] || exit 1
BOOTSTRAP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$BOOTSTRAP_DIR/runtime.sh"
dispatch_bootstrap resume.sh "$TASK" "$@"
shift
TIMEOUT_OVERRIDE=""
EFFORT_OVERRIDE=""
BUDGET_OVERRIDE=""
AMEND_PROMPT=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --timeout) TIMEOUT_OVERRIDE="${2:?error: --timeout needs minutes}"; shift 2 ;;
    --effort) EFFORT_OVERRIDE="${2:?error: --effort needs a level}"; shift 2 ;;
    --budget) BUDGET_OVERRIDE="${2:?error: --budget needs USD}"; shift 2 ;;
    --amend-prompt) AMEND_PROMPT="${2:?error: --amend-prompt needs a file}"; shift 2 ;;
    *) echo "error: unknown argument '$1'" >&2; exit 1 ;;
  esac
done

REPO_ROOT="$(git rev-parse --show-toplevel)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$REPO_ROOT/.agent-logs"

if [ ! -f "$LOG_DIR/$TASK.meta" ] || [ ! -f "$LOG_DIR/$TASK.prompt.orig" ]; then
  echo "not_found: no resumable record for task '$TASK' (missing .meta or .prompt.orig — was it dispatched before the resume feature existed, or never dispatched?)" >&2
  exit 11
fi

# Reuse status.sh's own classification instead of re-implementing it —
# refuse to resume a task that's still running or that finished cleanly.
STATUS_OUT="$(bash "$SCRIPT_DIR/status.sh" "$TASK" 2>&1)"
STATUS_CODE=$?
if [ "$STATUS_CODE" != "17" ] && [ "$STATUS_CODE" != "14" ] && [ "$STATUS_CODE" != "20" ] && [ "$STATUS_CODE" != "21" ] && [ "$STATUS_CODE" != "22" ]; then
  echo "refused: task '$TASK' is not in a resumable state (status.sh exit $STATUS_CODE: $STATUS_OUT). Only quota-exhausted(17), budget-capped(20), or timeout(14) tasks can be resumed." >&2
  exit 18
fi

# shellcheck disable=SC1090
ROLE="$(grep '^role=' "$LOG_DIR/$TASK.meta" | cut -d= -f2)"
META_TIMEOUT="$(grep '^timeout_min=' "$LOG_DIR/$TASK.meta" | cut -d= -f2)"
META_EFFORT="$(grep '^effort=' "$LOG_DIR/$TASK.meta" | cut -d= -f2)"
META_SESSION_ID="$(grep '^session_id=' "$LOG_DIR/$TASK.meta" | cut -d= -f2)"
# Missing on tasks dispatched before the no-worktree feature existed —
# default "0" (normal worktree behavior) via the ${VAR:-default} form, which
# also covers the empty-string case grep-no-match leaves behind.
META_NO_WORKTREE="$(grep '^no_worktree=' "$LOG_DIR/$TASK.meta" | cut -d= -f2)"
META_SNAPSHOT="$(grep '^snapshot=' "$LOG_DIR/$TASK.meta" | cut -d= -f2)"
# Missing on tasks dispatched before the multi-account feature existed —
# both default to "" via grep-no-match, same fallback shape as
# META_NO_WORKTREE above: an old task resumes under ambient env, unchanged
# from its pre-feature behavior.
META_ACCOUNT="$(grep '^account=' "$LOG_DIR/$TASK.meta" | cut -d= -f2)"
META_CONFIG_DIR="$(grep '^config_dir=' "$LOG_DIR/$TASK.meta" | cut -d= -f2)"
TIMEOUT_MIN="${TIMEOUT_OVERRIDE:-$META_TIMEOUT}"
EFFORT="${EFFORT_OVERRIDE:-$META_EFFORT}"

if [ -n "$AMEND_PROMPT" ]; then
  if [ ! -f "$AMEND_PROMPT" ]; then
    echo "error: amendment prompt file not found: $AMEND_PROMPT" >&2
    exit 1
  fi
  AMEND_COPY="$LOG_DIR/$TASK.prompt.amend.$(date +%s).txt"
  cp "$AMEND_PROMPT" "$AMEND_COPY"
  export DISPATCH_RESUME_AMEND_FILE="$AMEND_COPY"
fi

TS="$(date +%s)"
# bridge.json/stophook-count/result-missing archived too (2026-07-30 fix —
# H2, same rationale as dispatch.sh's stale-artifact guard): resume.sh keeps
# the SAME worktree/branch on purpose, but the agent-bridge state from the
# cut-off attempt (pending questions, any partial submit_result, the
# Stop-hook block counter) must not leak into the resumed run as if it were
# current.
for ext in json err exitcode pid bridge.json stophook-count result-missing agentmind-context.md agentmind-start.log agentmind-end.log; do
  [ -f "$LOG_DIR/$TASK.$ext" ] && mv "$LOG_DIR/$TASK.$ext" "$LOG_DIR/$TASK.$ext.prev-$TS"
done

# Exported unconditionally (even when empty, which means "force ambient/
# default", not "don't care") — dispatch.sh distinguishes "unset" from
# "set to empty" via `${DISPATCH_CONFIG_DIR_OVERRIDE+set}`, see its own
# "Account / config-dir resolution" block.
export DISPATCH_CONFIG_DIR_OVERRIDE="$META_CONFIG_DIR"

if [ -n "$META_SESSION_ID" ]; then
  echo "resuming: task=$TASK role=$ROLE account=${META_ACCOUNT:-ambient} session=$META_SESSION_ID (continuing actual conversation; previous attempt's logs archived as *.prev-$TS)"
  export DISPATCH_RESUME=1
  export DISPATCH_SESSION_ID="$META_SESSION_ID"
else
  echo "resuming: task=$TASK role=$ROLE account=${META_ACCOUNT:-ambient} (no session_id on record — task predates this feature, starting a FRESH conversation on the same worktree/prompt instead; previous logs archived as *.prev-$TS)" >&2
fi
DISPATCH_ARGS=(--timeout "$TIMEOUT_MIN" --effort "$EFFORT")
[ -n "$BUDGET_OVERRIDE" ] && DISPATCH_ARGS+=(--budget "$BUDGET_OVERRIDE")
[ -n "$META_ACCOUNT" ] && DISPATCH_ARGS+=(--account "$META_ACCOUNT")
[ "${META_NO_WORKTREE:-0}" = "1" ] && DISPATCH_ARGS+=(--no-worktree)
[ "${META_SNAPSHOT:-0}" = "1" ] && DISPATCH_ARGS+=(--snapshot)
exec bash "$SCRIPT_DIR/dispatch.sh" "$ROLE" "$TASK" "$LOG_DIR/$TASK.prompt.orig" "${DISPATCH_ARGS[@]}"
