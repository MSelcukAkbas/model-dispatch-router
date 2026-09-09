#!/bin/bash
# Usage: dispatch.sh <role> <task-id> <prompt-file> [--timeout MINUTES] [--effort LEVEL] [--budget USD] [--account NAME] [--no-worktree]
#   role             backend | design | sdk | general (Sonnet, full write
#                     access — general is the catch-all for docs/config/
#                     GOREV-md edits that don't fit the other three) |
#                     ops (Sonnet, full tool access incl. ssh-mcp — live
#                     jump-server/kubectl diagnostics and explicitly-named
#                     remediation, no repo file edits) |
#                     research (Haiku, Read/Grep/Glob only — cheap scanning) |
#                     judge (Opus, Read/Grep/Glob only — decision-only calls,
#                     give it all context up front, it shouldn't need to
#                     explore). Must match .claude/skills/model-dispatch-router/personas/<role>.md.
#   task-id          IMMUTABLE identifier — use the ticket ID this task closes
#                     (e.g. TASK-121 or TASK-135-TASK-136 for a batch), or
#                     run new-id.sh for a T-NNNNNN id if there's no ticket.
#                     Never rename a task mid-flight — worktree/branch/logs
#                     are all keyed off this exact string.
#   prompt-file      path to the task prompt. Two optional header lines,
#                     each on its own line at the TOP of the file, in any
#                     order:
#                       # GOAL: <one sentence — the single thing this task does>
#                       # FILES: path/one.js,path/two.js
#                     GOAL is REQUIRED — a task must have exactly one
#                     objective; a headless agent cannot ask a clarifying
#                     question back, so resolve every ambiguity yourself (or
#                     ask the user) BEFORE dispatching, not after.
#                     FILES is optional but enables automatic conflict
#                     rejection against other still-active tasks.
#   --timeout        optional, default 25.
#   --effort         optional, overrides the role's default reasoning effort
#                     (low|medium|high|xhigh|max — passed to `claude --effort`).
#                     Role defaults: research=low, general=medium, rest=high,
#                     judge=high (decision-only, worth paying for depth).
#   --budget         optional, human-supplied override for --max-budget-usd.
#                     When set, SKIPS the no-progress clamp/refusal logic
#                     entirely (see "Budget clamp" below) — use this only when
#                     a human has looked at the task and decided the clamp's
#                     diffstat-based progress signal is wrong for this case
#                     (e.g. progress was untracked new files, which the clamp
#                     under-counts — see diffstat comment). Bypasses the exit
#                     19 safety net on purpose; not for routine use.
#   --account        optional, a name from accounts.sh's ACCOUNT_CONFIG_DIR
#                     registry — routes this
#                     dispatch's `claude -p` call at that account's
#                     CLAUDE_CONFIG_DIR (separate credentials/session/quota)
#                     instead of the ambient one. Default "" — leaves
#                     CLAUDE_CONFIG_DIR untouched, i.e. whatever account the
#                     orchestrator itself is currently running under. Unknown
#                     name: exit 1 before anything is dispatched. Recorded in
#                     $TASK.meta (both the name and the resolved dir) so
#                     resume.sh reproduces the SAME account automatically.
#                     Provider-specific accounts may use a compatible endpoint;
#                     accounts.sh's apply_account_extra_env may also export
#                     ANTHROPIC_BASE_URL/_AUTH_TOKEN/_MODEL/_DEFAULT_*_MODEL
#                     provider environment variables. Keep credentials outside
#                     tracked files and choose providers according to task risk.
#   --no-worktree    optional flag to skip `git worktree add` entirely and run
#                     straight in the main checkout (RUN_DIR=$REPO_ROOT), same
#                     as the readonly roles already do. Default "0" (normal
#                     worktree). Needed for any target that a worktree of THIS
#                     repo's HEAD cannot reach, such as ignored content or a
#                     separate nested repository. `git worktree add` only
#                     materializes tracked content. With
#                     no-worktree=1 the dispatched agent's cwd is the real
#                     working tree, so those paths are physically present.
#                     Trade-off: no isolation from concurrent no-worktree
#                     tasks or from the orchestrator's own uncommitted state
#                     in that area (mitigate with # FILES: conflict checks,
#                     same rule as always); diff.sh/apply.sh become no-ops for
#                     this task since there's no separate copy to diff/copy
#                     from — changes are already live on disk, review with
#                     `git -C <path> status/diff` directly. Recorded in
#                     $TASK.meta so resume.sh carries the same mode forward.
#
# Exit codes: 0 dispatched | 1 bad usage/missing files | 12 file conflict |
#             15 quota too high to safely dispatch | 19 refused — no-progress
#             budget clamp exhausted (see "Budget clamp" block below), a
#             human needs to look at this task, not another auto-resume
#
# Launches a headless `claude -p` run in a dedicated git worktree, in the
# background, with full tool authority (bypassPermissions, MCP included) but
# a hard technical block on commit/push/branch-delete/rm -rf. Does not block.
# Does NOT notify when done — pair with wait.sh (see below) if you need a
# real completion notification instead of polling status.sh by hand.
#
# Internal-only env vars (set by resume.sh, never by a normal caller):
#   DISPATCH_RESUME=1              use --resume instead of --session-id —
#                                   continues the ACTUAL prior conversation
#                                   (claude -p persists session state by
#                                   session-id unless --no-session-persistence,
#                                   which this script never passes).
#   DISPATCH_SESSION_ID=<uuid>     which session to resume.
#   DISPATCH_CONFIG_DIR_OVERRIDE=<dir-or-empty>
#                                   reproduces the EXACT CLAUDE_CONFIG_DIR the
#                                   original dispatch used — takes priority
#                                   over the `account` argument (see "Account
#                                   / config-dir resolution" below).
set -uo pipefail

BOOTSTRAP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$BOOTSTRAP_DIR/runtime.sh"
[ "$#" -lt 3 ] || dispatch_bootstrap dispatch.sh "$2" "$@"

if [ "$#" -lt 3 ]; then
  echo "usage: dispatch.sh <role> <task-id> <prompt-file> [--timeout MINUTES] [--effort LEVEL] [--budget USD] [--account NAME] [--no-worktree]" >&2
  exit 1
