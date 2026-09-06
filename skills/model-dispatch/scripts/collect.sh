#!/bin/bash
# Usage: collect.sh <task-slug>
# Exit codes: 0 ok | 10 still running | 11 not found
set -uo pipefail
TASK="$1"
REPO_ROOT="$(git rev-parse --show-toplevel)"
LOG_DIR="$REPO_ROOT/.agent-logs"

# \b429\b (2026-07-30 fix — same as status.sh's H5 fix): the old '429 '
# (trailing space) pattern misses a bare "429" at end-of-line/string, and a
# raw "429" substring risks false positives on this billing-heavy platform.
QUOTA_SIGNATURE='usage limit|rate_limit_error|exceeded your.*(usage|quota)|\b429\b'

if [ ! -f "$LOG_DIR/$TASK.pid" ]; then
  echo "not_found: no dispatch record for task '$TASK'" >&2
  exit 11
fi
if [ ! -f "$LOG_DIR/$TASK.exitcode" ]; then
  echo "running: task '$TASK' not finished yet" >&2
  exit 10
fi
if [ ! -s "$LOG_DIR/$TASK.json" ]; then
  if [ -f "$LOG_DIR/$TASK.err" ] && grep -qiE "$QUOTA_SIGNATURE" "$LOG_DIR/$TASK.err"; then
    echo "quota_exhausted: task '$TASK' hit session/weekly cap before producing any event — not a task bug, reschedule after reset (see usage.sh)." >&2
    exit 11
  fi
  echo "not_found: no output file for task '$TASK' — killed before it produced any event, nothing recoverable" >&2
  exit 11
fi

if [ -f "$LOG_DIR/$TASK.err" ] && grep -qiE "$QUOTA_SIGNATURE" "$LOG_DIR/$TASK.err"; then
  echo "note: '$TASK.err' contains a quota/rate-limit signature — any PARTIAL result below may be truncated by session/weekly cap exhaustion, not a task bug." >&2
fi

# dispatch.sh runs --output-format stream-json: one JSON object per line,
# flushed as each turn happens. A clean run's last line has type:"result"
# (same shape the old single-blob json format had — .result/.total_cost_usd/
# .num_turns). A run killed mid-flight has no such line — report how far it
# got (turn count + last event's type/tool) instead of nothing.
node -e "
const fs = require('fs');
const lines = fs.readFileSync(process.argv[1], 'utf8').split('\n').map(l => l.trim()).filter(Boolean);
const events = [];
for (const line of lines) {
  try { events.push(JSON.parse(line)); } catch { /* partial/truncated last line — skip */ }
}
console.log('== report ($TASK) ==');
if (events.length === 0) {
  console.log('(no parseable events — output file had ' + lines.length + ' raw line(s), all truncated/unparseable)');
  process.exit(0);
}
const result = [...events].reverse().find(e => e.type === 'result');
if (result) {
  console.log(result.result || '(no result field)');
  console.log();
  console.log('== cost: \$' + (result.total_cost_usd ?? 'unknown') + ' — ' + (result.num_turns ?? '?') + ' turn(s) ==');
} else {
  const last = events[events.length - 1];
  console.log('PARTIAL — killed or crashed mid-flight, no final result. ' + events.length + ' event(s) captured before stopping.');
  console.log('Last event type: ' + last.type + (last.subtype ? (' / ' + last.subtype) : ''));
  if (last.message?.content) {
    const textParts = (Array.isArray(last.message.content) ? last.message.content : [])
      .filter(c => c.type === 'text').map(c => c.text);
    if (textParts.length) console.log('Last message text: ' + textParts.join(' ').slice(0, 2000));
  }
}
" "$LOG_DIR/$TASK.json"
