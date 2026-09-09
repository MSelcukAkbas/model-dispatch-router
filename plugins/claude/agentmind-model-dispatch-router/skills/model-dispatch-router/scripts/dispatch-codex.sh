#!/bin/bash
# Usage: dispatch-codex.sh <role: research|judge|coder> <task-id> <prompt-file> [timeout-minutes] [model]
#
# OpenAI Codex CLI (`codex exec`) engine lane — a THIRD engine alongside
# dispatch.sh (Claude) and dispatch-agy.sh (agy/Gemini), added 2026-09-09.
# Every behavior claim below was verified live against the installed binary
# (`codex --version` -> codex-cli 0.152.1, `codex exec --help`, and real
# `codex exec` calls in a scratch worktree) on this machine, not from vendor
# docs — same discipline dispatch-agy.sh's header applies to agy, for the
# same reason: CLI flag behavior drifts across versions faster than docs do.
#
# Why a separate script instead of folding into dispatch.sh or dispatch-agy.sh:
#   - `codex exec` is its own non-interactive surface with its own flag set
#     and its own JSONL event shape (thread.started/turn.started/
#     item.completed/turn.completed/turn.failed) — not Claude's stream-json,
#     not agy's single JSON blob. lifecycle.js has a dedicated `codexOutput()`
#     branch for it (see lifecycle.js) rather than forcing a third shape
#     through either existing engine's parser.
#   - Unlike agy, codex has a REAL structural sandbox with three levels
#     (`--sandbox read-only|workspace-write|danger-full-access`), not just a
#     persona instruction. Verified live 2026-09-09:
#       * `read-only`: a write attempt is REJECTED by the sandbox itself
#         before it reaches disk (`patch rejected: writing is blocked by
#         read-only sandbox`) — the model sees the rejection and can react
#         (e.g. report STATUS: BLOCKED), no `--dangerously-*` flag needed and
#         none is ever passed for research/judge here.
#       * `workspace-write`: normal file writes inside the workspace succeed,
#         but `.git/` writes are independently blocked — a live `git commit`
#         attempt failed with `Permission denied` creating `.git/index.lock`.
#         This is a STRONGER, independently-verified guarantee than agy's own
#         "--sandbox... vendor-documented, not fully round-tripped here"
#         caveat (see dispatch-agy.sh) — codex's git-write block was directly
#         reproduced, not just read in a changelog.
#     Combined with the same disposable worktree + throwaway branch dispatch.sh
#     and dispatch-agy.sh already use (`$REPO_ROOT/.worktrees/$TASK`, branch
#     `agent/$TASK`), coder gets two independent, both-verified isolation
#     layers instead of one.
#   - codex has NO per-invocation `--mcp-config` verified working end-to-end
#     here (the `-c mcp_servers.<name>....` TOML-override path exists in
#     principle but was NOT live-tested for this lane) — so, same as agy, the
#     agent-bridge MCP (submit_result/knowledge_write/knowledge_search) is
#     NOT wired for ANY role here. Instead: codex writes its final message to
#     a plain text file via `-o/--output-last-message` (structured per the
#     STATUS/SUMMARY|VERDICT/FINDINGS shapes in `personas/codex-*.md`), and
#     `ingest-findings.js` (shared with the agy lane, see its own header)
#     parses the FINDINGS: block and writes it directly to the knowledge
#     store after the engine exits — no MCP roundtrip needed.
#   - No budget clamp / no quota pre-check for ANY role here: codex exposes a
#     per-turn `usage` object in its `--json` stream (input/output/reasoning
#     tokens) but no `--max-budget-usd` and no quota-query subcommand found in
#     `codex --help`/`codex exec --help`. A call that hits exhausted quota
#     surfaces as a normal nonzero exit at call time — see lifecycle.js's
#     codex-specific classify() branch for exactly how that's detected (a
#     JSONL `type:"error"`/`type:"turn.failed"` event, NOT stderr — verified
#     live via a deliberately-invalid `-m` call: stderr held only generic
#     "Reading additional input from stdin..." noise, the real 400 was in the
#     JSONL). The rate-limit/quota TEXT shape specifically is NOT verified
#     the same way (would require actually exhausting quota) — classify()
#     applies the same regex the other two engines use, on a best-effort
#     basis, and falls back to a generic `failed` if it doesn't match.
#   - Model selection: `codex --help`/`codex exec --help` expose no
#     `codex models`-equivalent list command (unlike agy's `agy models`), and
#     `~/.codex/config.toml`'s example `-c model="o3"` is illustrative, not a
#     verified-current catalog. Rather than hardcode a guessed model name,
#     MODEL_OVERRIDE (5th positional arg) is optional and `-m` is omitted
#     entirely when not given — codex then uses whatever `~/.codex/config.toml`
#     already has configured (verified live on this machine: `gpt-5.6-sol`,
#     confirmed working). Re-verify that file's `model` key before assuming a
#     name is still current if this drifts.
#   - Reasoning effort uses the SAME low|medium|high|xhigh|max vocabulary
#     role-config.js already validates for Claude roles (via
#     `-c model_reasoning_effort=<level>`), even though codex's own
#     `enabled-reasoning-efforts` config lists extra tiers (ultra, persistent)
#     — kept to the shared vocabulary so a role's effort means the same thing
#     regardless of which engine runs it.
#   - Foreground, not backgrounded: `codex exec` streams JSONL to stdout and
#     exits when the turn completes (or `timeout` kills it). Nothing to poll
#     mid-run, same as agy.
#
# Exit codes: 0 done | 1 bad usage/missing files | 11 (coder only) worktree
#             already exists and reused, OR `git worktree add` itself failed
#             | 13 invalid/missing scope manifest | passthrough of codex's own
#             non-zero exit code on failure (not remapped).
set -uo pipefail