fi
ROLE="$1"
TASK="$2"
PROMPT_FILE="$3"
shift 3
TIMEOUT_MIN=25
EFFORT_OVERRIDE=""
BUDGET_OVERRIDE=""
ACCOUNT=""
NO_WORKTREE=0
SNAPSHOT=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --timeout) TIMEOUT_MIN="${2:?error: --timeout needs minutes}"; shift 2 ;;
    --effort) EFFORT_OVERRIDE="${2:?error: --effort needs a level}"; shift 2 ;;
    --budget) BUDGET_OVERRIDE="${2:?error: --budget needs USD}"; shift 2 ;;
    --account) ACCOUNT="${2:?error: --account needs a name}"; shift 2 ;;
    --no-worktree) NO_WORKTREE=1; shift ;;
    --snapshot) SNAPSHOT=1; shift ;;
    --worktree) NO_WORKTREE=0; shift ;;
    --) shift; break ;;
    *) echo "error: unknown argument '$1'. Optional positional arguments are no longer supported; use named flags." >&2; exit 1 ;;
  esac
done
[ "$#" -eq 0 ] || { echo "error: unexpected trailing argument '$1'" >&2; exit 1; }
[ "$SNAPSHOT:$NO_WORKTREE" != '1:1' ] || { echo 'error: --snapshot conflicts with --no-worktree' >&2; exit 1; }
[[ "$TIMEOUT_MIN" =~ ^[1-9][0-9]*$ ]] || { echo 'error: timeout must be positive integer minutes' >&2; exit 1; }

REPO_ROOT="$(git rev-parse --show-toplevel)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/scope.sh"
source "$SCRIPT_DIR/dispatch-common.sh"
# Extra accounts are local-only; without --account, use the invoking user's
# current Claude session. account-registry.sh never ships private registries.
source "$SCRIPT_DIR/account-registry.sh"
PERSONA_FILE="$SCRIPT_DIR/../personas/$ROLE.md"
WORKTREE_DIR="$REPO_ROOT/.worktrees/$TASK"
BRANCH="agent/$TASK"
LOG_DIR="$REPO_ROOT/.agent-logs"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
command -v "$CLAUDE_BIN" >/dev/null 2>&1 || { echo "error: Claude executable not found: $CLAUDE_BIN" >&2; exit 1; }

# --- Account / config-dir resolution (multi-account dispatch) ---
# DISPATCH_CONFIG_DIR_OVERRIDE (resume.sh only) reproduces the EXACT
# CLAUDE_CONFIG_DIR the original dispatch used — `claude --resume
# <session-id>` only finds that session under the config dir it was created
# in, so a resume must not re-derive this from the (possibly stale, possibly
# since-changed) account name or from whatever this shell's OWN ambient env
# happens to be right now. Checked via `+set` (not `-n`) because "" is a
# meaningful value here: it means the original dispatch ran under the plain
# ambient/default account, which a resume must reproduce by leaving
# CLAUDE_CONFIG_DIR unset too — not by inheriting today's ambient value.
if [ "${DISPATCH_CONFIG_DIR_OVERRIDE+set}" = "set" ]; then
  TARGET_CONFIG_DIR="$DISPATCH_CONFIG_DIR_OVERRIDE"
elif [ -n "$ACCOUNT" ]; then
  TARGET_CONFIG_DIR="$(resolve_account_config_dir "$ACCOUNT")" || exit 1
else
  TARGET_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-}"
fi

# Prefix-match denylist, NOT a sandbox (2026-07-30 clarified — H4). --rf
# variant ordering matters to the prefix matcher: `rm -fr*` and `rm -f -r*`
# are distinct strings from `rm -rf*`/`rm -r -f*` and weren't covered before
# — added. Still not exhaustive (`git -C x commit`, `sh -c "git push"`, any
# flag ordering we haven't enumerated all dodge a plain string-prefix match)
# — same honest caveat personas/ops.md already states for its SSH commands.
# The real backstop is diff review before apply.sh, not this list.
DISALLOWED="Bash(git commit*),Bash(git push*),Bash(rm -rf*),Bash(rm -r -f*),Bash(rm -fr*),Bash(rm -f -r*),Bash(git branch -D*),Bash(git branch --delete --force*),Bash(git worktree remove*),Bash(git reset --hard*),Bash(git clean*)"

# Role -> model (cost/capability match to the job):
#   backend/design/sdk  write code, need full Sonnet capability
#   research            read-only scan/search, cheap model is enough
#   judge                decision-only, no exploration expected — pay for the
#                        best reasoning since it's a single short call
declare -A ROLE_MODEL=(
  [backend]="sonnet-5"
  [design]="sonnet-5"
  [sdk]="sonnet-5"
  [general]="sonnet-5"
  [ops]="sonnet-5"
  [research]="haiku"
  [judge]="opus-4.8"
)
# Roles restricted to structurally-cannot-write tools (no Edit/Write/Bash at
# all — stronger than the commit/push/delete denylist used for the writer
# roles, because there's nothing to deny, the tools to do it aren't there).
declare -A ROLE_READONLY=(
  [research]="true"
  [judge]="true"
)
# Independent of ROLE_READONLY (2026-08-23 refactor — the two used to be the
# same boolean, which meant readonly roles structurally could not reach the
# agent-bridge MCP server — no ask_orchestrator, no submit_result, and (once
# added) no knowledge_write/knowledge_search. research/judge are the two
# roles the shared-knowledge design most needs bridge access from (research
# produces findings, judge resolves conflicts) — splitting this into its own
# flag lets a role be read-only on repo files (no Edit/Write/Bash) while
# still reaching the bridge, without touching the commit/push denylist logic
# writer roles use. All current roles get it; the flag exists so a future
# role can be excluded without re-entangling it with file-write permissions.
declare -A ROLE_BRIDGE=(
  [backend]="true"
  [design]="true"
  [sdk]="true"
  [general]="true"
  [ops]="true"
  [research]="true"
  [judge]="true"
)
# MCP tool names the agent-bridge server exposes, in `mcp__<server>__<tool>`
# form — needed verbatim here because readonly roles use an ALLOWLIST
# (--tools) rather than the writer roles' DENYLIST (--disallowedTools), so
# bridge tools must be named explicitly or the allowlist silently blocks
# them even with the MCP server configured and connected.
BRIDGE_TOOL_NAMES="mcp__agent-bridge__ask_orchestrator,mcp__agent-bridge__submit_result,mcp__agent-bridge__list_pending_questions,mcp__agent-bridge__answer_question,mcp__agent-bridge__get_result,mcp__agent-bridge__knowledge_write,mcp__agent-bridge__knowledge_search"
AGENTMIND_TOOL_NAMES="mcp__agentmind__memory_status_tool,mcp__agentmind__memory_context,mcp__agentmind__memory_for_file"
MODEL="${ROLE_MODEL[$ROLE]:-sonnet-5}"

