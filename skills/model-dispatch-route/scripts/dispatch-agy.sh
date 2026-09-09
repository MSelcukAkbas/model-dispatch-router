#!/bin/bash
# Usage: dispatch-agy.sh <role: research|judge|coder> <task-id> <prompt-file> [timeout-minutes] [model]
#
# Google Antigravity CLI (`agy`) engine lane — SEPARATE from dispatch.sh's
# Claude-only pipeline. Added 2026-08-27 (research/judge), coder added
# 2026-09-01. Every behavior claim below was verified against the live
# binary (`agy --help`, `agy mcp --help`, `agy models`, `agy changelog`, and
# real `agy -p` calls) on this machine, not from web docs — the docs were
# found to be wrong/incomplete during the original investigation (see
# knowledge base + session history for the raw evidence).
#
# Why a separate script instead of folding into dispatch.sh:
#   - agy has NO --tools allowlist / --disallowedTools equivalent — no way to
#     structurally restrict it to Read/Grep/Glob the way Claude's readonly
#     roles are restricted. Verified live (2026-08-27): with
#     --dangerously-skip-permissions OMITTED, a write-tool call is
#     auto-denied in headless mode (fail-closed, empty response) while a
#     pure-read task succeeds normally (file read is workspace-scoped
#     auto-allow per agy's own changelog). research/judge NEVER get
#     --dangerously-skip-permissions — hardcoded below, not a caller option.
#   - coder (2026-09-01) DOES need write access, so it gets a different
#     safety model instead of the missing tool-allowlist:
#       1. `--sandbox` — agy's own terminal/tool sandbox. Per agy's
#          changelog (1.1.7 area): ".git added to core list of dangerous
#          paths, preventing unauthorized or destructive repository
#          modification", plus general command/path restrictions. This is
#          VENDOR-DOCUMENTED, not independently round-tripped end-to-end in
#          this repo yet (a live test of "does `--sandbox
#          --dangerously-skip-permissions` actually block `git commit` in
#          practice" was started 2026-09-01 and interrupted before a
#          conclusive result — see task history). Treat it as a real but
#          unproven-here backstop, same epistemic honesty as the ops.md SSH
#          caveat and dispatch.sh's own commit/push denylist caveat — the
#          real backstop is still worktree isolation + diff review before
#          apply.sh, not this flag.
#       2. A disposable git worktree + throwaway branch, using the EXACT
#          SAME naming convention dispatch.sh uses (`$REPO_ROOT/.worktrees/
#          $TASK`, branch `agent/$TASK`) — deliberately, so diff.sh/
#          apply.sh/verify.sh/cleanup.sh (which all derive the worktree path
#          purely from the task-id) work UNCHANGED for an agy-coder task,
#          exactly as they do for a dispatch.sh backend/design/sdk/general
#          task. Trade-off: dispatching the SAME task-id to both engines
#          concurrently collides (`git worktree add` fails loudly on the
#          second call — safe failure, not silent corruption) — don't reuse
#          a task-id across engines while one is still active.
#     `--dangerously-skip-permissions` is still required for coder to write
#     at all (same fail-closed behavior noted above) — it is NOT gated
#     behind anything else, so the worktree + `--sandbox` are the only two
#     things standing between this role and the real working tree. Persona
#     (`agy-coder.md`) also behaviorally forbids commit/push/delete, same
#     belt-and-suspenders pattern as the Claude writer roles' persona text.
#   - agy has NO per-invocation --mcp-config — only a persistent named
#     `agy mcp add <name> ...` shared across every future call, unlike
#     Claude's per-task dynamic mcp-config file. So the agent-bridge MCP
#     server (submit_result/knowledge_write/knowledge_search) is NOT wired
#     here for ANY role, coder included — a shared persistent registration
#     would mix task state across unrelated concurrent agy calls, since
#     agent-bridge.js's per-task state relies on a DISPATCH_TASK_ID env var
#     agy has no equivalent hook for. Instead: agy returns plain text (its
#     `response` field, structured per the STATUS/CHANGED/RISK/VERIFIED/
#     FINDINGS shape in `personas/agy-coder.md`); the ORCHESTRATOR reads
#     $TASK.agy.json, applies via apply.sh, and calls knowledge_write itself
#     for anything durable. Do not add agy to the bridge's mcp registration
#     without re-reading this comment.
#   - --new-project is MANDATORY, not a flag callers can skip (verified live
#     2026-08-27): without it, agy can silently answer from an unrelated
#     STALE prior project's files instead of the current directory's actual
#     content — reproduced the leak with --add-dir alone, fixed it by adding
#     --new-project. Every call below always passes it.
#   - --model and --effort CONFLICT when the model name already encodes a
#     tier (verified live: `--model gemini-3.5-flash-medium --effort low`
#     errors "conflicts with --effort=low"). All model choices here use
#     tiered names (…-high/-medium/-low) and --effort is never passed.
#   - research/judge run directly in REPO_ROOT via --add-dir, no worktree —
#     both are read-only by construction (same reasoning dispatch.sh already
#     uses). coder gets a worktree (see above) since it writes.
#   - No budget clamp / no quota pre-check for ANY role here: agy has no
#     --max-budget-usd and no quota-query subcommand (verified — neither
#     `agy --help` nor `agy changelog` expose one, only a per-session cost
#     display). A call that hits exhausted quota surfaces as a normal error
#     at call time. For coder this also means none of dispatch.sh's
#     no-progress budget-halving/exit-19 protection exists — a looping coder
#     task is only bounded by --print-timeout, nothing else.
#   - Foreground, not backgrounded: agy's -p mode returns exactly ONE json
#     blob at completion, nothing to poll mid-run. Blocks until agy exits or
#     --print-timeout fires.
#
# Exit codes: 0 done | 1 bad usage/missing files | 11 (coder only) worktree
#             already exists and reused, OR `git worktree add` itself failed
#             | passthrough of agy's own non-zero exit code on failure
#             (not remapped).
set -uo pipefail