[ "$#" -ge 3 ] || { echo 'usage: dispatch-codex.sh research|judge|coder TASK PROMPT [--timeout MINUTES] [--model MODEL] [--effort LEVEL] [--resume SESSION_ID] [--amend-prompt FILE]' >&2; exit 1; }
BOOTSTRAP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$BOOTSTRAP_DIR/runtime.sh"
dispatch_bootstrap dispatch-codex.sh "$2" "$@"

ROLE="$1"
TASK="$2"
PROMPT_FILE="$3"
shift 3

TIMEOUT_MIN=10
MODEL_OVERRIDE=""
EFFORT_OVERRIDE=""
RESUME_MODE="${DISPATCH_RESUME:-0}"
RESUME_SESSION_ID="${DISPATCH_SESSION_ID:-}"
AMEND_FILE="${DISPATCH_RESUME_AMEND_FILE:-}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --timeout) TIMEOUT_MIN="${2:?error: --timeout needs minutes}"; shift 2 ;;
    --model) MODEL_OVERRIDE="${2:?error: --model needs a model name}"; shift 2 ;;
    --effort) EFFORT_OVERRIDE="${2:?error: --effort needs a level}"; shift 2 ;;
    --resume) RESUME_MODE=1; RESUME_SESSION_ID="${2:-}"; shift 2 ;;
    --amend-prompt) AMEND_FILE="${2:?error: --amend-prompt needs a file}"; shift 2 ;;
    *)
      # Backwards compatibility with positional [MINUTES] [MODEL]
      if [[ "$1" =~ ^[1-9][0-9]*$ ]] && [ "$TIMEOUT_MIN" -eq 10 ]; then
        TIMEOUT_MIN="$1"; shift
      elif [ -z "$MODEL_OVERRIDE" ] && [[ "$1" != --* ]]; then
        MODEL_OVERRIDE="$1"; shift
      else
        echo "error: unknown argument '$1'" >&2; exit 1
      fi
      ;;
  esac
done

[[ "$TIMEOUT_MIN" =~ ^[1-9][0-9]*$ ]] || { echo 'error: timeout must be positive integer minutes' >&2; exit 1; }

case "$ROLE" in
  research|judge|coder) ;;
  *) echo "error: dispatch-codex.sh only supports role=research, role=judge, or role=coder. Got: '$ROLE'" >&2; exit 1 ;;
esac

REPO_ROOT="$(git rev-parse --show-toplevel)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$REPO_ROOT/.agent-logs"

CODEX_BIN="${CODEX_BIN:-codex}"
command -v "$CODEX_BIN" >/dev/null 2>&1 || { echo "error: codex binary not found on PATH (checked '$CODEX_BIN')" >&2; exit 1; }

PERSONA_FILE="$SCRIPT_DIR/../personas/codex-$ROLE.md"
if [ ! -f "$PERSONA_FILE" ]; then
  echo "error: no codex persona file for role '$ROLE' at $PERSONA_FILE" >&2
  exit 1