# Role -> default reasoning effort. research is cheap-scan-only (Haiku, no
# deep reasoning needed); general is docs/config busywork; everything else
# (real code, or judge's single high-stakes decision) defaults to high.
declare -A ROLE_EFFORT=(
  [backend]="high"
  [design]="high"
  [sdk]="high"
  [general]="medium"
  [ops]="high"
  [research]="low"
  [judge]="high"
)

# Optional project configuration. A checked-in `.model-dispatch-router.json` can
# override roles, models, budgets, personas and the optional ops MCP config
# without editing this reusable skill.
ROLE_CONFIG_JSON="$(node "$SCRIPT_DIR/role-config.js" "$ROLE" "$REPO_ROOT" "$SCRIPT_DIR/..")" || exit $?
MODEL="$(node -e "process.stdout.write(String(JSON.parse(process.argv[1]).model))" "$ROLE_CONFIG_JSON")"
ROLE_EFFORT[$ROLE]="$(node -e "process.stdout.write(String(JSON.parse(process.argv[1]).effort))" "$ROLE_CONFIG_JSON")"
ROLE_READONLY[$ROLE]="$(node -e "process.stdout.write(String(JSON.parse(process.argv[1]).readonly))" "$ROLE_CONFIG_JSON")"
ROLE_BRIDGE[$ROLE]="$(node -e "process.stdout.write(String(JSON.parse(process.argv[1]).bridge))" "$ROLE_CONFIG_JSON")"
ROLE_MAX_BUDGET="$(node -e "process.stdout.write(String(JSON.parse(process.argv[1]).maxBudgetUsd))" "$ROLE_CONFIG_JSON")"
PERSONA_FILE="$(node -e "process.stdout.write(String(JSON.parse(process.argv[1]).persona))" "$ROLE_CONFIG_JSON")"
OPS_MCP_CONFIG="$(node -e "process.stdout.write(JSON.parse(process.argv[1]).opsMcpConfig || '')" "$ROLE_CONFIG_JSON")"
EFFORT="${EFFORT_OVERRIDE:-${ROLE_EFFORT[$ROLE]:-high}}"
case "$EFFORT" in
  low|medium|high|xhigh|max) ;;
  *) echo "error: invalid effort '$EFFORT' — must be low|medium|high|xhigh|max" >&2; exit 1 ;;
esac

if [ ! -f "$PERSONA_FILE" ]; then
  echo "error: no persona file for role '$ROLE' at $PERSONA_FILE" >&2
  exit 1
fi
if [ ! -f "$PROMPT_FILE" ]; then
  echo "error: prompt file not found: $PROMPT_FILE" >&2
  exit 1
fi

mkdir -p "$LOG_DIR" "$REPO_ROOT/.worktrees"

# --- Quota pre-check --- (targets $TARGET_CONFIG_DIR's account, not
# necessarily the orchestrator's own — resolved above)
QUOTA_JSON="$(CLAUDE_CONFIG_DIR="$TARGET_CONFIG_DIR" bash "$SCRIPT_DIR/usage.sh" --raw 2>/dev/null || true)"
if [ -n "$QUOTA_JSON" ]; then
  read -r QUOTA_PCT QUOTA_RESET_MIN <<< "$(echo "$QUOTA_JSON" | node -e "
let d='';process.stdin.on('data',c=>d+=c);
process.stdin.on('end',()=>{
  try {
    const j = JSON.parse(d);
    const pct = j.five_hour.utilization;
    const mins = j.five_hour.resets_at ? Math.round((new Date(j.five_hour.resets_at) - new Date()) / 60000) : '?';
    console.log(pct + ' ' + mins);
  } catch (e) { console.log(' '); }
});
" 2>/dev/null)"
  if [ -n "$QUOTA_PCT" ] && awk -v p="$QUOTA_PCT" 'BEGIN{exit !(p>=90)}'; then
    echo "refused: account=${ACCOUNT:-current-claude-session} session quota at ${QUOTA_PCT}% — too high to safely dispatch. Resets in ~${QUOTA_RESET_MIN} minute(s). Call ScheduleWakeup for ~$((QUOTA_RESET_MIN + 2)) minutes and retry then — do not dispatch now." >&2
    exit 15
  fi
else
  echo "warning: could not check quota for account=${ACCOUNT:-current-claude-session} before dispatch (usage.sh failed) — proceeding anyway, watch manually." >&2
fi

# --- GOAL header (required) + FILES header (optional) ---
GOAL_LINE="$(dispatch_common_require_goal "$PROMPT_FILE" "no ambiguity for the agent to resolve on its own")" || exit 1

FILES_LINE="$(grep -m1 '^# FILES:' "$PROMPT_FILE" || true)"
if [ -n "$FILES_LINE" ]; then
  dispatch_common_build_scope "$LOG_DIR" "$TASK" "$SCRIPT_DIR" "${FILES_LINE#"# FILES:"}" || exit $?
elif [ "${ROLE_READONLY[$ROLE]:-false}" != "true" ]; then
  echo "error: writer roles require a non-empty '# FILES:' header; it is enforced by diff.sh/apply.sh." >&2
  exit 1
fi

# Persist the ORIGINAL prompt (with headers) + role/timeout/effort permanently
# — resume.sh needs these to re-dispatch this exact task unchanged after a
# quota reset, without the caller having to remember/re-type them.
if [ ! "$PROMPT_FILE" -ef "$LOG_DIR/$TASK.prompt.orig" ]; then
  cp "$PROMPT_FILE" "$LOG_DIR/$TASK.prompt.orig"
fi