[ "$#" -ge 3 ] || { echo 'usage: dispatch-agy.sh research|judge|coder TASK PROMPT [MINUTES] [MODEL]' >&2; exit 1; }
BOOTSTRAP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$BOOTSTRAP_DIR/runtime.sh"
dispatch_bootstrap dispatch-agy.sh "$2" "$@"

ROLE="$1"
TASK="$2"
PROMPT_FILE="$3"
TIMEOUT_MIN="${4:-10}"
MODEL_OVERRIDE="${5:-}"
[[ "$TIMEOUT_MIN" =~ ^[1-9][0-9]*$ ]] || { echo 'error: timeout must be positive integer minutes' >&2; exit 1; }

case "$ROLE" in
  research|judge|coder) ;;
  *) echo "error: dispatch-agy.sh only supports role=research, role=judge, or role=coder. Got: '$ROLE'" >&2; exit 1 ;;
esac

REPO_ROOT="$(git rev-parse --show-toplevel)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$REPO_ROOT/.agent-logs"

AGY_BIN="${AGY_BIN:-agy}"
command -v "$AGY_BIN" >/dev/null 2>&1 || AGY_BIN="$LOCALAPPDATA/agy/bin/agy.exe"
if ! command -v "$AGY_BIN" >/dev/null 2>&1 && [ ! -x "$AGY_BIN" ]; then
  echo "error: agy binary not found (checked PATH and \$LOCALAPPDATA/agy/bin/agy.exe)" >&2
  exit 1
fi

PERSONA_FILE="$SCRIPT_DIR/../personas/agy-$ROLE.md"
if [ ! -f "$PERSONA_FILE" ]; then
  echo "error: no agy persona file for role '$ROLE' at $PERSONA_FILE" >&2
  exit 1
fi
if [ ! -f "$PROMPT_FILE" ]; then
  echo "error: prompt file not found: $PROMPT_FILE" >&2
  exit 1
fi

GOAL_LINE="$(grep -m1 '^# GOAL:' "$PROMPT_FILE" || true)"
if [ -z "$GOAL_LINE" ]; then
  echo "error: prompt file must start with a '# GOAL: <one sentence>' header — exactly one objective, this engine gets one shot, no back-and-forth." >&2
  exit 1