fi
if [ ! -f "$PROMPT_FILE" ]; then
  echo "error: prompt file not found: $PROMPT_FILE" >&2
  exit 1
fi

source "$SCRIPT_DIR/scope.sh"
source "$SCRIPT_DIR/dispatch-common.sh"
GOAL_LINE="$(dispatch_common_require_goal "$PROMPT_FILE" "this engine gets one shot, no back-and-forth")" || exit 1

declare -A ROLE_EFFORT=(
  [research]="low"
  [judge]="high"
  [coder]="high"
)
EFFORT="${EFFORT_OVERRIDE:-${ROLE_EFFORT[$ROLE]}}"

mkdir -p "$LOG_DIR" "$REPO_ROOT/.worktrees"

if [ "$ROLE" = coder ]; then
  FILES_LINE="$(grep -m1 '^# FILES:' "$PROMPT_FILE" || true)"
  [ -n "$FILES_LINE" ] || { echo 'error: coder requires # FILES:' >&2; exit 13; }
  dispatch_common_build_scope "$LOG_DIR" "$TASK" "$SCRIPT_DIR" "${FILES_LINE#'# FILES:'}" || { CODE=$?; [ "$CODE" = 12 ] && exit 12; exit 13; }
else
  echo 'preflight: read-only codex role runs under --sandbox read-only; a write attempt is rejected by the sandbox itself, not just by persona instruction.' >&2
fi

WORKTREE_DIR="$REPO_ROOT/.worktrees/$TASK"
BRANCH="agent/$TASK"
if [ "$ROLE" = "coder" ]; then
  dispatch_common_ensure_worktree "$REPO_ROOT" "$WORKTREE_DIR" "$BRANCH" || exit 11
  RUN_DIR="$WORKTREE_DIR"
else
  RUN_DIR="$REPO_ROOT"
fi

# Always preserve prompt.orig on first dispatch for resume.sh
[ "$RESUME_MODE" != "1" ] && cp "$PROMPT_FILE" "$LOG_DIR/$TASK.prompt.orig"

CLEAN_PROMPT_FILE="$LOG_DIR/$TASK.codex.prompt.tmp"
grep -v -e '^# GOAL:' -e '^# FILES:' "$PROMPT_FILE" > "$CLEAN_PROMPT_FILE"

PERSONA="$(cat "$PERSONA_FILE")"
FULL_PROMPT="$PERSONA