# --- Session identity (resume.sh support) ---
# DISPATCH_RESUME=1 + DISPATCH_SESSION_ID=<uuid> are set by resume.sh, never
# by a normal caller. `claude -p` persists conversation state per session-id
# (unless --no-session-persistence, which we never pass) — so a genuine
# resume can hand the SAME session-id back with --resume and get the real
# prior conversation continued, not just a fresh run pointed at the same
# worktree. A fresh dispatch always mints a new session-id.
RESUME_MODE="${DISPATCH_RESUME:-0}"
if [ "$RESUME_MODE" = "1" ]; then
  if [ -z "${DISPATCH_SESSION_ID:-}" ]; then
    echo "error: DISPATCH_RESUME=1 requires DISPATCH_SESSION_ID (resume.sh should have set this from \$TASK.meta)" >&2
    exit 1
  fi
  SESSION_ID="$DISPATCH_SESSION_ID"
  SESSION_FLAGS=(--resume "$SESSION_ID")
else
  SESSION_ID="$(node -e "console.log(require('crypto').randomUUID())")"
  SESSION_FLAGS=(--session-id "$SESSION_ID")
fi

{
  echo "role=$ROLE"
  echo "timeout_min=$TIMEOUT_MIN"
  echo "effort=$EFFORT"
  echo "session_id=$SESSION_ID"
  echo "no_worktree=$NO_WORKTREE"
  echo "snapshot=$SNAPSHOT"
  echo "account=$ACCOUNT"
  echo "config_dir=$TARGET_CONFIG_DIR"
} > "$LOG_DIR/$TASK.meta"
# max_budget_usd/attempt appended separately below, after the budget-clamp
# block runs (it needs RUN_DIR/WORKTREE_DIR, computed further down).

# Strip header lines before handing the prompt to claude; keep the rest.
CLEAN_PROMPT_FILE="$LOG_DIR/$TASK.prompt.tmp"
grep -v -e '^# GOAL:' -e '^# FILES:' "$PROMPT_FILE" > "$CLEAN_PROMPT_FILE"

# Read-only roles (research/judge) have no Edit/Write/Bash — structurally
# cannot touch a file even by accident — so a dedicated worktree buys zero
# isolation for them, only disk+IO cost for a full working-tree checkout in
# what's often a large monorepo. Run them straight in the main checkout.
if [ "${ROLE_READONLY[$ROLE]:-false}" = "true" ]; then
  RUN_DIR="$REPO_ROOT"
elif [ "$NO_WORKTREE" = "1" ]; then
  echo "note: no-worktree=1 — running '$TASK' directly in the main checkout ($REPO_ROOT), no isolated worktree/branch created." >&2
  RUN_DIR="$REPO_ROOT"
  # Baseline the declared scope now, before the agent touches anything, so
  # diff.sh can later report what actually changed in THIS run instead of
  # just "what's dirty right now" (which may include state that predates this
  # dispatch or a concurrent actor's edits — no-worktree has no isolation from
  # either). Writer roles always have a non-empty scope manifest by this point
  # (enforced above); an empty/missing one just yields an empty baseline.
  # A resumed task must keep the snapshot from its first attempt. Replacing it
  # here would hide changes made before the budget/timeout interruption.
  if [ "${ROLE_READONLY[$ROLE]:-false}" != "true" ] && [ ! -f "$LOG_DIR/$TASK.no-worktree-baseline" ]; then
    scope_snapshot "$REPO_ROOT" "$LOG_DIR/$TASK.scope" > "$LOG_DIR/$TASK.no-worktree-baseline"
  fi
else
  # Exit code checked explicitly (2026-07-30 fix — H3): with only
  # `set -uo pipefail` (no `-e`), a failed `git worktree add` (e.g. branch
  # "agent/$TASK" already exists from a prior failed/not-yet-cleaned-up run)
  # used to fall through silently — RUN_DIR still got set to a worktree dir
  # that was never created, and the exec subshell's `cd` into it would then
  # land wherever the CALLER's cwd happened to be (often the main checkout),
  # handing a supposedly-isolated bypassPermissions run full write access to
  # the real working tree instead. Refuse instead of silently downgrading
  # isolation.
  dispatch_common_ensure_worktree "$REPO_ROOT" "$WORKTREE_DIR" "$BRANCH" || exit 1
  RUN_DIR="$WORKTREE_DIR"
fi

if [ "$SNAPSHOT" = 1 ] && [ ! -f "$LOG_DIR/$TASK.snapshot.json" ]; then
  [ "$RUN_DIR" = "$WORKTREE_DIR" ] || { echo 'error: --snapshot requires a writer worktree' >&2; exit 1; }
  node "$SCRIPT_DIR/snapshot.js" prepare "$REPO_ROOT" "$WORKTREE_DIR" "$LOG_DIR/$TASK.scope" "$LOG_DIR/$TASK.snapshot.json" || exit $?
fi

# --- Budget clamp (2026-07-17, judge-designed policy — see SKILL.md "Kaçak
# kota yakımı" section) ---
# Seed per-role dollar caps, derived from observed total_cost_usd across
# this session's dispatches (~2.5-3x the worst legitimate run seen so far —
# n is still small, these are backstops against runaway loops, not tight
# budgets). `claude -p --max-turns` does NOT exist in this CLI version
# (verified via `claude -p --help` before relying on it) — `--max-budget-usd`
# does, and caps spend directly, which is what we actually care about.
declare -A ROLE_MAX_BUDGET_USD=(
  [backend]="1.50"
  [design]="2.50"
  [sdk]="2.00"
  [general]="1.00"
  [ops]="2.00"
  [research]="0.50"
  [judge]="1.50"
)
SEED_BUDGET="$ROLE_MAX_BUDGET"

# ATTEMPT/diffstat persistence delayed until AFTER the clamp decision below
# (2026-07-30 fix — H9): this used to write $TASK.attempt (and, further
# down, $TASK.diffstat) unconditionally BEFORE deciding whether to actually
# launch — so a refused dispatch (exit 19, no run ever happened) still
# advanced the attempt counter. A human fixing the root cause and
# re-dispatching the same task-id would then land on an already-inflated
# attempt number and could get clamped/refused again immediately, even
# though only a fraction of that many runs had actually executed. Read the
# PREVIOUS attempt count here (still needed for the decision below) but only
# persist the NEW one on a path that actually launches.
PREV_ATTEMPT=0
[ -f "$LOG_DIR/$TASK.attempt" ] && PREV_ATTEMPT="$(cat "$LOG_DIR/$TASK.attempt")"
ATTEMPT=$((PREV_ATTEMPT + 1))