fi

# Tiered model defaults per role — research is cheap/fast scanning (mirrors
# Claude's haiku pick), judge is Google's strongest reasoning tier (the whole
# point of this lane is an independent-vendor cross-check for judge, not
# just re-running Claude through a different CLI).
declare -A ROLE_MODEL=(
  [research]="gemini-3.7-flash-medium"
  [judge]="gemini-3.1-pro-high"
  [coder]="gemini-3.1-pro-high"
)
MODEL="${MODEL_OVERRIDE:-${ROLE_MODEL[$ROLE]}}"

mkdir -p "$LOG_DIR" "$REPO_ROOT/.worktrees"

source "$SCRIPT_DIR/scope.sh"
if [ "$ROLE" = coder ]; then
  FILES_LINE="$(grep -m1 '^# FILES:' "$PROMPT_FILE" || true)"
  [ -n "$FILES_LINE" ] || { echo 'error: coder requires # FILES:' >&2; exit 13; }
  SCOPE_TMP="$(mktemp)"
  IFS=',' read -ra ENTRIES <<< "${FILES_LINE#'# FILES:'}"
  for ENTRY in "${ENTRIES[@]}"; do
    ENTRY="$(printf '%s' "$ENTRY" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    scope_normalize_entry "$ENTRY" >> "$SCOPE_TMP" || { rm -f "$SCOPE_TMP"; exit 13; }
  done
  [ -s "$SCOPE_TMP" ] || { rm -f "$SCOPE_TMP"; exit 13; }
  mv "$SCOPE_TMP" "$LOG_DIR/$TASK.scope"
  scope_reserve "$LOG_DIR" "$TASK" "$SCRIPT_DIR" || exit $?
else
  # Explicit command-free protocol; does not pretend to be a tool sandbox.
  # Omitted permission bypass stays fail-closed for headless denied operations.
  echo 'preflight: read-only AGY uses file reads only; if a command is needed return STATUS: BLOCKED with the reason.' >&2
fi

# coder writes, so it needs a real isolation boundary — reuse dispatch.sh's
# EXACT worktree/branch naming (see header comment) so diff.sh/apply.sh/
# verify.sh/cleanup.sh work on an agy-coder task with zero changes.
# research/judge stay in REPO_ROOT (read-only by construction, worktree buys
# them nothing — same reasoning dispatch.sh uses for its own research/judge).
WORKTREE_DIR="$REPO_ROOT/.worktrees/$TASK"
BRANCH="agent/$TASK"
if [ "$ROLE" = "coder" ]; then
  if [ -d "$WORKTREE_DIR" ]; then
    echo "note: worktree $WORKTREE_DIR already exists — reusing." >&2
  elif ! git -C "$REPO_ROOT" worktree add -b "$BRANCH" "$WORKTREE_DIR" HEAD; then
    echo "error: git worktree add failed for '$TASK' (branch '$BRANCH' may already exist — check 'git branch -a' / 'git worktree list', possibly a prior dispatch.sh or dispatch-agy.sh run on the same task-id; cleanup.sh removes both). Refusing to fall back to the main checkout for a writer role that expects isolation." >&2
    exit 11
  fi
  RUN_DIR="$WORKTREE_DIR"
else
  RUN_DIR="$REPO_ROOT"
fi

CLEAN_PROMPT_FILE="$LOG_DIR/$TASK.agy.prompt.tmp"
grep -v -e '^# GOAL:' -e '^# FILES:' "$PROMPT_FILE" > "$CLEAN_PROMPT_FILE"

PERSONA="$(cat "$PERSONA_FILE")"
FULL_PROMPT="$PERSONA

