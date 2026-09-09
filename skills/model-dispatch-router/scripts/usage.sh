#!/bin/bash
# Usage: usage.sh [--raw] [account]
#   (no args)  human-readable summary for the CURRENT CLAUDE SESSION account — whatever
#              CLAUDE_CONFIG_DIR the calling shell already has (unset means
#              the plain default account).
#   --raw      print the raw JSON response (for other scripts, e.g. health.sh
#              / dispatch.sh's quota pre-check).
#   account    optional name from accounts.sh's ACCOUNT_CONFIG_DIR registry
#              from accounts.sh — check THAT account's quota instead of
#              the current session. Unknown name: exit 1, no guessing.
#
# Reads the OAuth token from <config-dir>/.credentials.json and queries the
# (undocumented, may break without notice) Anthropic usage endpoint to show
# remaining session (5h) / weekly (7d) quota and reset times — the same data
# the interactive /usage command shows, but callable from a script/headless
# context. Read-only. If this ever 4xx/5xx's, the endpoint likely changed —
# don't guess at quota, just say you can't check it. Exit 1 on any failure.
#
# Fixed 2026-08-02: this used to hardcode ~/.claude regardless of the
# current-session CLAUDE_CONFIG_DIR too — a caller running under a non-default
# account (for example an orchestrator with a custom CLAUDE_CONFIG_DIR)
# would silently have its quota checked against a DIFFERENT (the plain
# default) account's credentials. Confirmed live before fixing. Now: no
# `account` arg given -> respects ambient CLAUDE_CONFIG_DIR if set, else
# falls back to the plain default, same order `claude` itself resolves it.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=account-registry.sh
source "$SCRIPT_DIR/account-registry.sh"

RAW=""
ACCOUNT=""
for arg in "$@"; do
  if [ "$arg" = "--raw" ]; then
    RAW="--raw"
  else
    ACCOUNT="$arg"
  fi
done

OVERRIDE_DIR=""
if [ -n "$ACCOUNT" ]; then
  OVERRIDE_DIR="$(resolve_account_config_dir "$ACCOUNT")" || exit 1
fi

node -e "
const fs = require('fs');
const https = require('https');
const path = require('path');
const os = require('os');

const raw = process.argv[1] === '--raw';
const overrideDir = process.argv[2];
const accountLabel = process.argv[3] || 'current-claude-session';
const configDir = (overrideDir && overrideDir.length) ? overrideDir : (process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), '.claude'));
const credPath = path.join(configDir, '.credentials.json');
let creds;
try {
  creds = JSON.parse(fs.readFileSync(credPath, 'utf8'));
} catch (e) {
  console.error('Cannot read credentials for account=' + accountLabel + ' at ' + credPath + ':', e.message);
  process.exit(1);
}
const token = creds.claudeAiOauth.accessToken;

const req = https.request({
  hostname: 'api.anthropic.com',
  path: '/api/oauth/usage',
  method: 'GET',
  headers: {
    'Authorization': 'Bearer ' + token,
    'anthropic-beta': 'oauth-2025-04-20'
  }
}, res => {
  let data = '';
  res.on('data', d => data += d);
  res.on('end', () => {
    if (res.statusCode !== 200) {
      console.error('Usage endpoint returned', res.statusCode, '— it may have changed. Cannot report quota, do not guess.');
      process.exit(1);
    }
    if (raw) {
      console.log(data);
      return;
    }
    const j = JSON.parse(data);
    const fmtReset = (iso) => {
      if (!iso) return 'n/a';
      const d = new Date(iso);
      const now = new Date();
      const minsLeft = Math.round((d - now) / 60000);
      return d.toISOString() + ' (' + (minsLeft > 0 ? '~' + minsLeft + ' dk sonra' : 'geçti') + ')';
    };
    console.log('== Kota durumu (account=' + accountLabel + ') ==');
    console.log('5 saatlik (session): %' + j.five_hour.utilization + ' kullanıldı — sıfırlanma: ' + fmtReset(j.five_hour.resets_at));
    console.log('7 günlük (weekly):   %' + j.seven_day.utilization + ' kullanıldı — sıfırlanma: ' + fmtReset(j.seven_day.resets_at));
  });
});
req.on('error', e => { console.error('Network error:', e.message); process.exit(1); });
req.end();
" -- "$RAW" "$OVERRIDE_DIR" "${ACCOUNT:-current-claude-session}"