if [ "${ROLE_READONLY[$ROLE]:-false}" = "true" ] || [ "$NO_WORKTREE" = "1" ]; then
  # No worktree/diff to measure progress against — keep it simple, flat
  # seed budget every time. Readonly roles are cheap/short-lived by design;
  # no-worktree writer tasks lose the progress-based clamp/halving as a
  # trade-off (there's no isolated diff base to measure "did this attempt
  # actually move forward" against — REPO_ROOT's working tree may carry
  # unrelated changes too) — same trade-off called out in dispatch.sh's
  # no-worktree usage comment, not a gap that snuck in unnoticed.
  MAX_BUDGET="${BUDGET_OVERRIDE:-$SEED_BUDGET}"
else
  # Progress signal: did the LAST attempt actually change anything in the
  # worktree since the attempt before it? Measured via total changed lines
  # (git diff --numstat sum) PLUS line counts of new untracked files — plain
  # `git diff --numstat` is blind to untracked files (2026-07-26 bug: a task
  # whose entire progress was writing new files read as zero progress every
  # attempt, clamped itself to the floor and then refused, in one resume).
  # Same untracked-blindness apply.sh already works around (see its
  # `--untracked-files=all` comment) — same fix here. If the previous attempt
  # made no measurable progress, this is a loop, not slow-but-working — clamp
  # the budget instead of handing the same full amount to another attempt
  # that's likely to repeat it. If it DID make progress, treat this as a
  # healthy continuation and restore the full seed budget.
  CURRENT_DIFFSTAT=0
  if [ -d "$WORKTREE_DIR" ]; then
    TRACKED_DIFFSTAT="$(git -C "$WORKTREE_DIR" diff --numstat 2>/dev/null | awk '{a+=$1+$2} END{print a+0}')"
    UNTRACKED_DIFFSTAT=0
    while IFS= read -r f; do
      [ -n "$f" ] && [ -f "$WORKTREE_DIR/$f" ] && UNTRACKED_DIFFSTAT=$((UNTRACKED_DIFFSTAT + $(wc -l < "$WORKTREE_DIR/$f" 2>/dev/null || echo 0)))
    done < <(git -C "$WORKTREE_DIR" status --porcelain --untracked-files=all 2>/dev/null | grep '^??' | cut -c4-)
    CURRENT_DIFFSTAT=$((TRACKED_DIFFSTAT + UNTRACKED_DIFFSTAT))
  fi
  PREV_DIFFSTAT=0
  [ -f "$LOG_DIR/$TASK.diffstat" ] && PREV_DIFFSTAT="$(cat "$LOG_DIR/$TASK.diffstat")"
  NEW_DIFFSTAT="$CURRENT_DIFFSTAT"

  if [ -n "$BUDGET_OVERRIDE" ]; then
    MAX_BUDGET="$BUDGET_OVERRIDE"
    echo "note: manual budget override for '$TASK' — using \$$MAX_BUDGET, skipping no-progress clamp/refusal (human call)" >&2
  elif [ "$ATTEMPT" -le 1 ]; then
    MAX_BUDGET="$SEED_BUDGET"
  elif [ "$CURRENT_DIFFSTAT" -gt "$PREV_DIFFSTAT" ]; then
    MAX_BUDGET="$SEED_BUDGET"
  elif [ "$ATTEMPT" -eq 2 ]; then
    MAX_BUDGET="$(awk -v b="$SEED_BUDGET" 'BEGIN{printf "%.2f", b*0.5}')"
  elif [ "$ATTEMPT" -eq 3 ]; then
    MAX_BUDGET="$(awk -v b="$SEED_BUDGET" 'BEGIN{printf "%.2f", b*0.25}')"
  else
    echo "refused: task '$TASK' stuck — attempt $ATTEMPT with zero worktree progress since the last recorded diff (seed budget \$$SEED_BUDGET already halved/quartered twice). This is a runaway loop, not a slow-but-working task — needs human review, not another auto-resume. Check diff.sh/collect.sh, fix the prompt or worktree state by hand." >&2
    exit 19
  fi
fi

# Persist attempt/diffstat only once we've actually decided to launch — the
# exit-19 refusal above returns before reaching this point, so a refused
# dispatch leaves both counters exactly as they were (see H9 comment above).
echo "$ATTEMPT" > "$LOG_DIR/$TASK.attempt"
[ -n "${NEW_DIFFSTAT:-}" ] && echo "$NEW_DIFFSTAT" > "$LOG_DIR/$TASK.diffstat"

{
  echo "max_budget_usd=$MAX_BUDGET"
  echo "attempt=$ATTEMPT"
} >> "$LOG_DIR/$TASK.meta"