Task ID: $TASK
Single goal: ${GOAL_LINE#"# GOAL:"}

$(cat "$CLEAN_PROMPT_FILE")"

if [ "$ROLE" != coder ]; then
  FULL_PROMPT="$FULL_PROMPT

Do not invoke terminal/shell commands or write tools. Use file-read tools only. If these cannot answer the task, return STATUS: BLOCKED and explain the missing capability. Never return an empty response."
fi
FULL_PROMPT="$FULL_PROMPT

Return a nonempty result starting with STATUS: DONE, PARTIAL, or BLOCKED. Include evidence, remaining work, and verification. Work in small units; preserve intermediate findings in your response as you go."

{
  echo "role=$ROLE"
  echo "model=$MODEL"
  echo "timeout_min=$TIMEOUT_MIN"
  echo "engine=agy"
  [ "$ROLE" = "coder" ] && echo "worktree=$WORKTREE_DIR" && echo "branch=$BRANCH"
} > "$LOG_DIR/$TASK.agy.meta"

# coder-only flags: --sandbox (agy's terminal/path sandbox — blocks .git
# writes among other dangerous paths, per agy's changelog; see header
# comment for the honest "vendor-documented, not fully round-tripped here"
# caveat) + --dangerously-skip-permissions (required for ANY write tool call
# to succeed at all in headless mode — without it every write is auto-denied,
# verified live 2026-08-27). Never passed for research/judge.
AGY_EXTRA_ARGS=()
if [ "$ROLE" = "coder" ]; then
  AGY_EXTRA_ARGS+=(--sandbox --dangerously-skip-permissions)
  echo "dispatching (agy): task=$TASK role=$ROLE model=$MODEL timeout=${TIMEOUT_MIN}m worktree=$WORKTREE_DIR branch=$BRANCH" >&2
else
  echo "dispatching (agy): task=$TASK role=$ROLE model=$MODEL timeout=${TIMEOUT_MIN}m" >&2
fi

TS_STALE="$(date +%s)"
for ext in agy.json agy.err agy.exitcode agy.pid run.json final-status.json checkpoint.json; do
  [ ! -f "$LOG_DIR/$TASK.$ext" ] || mv "$LOG_DIR/$TASK.$ext" "$LOG_DIR/$TASK.$ext.prev-$TS_STALE"
done
node "$SCRIPT_DIR/lifecycle.js" begin "$LOG_DIR" "$TASK" agy "$BASHPID" false || exit 1
(
  cd "$RUN_DIR" || { echo "error: cd to RUN_DIR ($RUN_DIR) failed" >&2; exit 1; }
  timeout "${TIMEOUT_MIN}m" "$AGY_BIN" -p "$FULL_PROMPT" \
    --new-project \
    --add-dir "$RUN_DIR" \
    --model "$MODEL" \
    "${AGY_EXTRA_ARGS[@]}" \
    --output-format json \
    --print-timeout "${TIMEOUT_MIN}m" \
    > "$LOG_DIR/$TASK.agy.json" 2> "$LOG_DIR/$TASK.agy.err"
)
EXIT_CODE=$?
node "$SCRIPT_DIR/lifecycle.js" finalize "$LOG_DIR" "$TASK" "$EXIT_CODE"
EXIT_CODE=$?
node "$SCRIPT_DIR/lifecycle.js" hook "$LOG_DIR" "$TASK" 0

if [ "$EXIT_CODE" -ne 0 ]; then
  echo "error: agy exited $EXIT_CODE for task '$TASK' — see $LOG_DIR/$TASK.agy.err" >&2
  exit "$EXIT_CODE"
fi

if [ "$ROLE" = "coder" ]; then
  echo "done: task=$TASK — response in $LOG_DIR/$TASK.agy.json (parse .response field, expect STATUS/CHANGED/RISK/VERIFIED/FINDINGS per personas/agy-coder.md). Worktree at $WORKTREE_DIR, branch $BRANCH — review with 'diff.sh $TASK', apply with 'apply.sh $TASK' (same as a dispatch.sh writer task), then cleanup.sh $TASK when done. Call knowledge_write yourself for any durable FINDINGS — this lane has no bridge MCP wired." >&2
else
  echo "done: task=$TASK — response in $LOG_DIR/$TASK.agy.json (parse .response field). Read it and call knowledge_write yourself if anything durable came up — this lane has no bridge MCP wired." >&2
fi
exit 0
