#!/bin/bash
# Usage: context-usage.sh <session-id> [max-tokens] [account]
#   session-id   the running session's own ID — Claude, you know your own
#                sessionId from tool-result/hook payloads shown to you during
#                this conversation (e.g. paths under
#                .claude/projects/<project>/<session-id>.jsonl). Pass it
#                explicitly; this script does not try to auto-detect it,
#                because multiple Claude Code sessions can be open on the
#                same project at once (confirmed via `claude agents --json`
#                in this repo) and guessing "most recently modified file"
#                could silently report a DIFFERENT session's usage.
#   max-tokens   optional, default 1000000 — this account's Sonnet sessions
#                were observed with a 1M context window (see modelUsage in
#                a claude -p --output-format json response). Override if a
#                different model/tier applies.
#   account      optional name from accounts.sh's ACCOUNT_CONFIG_DIR registry
#                from accounts.sh — look under THAT account's config dir
#                instead of the ambient one. Default "": ambient (whatever
#                CLAUDE_CONFIG_DIR this shell already has, or the plain
#                default if unset). Only relevant if you're checking a
#                session that ran under a non-ambient account — the
#                orchestrator's own session normally matches ambient.
#
# Reads the LAST message.usage entry from this session's own transcript
# (<config-dir>/projects/*/<session-id>.jsonl) and reports approximate
# context window fill — input_tokens + cache_creation_input_tokens +
# cache_read_input_tokens against max-tokens. This is a proxy (the exact
# context accounting Claude Code itself uses may differ slightly) — good
# enough for a "should I checkpoint/compact soon" signal, not a precise
# figure. Read-only.
#
# Fixed 2026-08-02: this used to hardcode ~/.claude/projects regardless of
# the AMBIENT CLAUDE_CONFIG_DIR — confirmed this orchestrator's OWN session
# transcript may live under a custom CLAUDE_CONFIG_DIR/projects directory,
# not ~/.claude/projects, so the old hardcoded path would have found nothing
# for this very session.
set -euo pipefail

SESSION_ID="$1"
MAX_TOKENS="${2:-1000000}"
ACCOUNT="${3:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=accounts.sh
source "$SCRIPT_DIR/accounts.sh"

if [ -n "$ACCOUNT" ]; then
  CONFIG_DIR="$(resolve_account_config_dir "$ACCOUNT")" || exit 1
else
  CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
fi

FILE="$(find "$CONFIG_DIR/projects" -name "${SESSION_ID}.jsonl" 2>/dev/null | head -1)"
if [ -z "$FILE" ]; then
  echo "Session transcript not found for $SESSION_ID under $CONFIG_DIR/projects (account=${ACCOUNT:-ambient}) — wrong ID, wrong account, or transcript not yet written." >&2
  exit 1
fi

node -e "
const fs = require('fs');
const filePath = process.argv[1];
const maxTokens = parseInt(process.argv[2], 10);
const lines = fs.readFileSync(filePath, 'utf8').split('\n');
let lastUsage = null;
for (let i = lines.length - 1; i >= 0; i--) {
  const line = lines[i].trim();
  if (!line) continue;
  try {
    const obj = JSON.parse(line);
    const u = obj.message && obj.message.usage;
    if (u) { lastUsage = u; break; }
  } catch (e) { /* skip malformed/partial lines */ }
}
if (!lastUsage) {
  console.error('No usage data found in this transcript — session may be brand new.');
  process.exit(1);
}
const total = (lastUsage.input_tokens || 0) + (lastUsage.cache_creation_input_tokens || 0) + (lastUsage.cache_read_input_tokens || 0);
const pct = (total * 100 / maxTokens).toFixed(1);
console.log('== Context penceri kullanımı (yaklaşık) ==');
console.log('Toplam: ' + total.toLocaleString() + ' / ' + maxTokens.toLocaleString() + ' token (%' + pct + ')');
if (pct >= 70) {
  console.log('UYARI: %70+ dolu — uzun bir batch dispatch etmeden önce özetleme/checkpoint düşün.');
}
" "$FILE" "$MAX_TOKENS"