# --- MCP scoping (2026-07-17, measured — see SKILL.md "Token tasarrufu") ---
# Measured via two real `claude -p` calls (default vs --strict-mcp-config,
# otherwise identical flags): writer-role cache_creation_input_tokens dropped
# 42180 -> 26911 (~15.3K tokens/dispatch) with no MCP servers loaded — this
# environment's only configured MCP server is ssh-mcp, everything else
# contributing those tokens (Playwright plugin, etc.) is irrelevant to a
# headless coding task. readonly roles (research/judge) showed NO measurable
# difference (--tools allowlist already excludes MCP schemas for them) —
# --strict-mcp-config added anyway for clarity/defense-in-depth, it's a
# verified no-op there, not a guess. `ops` additionally needs ssh-mcp (live
# jump-server/kubectl work) — it gets that one back explicitly, nothing else.
#
# agent-bridge (2026-07-21): writer roles also get a scoped inter-agent
# comms MCP server — ask_orchestrator/submit_result tools so a dispatched
# agent can ask a blocking question instead of guessing, and hand back a
# structured final report instead of free-text. Not wired for readonly
# roles (research/judge) yet — they have no Edit/Write/Bash to begin with
# and their persona explicitly expects zero back-and-forth (all context
# given up front), so the extra channel has no clear use there yet.
#
# Per-task dynamic config (2026-07-30 fix — H1). The former static
# mcp-bridge-only.json/settings-enforce-result.json files hardcoded an
# ABSOLUTE path to this skill's own agent-bridge.js/enforce-submit-result.js.
# This skill can be copied between repositories while static files still point
# at the first repository's copy. Every dispatch from the second repo would then
# wrote its bridge state (.bridge.json/.stophook-count/.result-missing) into
# the WRONG repo's .agent-logs/, invisible to cleanup.sh and to whoever's
# actually looking in THIS repo's .agent-logs/. Generating
# a fresh per-task config from $SCRIPT_DIR (always resolves to THIS repo,
# wherever the skill physically lives) eliminates the whole bug class rather
# than just re-pointing the static files at today's repo. `pwd -W` gets a
# Windows-style (C:/...) path — required because these paths end up inside
# JSON consumed directly by node's child_process.spawn (no shell/MSYS argv
# translation applies to file CONTENTS, only to args on a command line).
if [ "${ROLE_BRIDGE[$ROLE]:-false}" = "true" ]; then
  WIN_BRIDGE_DIR="$(cd "$SCRIPT_DIR/../mcp/bridge" 2>/dev/null && { pwd -W 2>/dev/null || pwd; })"
  WIN_SCRIPTS_DIR="$(cd "$SCRIPT_DIR" 2>/dev/null && { pwd -W 2>/dev/null || pwd; })"
  AGENT_BRIDGE_JS="$WIN_BRIDGE_DIR/agent-bridge.js"
  ENFORCE_HOOK_JS="$WIN_SCRIPTS_DIR/enforce-submit-result.js"

  BRIDGE_CONFIG="$LOG_DIR/$TASK.mcp-bridge.json"
  if command -v agentmind-mcp >/dev/null 2>&1 && [ "${AGENTMIND_DISABLE:-0}" != "1" ]; then
    printf '{"mcpServers":{"agent-bridge":{"command":"node","args":["%s"]},"agentmind":{"command":"agentmind-mcp"}}}\n' "$AGENT_BRIDGE_JS" > "$BRIDGE_CONFIG"
  else
    printf '{"mcpServers":{"agent-bridge":{"command":"node","args":["%s"]}}}\n' "$AGENT_BRIDGE_JS" > "$BRIDGE_CONFIG"
    echo "warning: agentmind-mcp not found; dispatch continues with Agent Bridge only" >&2
  fi

  TASK_SETTINGS="$LOG_DIR/$TASK.settings.json"
  printf '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"node \\"%s\\""}]}]}}\n' "$ENFORCE_HOOK_JS" > "$TASK_SETTINGS"
fi

# Refresh AgentMind and prepare task-specific memory before the conversation.
# This is deterministic shell-owned lifecycle work, not a request that relies
# on the model remembering to call a tool.  Failure is deliberately fail-open:
# dispatch still runs, but no context file is injected.
AGENTMIND_CONTEXT_FILE="$LOG_DIR/$TASK.agentmind-context.md"
# Archive the previous lifecycle files before creating this run's context.
# The general stale-artifact guard runs later, after the persona is assembled,
# and must not move these newly-created files out from under the current run.
TS_AGENTMIND="$(date +%s)"
for ext in agentmind-context.md agentmind-start.log agentmind-end.log; do
  [ -f "$LOG_DIR/$TASK.$ext" ] && mv "$LOG_DIR/$TASK.$ext" "$LOG_DIR/$TASK.$ext.prev-$TS_AGENTMIND"
done
if command -v am >/dev/null 2>&1 && [ "${AGENTMIND_DISABLE:-0}" != "1" ]; then
  am session-start "$TASK" \
    --role "$ROLE" \
    --src "$REPO_ROOT" \
    --query "${GOAL_LINE#"# GOAL:"}" \
    --out "$AGENTMIND_CONTEXT_FILE" \
    > "$LOG_DIR/$TASK.agentmind-start.log" 2>&1 || true
else
  : > "$AGENTMIND_CONTEXT_FILE"
fi

if [ "${ROLE_BRIDGE[$ROLE]:-false}" != "true" ]; then
  MCP_ARGS=(--strict-mcp-config)
elif [ "$ROLE" = "ops" ] && [ -n "$OPS_MCP_CONFIG" ]; then
  MCP_ARGS=(--strict-mcp-config --mcp-config "$OPS_MCP_CONFIG" "$BRIDGE_CONFIG")
else
  if [ "$ROLE" = "ops" ]; then
    # opsMcpConfig is opt-in per repo (.model-dispatch-router.json) since remote
    # access tooling is machine/project-specific and must not be hardcoded
    # into this shared skill. Silently falling through to the bridge-only
    # config would dispatch an ops task with no way to reach the infrastructure
    # it was asked to diagnose — the agent would discover this only by
    # failing partway through, not from anything the dispatcher told it.
    echo "warning: role=ops but no opsMcpConfig is set in .model-dispatch-router.json — dispatching with NO remote-access MCP server (bridge only). Set opsMcpConfig if this task needs infrastructure tools." >&2
  fi
  MCP_ARGS=(--strict-mcp-config --mcp-config "$BRIDGE_CONFIG")
fi

# Stop hook (2026-07-21): bridge'e erişimi olan roller için turu bitirmeden
# submit_result çağırmayı ZORUNLU kılar — bkz. enforce-submit-result.js.
# --settings "additional settings" yükler (proje/kullanıcı settings'ini
# REPLACE etmez), sadece bu dispatch'e scoped. TASK_SETTINGS de per-task
# dinamik üretiliyor, aynı H1 gerekçesiyle (yukarı bkz.). 2026-08-23: gating
# ROLE_READONLY yerine ROLE_BRIDGE'e taşındı — research/judge artık bridge'e
# bağlı olduğu için onlar da submit_result'a (dolayısıyla findings[]'e)
# zorlanıyor, salt-okunur dosya erişimleri değişmedi.
if [ "${ROLE_BRIDGE[$ROLE]:-false}" != "true" ]; then
  SETTINGS_ARGS=()
else
  SETTINGS_ARGS=(--settings "$TASK_SETTINGS")
fi

# Install checkpoint persistence for every role, including bridge-free tasks.
WIN_SCRIPTS_DIR="$(cd "$SCRIPT_DIR" && { pwd -W 2>/dev/null || pwd; })"
TASK_SETTINGS="$LOG_DIR/$TASK.settings.json"
node -e '
const fs = require("fs");
const [file, scripts, bridge] = process.argv.slice(1);
const command = name => "node " + JSON.stringify(scripts + "/" + name);
const hooks = {PostToolUse: [{matcher: ".*", hooks: [{type: "command", command: command("checkpoint-hook.js")}]}]};
if (bridge === "true") hooks.Stop = [{hooks: [{type: "command", command: command("enforce-submit-result.js")}]}];
fs.writeFileSync(file, JSON.stringify({hooks}));
' "$TASK_SETTINGS" "$WIN_SCRIPTS_DIR" "${ROLE_BRIDGE[$ROLE]:-false}" || exit 1
SETTINGS_ARGS=(--settings "$TASK_SETTINGS")