Task ID: $TASK
Single goal: ${GOAL_LINE#"# GOAL:"}

$(cat "$CLEAN_PROMPT_FILE")"

if [ "$ROLE" != coder ]; then
  FULL_PROMPT="$FULL_PROMPT

Return a nonempty result starting with STATUS: DONE, PARTIAL, or BLOCKED. Include evidence, remaining work, and verification. Work in small units; preserve intermediate findings in your response as you go."
fi

# Determine previous thread_id if resuming
if [ "$RESUME_MODE" = "1" ] && [ -z "$RESUME_SESSION_ID" ] && [ -f "$LOG_DIR/$TASK.codex.meta" ]; then
  RESUME_SESSION_ID="$(grep '^thread_id=' "$LOG_DIR/$TASK.codex.meta" | cut -d= -f2 || true)"
fi

{
  echo "role=$ROLE"
  echo "effort=$EFFORT"
  [ -n "$MODEL_OVERRIDE" ] && echo "model=$MODEL_OVERRIDE"
  echo "timeout_min=$TIMEOUT_MIN"
  echo "engine=codex"
  [ -n "$RESUME_SESSION_ID" ] && echo "thread_id=$RESUME_SESSION_ID"
  [ "$ROLE" = "coder" ] && echo "worktree=$WORKTREE_DIR" && echo "branch=$BRANCH"
} > "$LOG_DIR/$TASK.codex.meta"

SANDBOX="read-only"
[ "$ROLE" = "coder" ] && SANDBOX="workspace-write"

if [ "$RESUME_MODE" = "1" ] && [ -n "$RESUME_SESSION_ID" ]; then
  if [ -n "$AMEND_FILE" ] && [ -f "$AMEND_FILE" ]; then
    EXEC_PROMPT="You are continuing a prior task. The orchestrator reviewed your previous delivery and provided this amendment:

$(cat "$AMEND_FILE")"
  else
    EXEC_PROMPT="You are resuming a prior turn that was cut off before completion. Your previous thoughts and partial worktree edits are still intact. Continue where you left off."
  fi
  CODEX_ARGS=(exec resume --json -c "model_reasoning_effort=$EFFORT" -o "$LOG_DIR/$TASK.codex.txt")
  [ -n "$MODEL_OVERRIDE" ] && CODEX_ARGS+=(-m "$MODEL_OVERRIDE")
  CODEX_ARGS+=("$RESUME_SESSION_ID" "$EXEC_PROMPT")
  echo "resuming (codex): task=$TASK role=$ROLE session=$RESUME_SESSION_ID timeout=${TIMEOUT_MIN}m" >&2
else
  CODEX_ARGS=(exec --sandbox "$SANDBOX" --json -c "model_reasoning_effort=$EFFORT" -o "$LOG_DIR/$TASK.codex.txt")
  [ -n "$MODEL_OVERRIDE" ] && CODEX_ARGS+=(-m "$MODEL_OVERRIDE")
  CODEX_ARGS+=("$FULL_PROMPT")
  if [ "$ROLE" = "coder" ]; then
    echo "dispatching (codex): task=$TASK role=$ROLE effort=$EFFORT${MODEL_OVERRIDE:+ model=$MODEL_OVERRIDE} timeout=${TIMEOUT_MIN}m sandbox=$SANDBOX worktree=$WORKTREE_DIR branch=$BRANCH" >&2
  else
    echo "dispatching (codex): task=$TASK role=$ROLE effort=$EFFORT${MODEL_OVERRIDE:+ model=$MODEL_OVERRIDE} timeout=${TIMEOUT_MIN}m sandbox=$SANDBOX" >&2
  fi
fi

dispatch_common_archive_stale "$LOG_DIR" "$TASK" codex.json codex.err codex.txt codex.exitcode codex.pid run.json final-status.json checkpoint.json
node "$SCRIPT_DIR/lifecycle.js" begin "$LOG_DIR" "$TASK" codex "$BASHPID" false || exit 1
(
  cd "$RUN_DIR" || { echo "error: cd to RUN_DIR ($RUN_DIR) failed" >&2; exit 1; }
  : > "$LOG_DIR/$TASK.codex.txt"
  timeout "${TIMEOUT_MIN}m" "$CODEX_BIN" "${CODEX_ARGS[@]}" \
    > "$LOG_DIR/$TASK.codex.json" 2> "$LOG_DIR/$TASK.codex.err" < /dev/null
)
EXIT_CODE=$?
node "$SCRIPT_DIR/lifecycle.js" finalize "$LOG_DIR" "$TASK" "$EXIT_CODE"
EXIT_CODE=$?
node "$SCRIPT_DIR/lifecycle.js" hook "$LOG_DIR" "$TASK" 0

# Structural fix for the "engine findings never reach the knowledge store"
# gap this lane shares with agy (no per-invocation MCP — see header comment):
# parse whatever FINDINGS: block the response contains and write it directly
# against knowledge-store.js. Runs on any classified outcome with a captured
# response (done/partial/blocked), not just success. Fail-open: a
# knowledge-store problem is logged, never turns an otherwise-fine dispatch
# into a failure.
node "$SCRIPT_DIR/ingest-findings.js" "$LOG_DIR" "$TASK" codex 2>&1 | sed 's/^/knowledge: /' >&2 || true

if [ "$EXIT_CODE" -ne 0 ]; then
  echo "error: codex exited $EXIT_CODE for task '$TASK' — see $LOG_DIR/$TASK.codex.err and $LOG_DIR/$TASK.codex.json" >&2
  exit "$EXIT_CODE"
fi

if [ "$ROLE" = "coder" ]; then
  echo "done: task=$TASK — final message in $LOG_DIR/$TASK.codex.txt (expect STATUS/CHANGED/RISK/VERIFIED/FINDINGS per personas/codex-coder.md). Worktree at $WORKTREE_DIR, branch $BRANCH — review with 'diff.sh $TASK', apply with 'apply.sh $TASK' (same as a dispatch.sh writer task), then cleanup.sh $TASK when done. FINDINGS were auto-ingested into the knowledge store above; call knowledge_write yourself only for something that came up outside that block." >&2
else
  echo "done: task=$TASK — final message in $LOG_DIR/$TASK.codex.txt. FINDINGS were auto-ingested into the knowledge store above; call knowledge_write yourself only for something that came up outside that block." >&2
fi
exit 0
