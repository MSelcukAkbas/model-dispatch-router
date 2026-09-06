#!/bin/bash
# Usage: status.sh <task-slug>
# Exit codes: 0 done-success | 10 running | 11 not found | 14 timeout |
#             17 quota exhausted mid-run (not a task bug — reschedule) |
#             20 per-task --max-budget-usd cap hit (runaway-spend guard —
#                see dispatch.sh's budget-clamp block; resume.sh will halve
#                the budget on retry, not just re-try the same amount) |
#             1 failed (other)
set -uo pipefail
TASK="$1"
REPO_ROOT="$(git rev-parse --show-toplevel)"
LOG_DIR="$REPO_ROOT/.agent-logs"

# claude -p has no fallback for session/weekly cap exhaustion (--fallback-model
# only covers overload/unavailability, not quota) — if the cap is hit mid-run
# the CLI just errors out. Recognize the known error shapes so this doesn't
# get mistaken for a real task failure.
# `\b429\b` (2026-07-30 fix — H5): the old pattern was '429 ' (trailing
# space) — misses "429" at the end of a line/string with no trailing space,
# and this platform is a credits/billing SaaS, so "429" as a raw substring
# risks matching unrelated numeric content too. Word-boundary is tighter
# without losing the real HTTP-429 case.
QUOTA_SIGNATURE='usage limit|rate_limit_error|exceeded your.*(usage|quota)|\b429\b'

# CONFIRMED 2026-07-23 (plt-4-faz2 run): the CLI does NOT write the budget-cap
# message to stderr — it only appears in the stream-json log's terminal
# "result" event as subtype "error_max_budget_usd" and errors:["Reached
# maximum budget ($X)"].
#
# Structured check, not a raw grep (2026-07-30 fix — H5): a plain
# `grep -iE 'cost limit|spending limit|budget.*exceed'` over the ENTIRE
# $TASK.json — which is the full stream-json transcript, every turn's text
# included — false-positives on any billing/credits task whose actual work
# is legitimately talking about cost limits (this platform deducts credits
# per KYC call; a backend task fixing that logic would say exactly these
# words with zero connection to dispatch.sh's own --max-budget-usd cap).
# Parse the JSONL and check ONLY the terminal "result" event's own
# subtype/errors fields — the one place the CLI actually reports this.
check_budget_capped() {
  [ -f "$LOG_DIR/$TASK.json" ] || return 1
  node -e "
const fs = require('fs');
let lines;
try { lines = fs.readFileSync(process.argv[1], 'utf8').split('\n'); } catch { process.exit(1); }
let hit = false;
for (const line of lines) {
  const t = line.trim();
  if (!t) continue;
  let e;
  try { e = JSON.parse(t); } catch { continue; }
  if (e.type !== 'result') continue;
  if (e.subtype === 'error_max_budget_usd') hit = true;
  if (Array.isArray(e.errors) && e.errors.some(x => /max(imum)?\s*budget|budget.*exceed/i.test(String(x)))) hit = true;
}
process.exit(hit ? 0 : 1);
" "$LOG_DIR/$TASK.json" 2>/dev/null
}

# CONFIRMED 2026-08-02 (SDK-34 run): session/weekly cap exhaustion mid-run does
# NOT always write to stderr — observed case wrote nothing to $TASK.err at all,
# the CLI instead emitted a synthetic assistant turn (message.model ===
# "<synthetic>") and terminated with a normal-looking terminal "result" event
# (is_error:true, terminal_reason:"api_error", api_error_status:429, result
# text "You've hit your session limit · resets <time>"). The raw-.err
# QUOTA_SIGNATURE grep above never saw this because there was nothing in
# stderr to match — task fell through to generic exit 1 ("failed"), which
# resume.sh refuses to touch (only resumes 14/17/20), silently discarding a
# task that was mid-progress through no fault of its own. Same discipline as
# check_budget_capped: parse JSONL, check the terminal "result" event's own
# structured fields, not a raw grep over the whole transcript (avoids
# false-positives on tasks whose real work legitimately discusses quotas/limits).
check_quota_exhausted_structured() {
  [ -f "$LOG_DIR/$TASK.json" ] || return 1
  node -e "
const fs = require('fs');
let lines;
try { lines = fs.readFileSync(process.argv[1], 'utf8').split('\n'); } catch { process.exit(1); }
let hit = false;
for (const line of lines) {
  const t = line.trim();
  if (!t) continue;
  let e;
  try { e = JSON.parse(t); } catch { continue; }
  if (e.type !== 'result') continue;
  if (e.api_error_status === 429) hit = true;
  if (e.terminal_reason === 'api_error' && /session limit|usage limit|rate.?limit/i.test(String(e.result || ''))) hit = true;
}
process.exit(hit ? 0 : 1);
" "$LOG_DIR/$TASK.json" 2>/dev/null
}

if [ ! -f "$LOG_DIR/$TASK.pid" ]; then
  echo "not_found: no dispatch record for task '$TASK'"
  exit 11
fi

PID="$(cat "$LOG_DIR/$TASK.pid")"

if [ -f "$LOG_DIR/$TASK.exitcode" ]; then
  CODE="$(cat "$LOG_DIR/$TASK.exitcode")"
  if [ "$CODE" = "0" ]; then
    echo "done: task=$TASK — run collect.sh $TASK"
    exit 0
  elif [ "$CODE" = "124" ]; then
    echo "timeout: task=$TASK — check .agent-logs/$TASK.err"
    exit 14
  elif { [ -f "$LOG_DIR/$TASK.err" ] && grep -qiE "$QUOTA_SIGNATURE" "$LOG_DIR/$TASK.err"; } || check_quota_exhausted_structured; then
    echo "quota_exhausted: task=$TASK — hit session/weekly cap mid-run, not a task bug. Check usage.sh, reschedule after reset, re-dispatch same task-id/prompt (or resume.sh once reset)."
    exit 17
  elif check_budget_capped; then
    echo "budget_capped: task=$TASK — hit its --max-budget-usd runaway guard (see \$TASK.meta for the cap used). resume.sh will apply the progress-based clamp, not just retry the same budget."
    exit 20
  else
    echo "failed: task=$TASK exitcode=$CODE — check .agent-logs/$TASK.err"
    exit 1
  fi
elif kill -0 "$PID" 2>/dev/null; then
  echo "running: task=$TASK pid=$PID"
  exit 10
else
  echo "not_found: process $PID gone and no exitcode written — may have crashed, check .agent-logs/$TASK.err"
  exit 11
fi