PERSONA="$(cat "$PERSONA_FILE")

Task ID: $TASK — immutable, do not rename it in your report.
Single goal, nothing else: ${GOAL_LINE#"# GOAL:"}
Never attempt commit/push/delete — technically blocked, don't waste a turn trying."

PERSONA="$PERSONA

Checkpoint protocol: after each meaningful work unit, emit a short CHECKPOINT text with findings, changed paths, verification completed, and remaining work. Keep a deliverable summary current from the first unit onward. Reserve the last 15 percent of your allotted effort for verification and the final result. If interrupted or unable to finish, submit_result with status PARTIAL or BLOCKED and an honest summary; do not claim DONE. Budget cap for this attempt: USD $MAX_BUDGET."

if [ -s "$AGENTMIND_CONTEXT_FILE" ]; then
  PERSONA="$PERSONA

# AgentMind context
This context was selected automatically from the code graph and prior agent
claims. Candidate claims are leads, not verified facts; check them against the
working tree before relying on them.

$(cat "$AGENTMIND_CONTEXT_FILE")"
fi

if [ "$RESUME_MODE" = "1" ]; then
  # Real conversation continuation via --resume — don't re-send the full
  # original task text as a second "new" request, that reads as a duplicate
  # instruction to a model that already has the prior turns in context.
  # A short nudge is enough; it already remembers what it was doing.
  PROMPT="Kesintiye uğradın (kota/timeout dolayısıyla oturum yarıda kesildi). Worktree'deki mevcut dosya durumunu kontrol et, kaldığın yerden devam et, orijinal hedefi tamamla: ${GOAL_LINE#"# GOAL:"}"
  if [ -n "${DISPATCH_RESUME_AMEND_FILE:-}" ]; then
    if [ ! -f "$DISPATCH_RESUME_AMEND_FILE" ]; then
      echo "error: resume amendment not found: $DISPATCH_RESUME_AMEND_FILE" >&2
      exit 1
    fi
    PROMPT="$PROMPT

Ek, daha sonraki orkestratör talimatı (orijinal hedefi değiştirmez):
$(cat "$DISPATCH_RESUME_AMEND_FILE")"
  fi
else
  PROMPT="$(cat "$CLEAN_PROMPT_FILE")"
fi

# --- Stale-artifact guard (2026-07-27 bug fix) ---
# resume.sh archives the previous attempt's .json/.err/.exitcode/.pid before
# calling this script — but resume.sh only accepts tasks in states 17/14/20
# (quota/timeout/budget-capped). A task that failed some OTHER way (e.g. an
# instant transient spawn failure, exit 127, before a single turn ran) is not
# resumable, so the only path forward is calling dispatch.sh directly again
# on the same task-id — and this script used to leave the dead attempt's
# .exitcode/.pid/.err/.json sitting on disk untouched until ITS OWN
# completion overwrote them. status.sh reads .exitcode unconditionally as
# its FIRST check (no liveness check), so in the window between this dispatch
# and its real completion, status.sh reported the STALE prior result (e.g.
# that instant exit 127) as if it belonged to the new, genuinely-running
# process — confirmed live 2026-07-27 (T-000013: `kill -0` showed the pid
# alive and the transcript showed real tool calls, while status.sh insisted
# "failed"). Fix: do the same archive-before-relaunch resume.sh already does,
# here too, so any direct re-dispatch is equally safe regardless of caller.
# The bootstrap uses the run UUID plus process-start identity. Do not re-check
# with kill -0 here: a recycled PID would turn an unrelated process into a
# permanent false "running" task.
# bridge.json/stophook-count/result-missing added (2026-07-30 fix — H2):
# these are the agent-bridge state files a PRIOR run of this same task-id
# left behind (get_result/submit_result state, Stop-hook block counter, the
# "gave up enforcing" marker). Redispatching the same task-id (the normal
# case per SKILL.md's "use the ticket ID as task-id" rule — a ticket can get
# redispatched) used to leave these untouched: get_result(task_id) would
# return the PREVIOUS run's stale DONE/PARTIAL result as if it belonged to
# the new run, and a stophook-count already at MAX_BLOCKS from the earlier
# run would mean the new run's Stop hook never actually enforces
# submit_result again. Archive them alongside json/err/exitcode/pid so a
# same-task-id redispatch starts with a clean bridge slate.
dispatch_common_archive_stale "$LOG_DIR" "$TASK" json err exitcode pid bridge.json stophook-count result-missing run.json final-status.json checkpoint.json

(
  node "$SCRIPT_DIR/lifecycle.js" begin "$LOG_DIR" "$TASK" claude "$BASHPID" "${ROLE_BRIDGE[$ROLE]:-false}" || exit 1
  # cd failure fallback (2026-07-30 fix — H3): without this, a failed cd
  # (RUN_DIR deleted out from under us between computation and launch, a
  # race with a concurrent cleanup.sh) leaves the subshell running in
  # whatever cwd it inherited — often the main checkout — silently handing
  # a bypassPermissions run full write access to the real working tree
  # instead of the isolated worktree it was supposed to get. `exit 1` here
  # only exits this backgrounded subshell, not dispatch.sh itself.
  cd "$RUN_DIR" || { echo "cd to RUN_DIR ($RUN_DIR) failed" >> "$LOG_DIR/$TASK.err"; node "$SCRIPT_DIR/lifecycle.js" finalize "$LOG_DIR" "$TASK" 1; exit 1; }
  export DISPATCH_TASK_ID="$TASK"
  export DISPATCH_REPO_ROOT="$REPO_ROOT"
  export DISPATCH_STARTED_MS="$(node -e 'console.log(Date.now())')"
  export DISPATCH_TIMEOUT_MIN="$TIMEOUT_MIN"
  # agent-bridge.js'in submit_result/knowledge_write'ta source_role'u
  # otomatik doldurması için (2026-08-23) — ajanın ayrıca kendi rolünü
  # belirtmesi gerekmiyor.
  export DISPATCH_ROLE="$ROLE"
  # Scoped to this backgrounded subshell only — does not affect dispatch.sh's
  # own process or any later dispatch. Empty means "leave ambient as-is".
  if [ -n "$TARGET_CONFIG_DIR" ]; then
    export CLAUDE_CONFIG_DIR="$TARGET_CONFIG_DIR"
  fi
  # Compatible third-party provider accounts may also need
  # ANTHROPIC_BASE_URL/_AUTH_TOKEN/_MODEL/_DEFAULT_*_MODEL — see accounts.sh's
  # apply_account_extra_env. No-op (exports nothing) for native Claude
  # ordinary named accounts or the ambient default.
  apply_account_extra_env "$ACCOUNT"
  # stream-json (not json): --output-format json buffers the ENTIRE run and
  # writes one blob only at process exit — if the task is killed mid-flight
  # (timeout, or the orchestrator stopping it for cause), the output file is
  # empty and every turn of work is unrecoverable (found 2026-07-14). stream-json
  # emits one JSON object per turn, flushed as it happens, so $TASK.json always
  # has whatever ran up to the kill point. collect.sh reads this as JSONL and
  # finds the last type:"result" line (same shape the old json-format gave).
  if [ "${ROLE_READONLY[$ROLE]:-false}" = "true" ]; then
    # Structurally read-only: only Read/Grep/Glob (+ bridge MCP tools, when
    # ROLE_BRIDGE=true) exist for this run — no Edit/Write/Bash means no
    # commit/push/delete/edit is even possible, regardless of permission
    # mode. Bridge tools must be named explicitly here (2026-08-23): --tools
    # is an ALLOWLIST, so an MCP server can be fully connected and still be
    # unreachable if its tool names aren't in this string.
    READONLY_TOOLS="Read,Grep,Glob"
    [ "${ROLE_BRIDGE[$ROLE]:-false}" = "true" ] && READONLY_TOOLS="$READONLY_TOOLS,$BRIDGE_TOOL_NAMES"
    if command -v agentmind-mcp >/dev/null 2>&1 && [ "${AGENTMIND_DISABLE:-0}" != "1" ]; then
      READONLY_TOOLS="$READONLY_TOOLS,$AGENTMIND_TOOL_NAMES"
    fi
    # permission-mode bypassPermissions, NOT acceptEdits (2026-08-23 bug fix
    # — found via a real dispatch smoke test): acceptEdits auto-approves file
    # edits but does NOT auto-approve MCP tool calls — in headless mode a
    # call needing approval just gets silently denied (nothing to prompt).
    # Live transcript showed the model calling mcp__agent-bridge__submit_result
    # with a fully correct payload 4 times, denied every time, Stop hook
    # exhausted its 3 retries and gave up (.result-missing). bypassPermissions
    # is safe here because it only removes the approval gate for tools that
    # are ALREADY in --tools — Edit/Write/Bash aren't in the allowlist at all,
    # so bypassPermissions can't grant them; nothing readonly roles couldn't
    # already technically do.
    timeout "${TIMEOUT_MIN}m" "$CLAUDE_BIN" -p "$PROMPT" \
      --append-system-prompt "$PERSONA" \
      --model "$MODEL" \
      --effort "$EFFORT" \
      --max-budget-usd "$MAX_BUDGET" \
      "${SESSION_FLAGS[@]}" \
      "${MCP_ARGS[@]}" \
      "${SETTINGS_ARGS[@]}" \
      --tools "$READONLY_TOOLS" \
      --permission-mode bypassPermissions \
      --output-format stream-json --verbose \
      >> "$LOG_DIR/$TASK.json" 2>> "$LOG_DIR/$TASK.err"
  else
    timeout "${TIMEOUT_MIN}m" "$CLAUDE_BIN" -p "$PROMPT" \
      --append-system-prompt "$PERSONA" \
      --model "$MODEL" \
      --effort "$EFFORT" \
      --max-budget-usd "$MAX_BUDGET" \
      "${SESSION_FLAGS[@]}" \
      "${MCP_ARGS[@]}" \
      "${SETTINGS_ARGS[@]}" \
      --permission-mode bypassPermissions \
      --disallowedTools "$DISALLOWED" \
      --output-format stream-json --verbose \
      >> "$LOG_DIR/$TASK.json" 2>> "$LOG_DIR/$TASK.err"
  fi
  RUN_EXIT="$?"
  node "$SCRIPT_DIR/lifecycle.js" finalize "$LOG_DIR" "$TASK" "$RUN_EXIT"
  RUN_EXIT=$?
  if command -v am >/dev/null 2>&1 && [ "${AGENTMIND_DISABLE:-0}" != "1" ]; then
    case "$RUN_EXIT" in
      0) AGENTMIND_FINAL_STATUS="done" ;;
      124) AGENTMIND_FINAL_STATUS="timeout" ;;
      *) AGENTMIND_FINAL_STATUS="failed" ;;
    esac
    timeout 60s am session-end "$TASK" \
      --role "$ROLE" \
      --src "$REPO_ROOT" \
      --exit-code "$RUN_EXIT" \
      --status "$AGENTMIND_FINAL_STATUS" \
      > "$LOG_DIR/$TASK.agentmind-end.log" 2>&1
    node "$SCRIPT_DIR/lifecycle.js" hook "$LOG_DIR" "$TASK" "$?"
  else
    node "$SCRIPT_DIR/lifecycle.js" hook "$LOG_DIR" "$TASK" 0
  fi
) &

DISPATCH_PID=$!
echo "$DISPATCH_PID" > "$LOG_DIR/$TASK.pid"
if [ "${ROLE_READONLY[$ROLE]:-false}" = "true" ] || [ "$NO_WORKTREE" = "1" ]; then
  echo "dispatched: task=$TASK role=$ROLE model=$MODEL effort=$EFFORT budget=\$$MAX_BUDGET attempt=$ATTEMPT account=${ACCOUNT:-current-claude-session} run_dir=$RUN_DIR(main checkout, no worktree) pid=$DISPATCH_PID timeout=${TIMEOUT_MIN}m"
else
  echo "dispatched: task=$TASK role=$ROLE model=$MODEL effort=$EFFORT budget=\$$MAX_BUDGET attempt=$ATTEMPT account=${ACCOUNT:-current-claude-session} worktree=$WORKTREE_DIR branch=$BRANCH pid=$DISPATCH_PID timeout=${TIMEOUT_MIN}m"
fi
exit 0
