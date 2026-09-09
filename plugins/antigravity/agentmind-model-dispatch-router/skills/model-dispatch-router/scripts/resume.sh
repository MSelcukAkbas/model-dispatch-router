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
# A task that finished successfully (status 0) can ALSO be resumed, but only
# together with --amend-prompt: this is the "orchestrator reviewed the diff
# and rejected it" path (contradicts the report, missing a required file,
# fails an obvious check) that used to force discarding the whole worktree
# and starting a brand-new task-id for what was often a one-file fix — see
# SKILL.md's dispatch workflow notes. Same worktree, same session, the
# amendment is handed to the model as new instructions on top of what it
# already did; the original prompt file itself is never edited.
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
#             18 task is not in a resumable state (still running; or done
#                without --amend-prompt) | 19 dispatch.sh refused —
#                no-progress budget clamp exhausted, needs a human, not
#                another auto-resume
set -uo pipefail

if [ "$#" -lt 1 ]; then
  echo "usage: resume.sh <task-id> [--timeout MINUTES] [--effort LEVEL] [--budget USD] [--amend-prompt FILE]" >&2
  exit 1
fi
TASK="$1"
BOOTSTRAP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=dispatch-common.sh
source "$BOOTSTRAP_DIR/dispatch-common.sh"
dispatch_common_valid_task_id "$TASK" || exit 1
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

IS_CODEX=0
META_FILE=""
if [ -f "$LOG_DIR/$TASK.codex.meta" ]; then
  IS_CODEX=1
  META_FILE="$LOG_DIR/$TASK.codex.meta"
elif [ -f "$LOG_DIR/$TASK.meta" ]; then
  META_FILE="$LOG_DIR/$TASK.meta"
  [ "$(grep '^engine=' "$META_FILE" | cut -d= -f2 || true)" = "codex" ] && IS_CODEX=1
fi

if [ -z "$META_FILE" ] || [ ! -f "$LOG_DIR/$TASK.prompt.orig" ]; then
  echo "not_found: no resumable record for task '$TASK' (missing .meta or .prompt.orig — was it dispatched before the resume feature existed, or never dispatched?)" >&2
  exit 11
fi

# Reuse status.sh's own classification instead of re-implementing it —
# refuse to resume a task that's still running.
STATUS_OUT="$(bash "$SCRIPT_DIR/status.sh" "$TASK" 2>&1)"
STATUS_CODE=$?
# A cleanly finished task (0) is normally not resumable — resuming a
# successful run with no new instructions would just re-run it for nothing.
# But "done" only means the engine delivered SOMETHING; the orchestrator may
# still reject the deliverable (e.g. diff.sh's out-of-scope section shows a
# missing test, or the report contradicts the diff — see the AGY/Claude
# review-and-reject cases this exists for). --amend-prompt is required in
# that case specifically because it is the one signal that this is a
# deliberate correction round, not an accidental double-resume of a task
# that already succeeded.
if [ "$STATUS_CODE" = "0" ] && [ -z "$AMEND_PROMPT" ]; then
  echo "refused: task '$TASK' already finished successfully (status.sh exit 0). Pass --amend-prompt FILE if the orchestrator is rejecting the deliverable and wants a correction round in the SAME worktree/session instead of a fresh task-id." >&2
  exit 18
fi
if [ "$STATUS_CODE" != "0" ] && [ "$STATUS_CODE" != "17" ] && [ "$STATUS_CODE" != "14" ] && [ "$STATUS_CODE" != "20" ] && [ "$STATUS_CODE" != "21" ] && [ "$STATUS_CODE" != "22" ]; then
  echo "refused: task '$TASK' is not in a resumable state (status.sh exit $STATUS_CODE: $STATUS_OUT). Only done(0, with --amend-prompt), quota-exhausted(17), budget-capped(20), or timeout(14) tasks can be resumed." >&2
  exit 18
fi

# shellcheck disable=SC1090
ROLE="$(grep '^role=' "$META_FILE" | cut -d= -f2)"
META_TIMEOUT="$(grep '^timeout_min=' "$META_FILE" | cut -d= -f2)"
META_EFFORT="$(grep '^effort=' "$META_FILE" | cut -d= -f2)"
META_MODEL="$(grep '^model=' "$META_FILE" | cut -d= -f2 || true)"
META_SESSION_ID="$(grep -e '^session_id=' -e '^thread_id=' "$META_FILE" | head -n1 | cut -d= -f2 || true)"
META_NO_WORKTREE="$(grep '^no_worktree=' "$META_FILE" | cut -d= -f2 || true)"
META_SNAPSHOT="$(grep '^snapshot=' "$META_FILE" | cut -d= -f2 || true)"
META_ACCOUNT="$(grep '^account=' "$META_FILE" | cut -d= -f2 || true)"
META_CONFIG_DIR="$(grep '^config_dir=' "$META_FILE" | cut -d= -f2 || true)"
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
for ext in json err exitcode pid codex.json codex.err codex.txt codex.exitcode codex.pid bridge.json stophook-count result-missing agentmind-context.md agentmind-start.log agentmind-end.log; do
  [ -f "$LOG_DIR/$TASK.$ext" ] && mv "$LOG_DIR/$TASK.$ext" "$LOG_DIR/$TASK.$ext.prev-$TS"
done

if [ "$IS_CODEX" = "1" ]; then
  if [ -n "$META_SESSION_ID" ]; then
    echo "resuming (codex): task=$TASK role=$ROLE session=$META_SESSION_ID (continuing conversation; previous attempt's logs archived as *.prev-$TS)"
    export DISPATCH_RESUME=1
    export DISPATCH_SESSION_ID="$META_SESSION_ID"
  else
    echo "resuming (codex): task=$TASK role=$ROLE (no thread_id on record — starting fresh conversation on same worktree; previous logs archived as *.prev-$TS)" >&2
  fi
  DISPATCH_ARGS=(--timeout "$TIMEOUT_MIN" --effort "$EFFORT")
  [ -n "$META_MODEL" ] && DISPATCH_ARGS+=(--model "$META_MODEL")
  [ -n "$META_SESSION_ID" ] && DISPATCH_ARGS+=(--resume "$META_SESSION_ID")
  [ -n "$AMEND_PROMPT" ] && DISPATCH_ARGS+=(--amend-prompt "$AMEND_COPY")
  exec bash "$SCRIPT_DIR/dispatch-codex.sh" "$ROLE" "$TASK" "$LOG_DIR/$TASK.prompt.orig" "${DISPATCH_ARGS[@]}"
fi

# Exported unconditionally for Claude dispatches
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
