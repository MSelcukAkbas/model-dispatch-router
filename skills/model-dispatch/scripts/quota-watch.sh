#!/bin/bash
# Usage: quota-watch.sh [account] [poll_seconds]
#   account       optional accounts.sh registry name (default: ambient
#                 CLAUDE_CONFIG_DIR, same resolution as usage.sh) -- normally
#                 left empty: this watches the ORCHESTRATOR's OWN ambient
#                 quota while it works, not a dispatch target's quota
#                 (that's wait-quota.sh's job).
#   poll_seconds  polling interval (default 300 = 5min -- this is a passive
#                 ambient reminder, not a blocking gate, no need to poll fast)
#
# Does NOT block-until-threshold and does NOT exit on its own (unlike
# wait-quota.sh) -- it just runs for the life of the session, printing a
# line every time five_hour.utilization crosses a NEW 5-point band (up or
# down) since the last poll. Silent polls (no band change) print nothing.
#
# Start once near the top of a long/heavy session: Bash tool with
# run_in_background:true, then watch it with the Monitor tool -- each
# printed line becomes a notification, so the orchestrator gets nudged
# "you're at 35% now... 40%... 45%..." without manually remembering to run
# usage.sh every 15-20 minutes (see SKILL.md "Session Hygiene").
#
# Safety cap: stops after MAX_HOURS (default 8) so a forgotten watcher from
# a finished session doesn't run forever. Exit 0 on cap or usage.sh failure
# -- either way, stop and let the caller decide whether to restart it.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ACCOUNT="${1:-}"
POLL="${2:-300}"
MAX_HOURS="${QUOTA_WATCH_MAX_HOURS:-8}"

DEADLINE=$(( $(date +%s) + MAX_HOURS * 3600 ))
LAST_BAND=-1

while true; do
  if [ "$(date +%s)" -ge "$DEADLINE" ]; then
    echo "quota-watch: ${MAX_HOURS}h safety cap reached, stopping (account=${ACCOUNT:-ambient})."
    exit 0
  fi

  RAW="$(bash "$SCRIPT_DIR/usage.sh" --raw "$ACCOUNT" 2>&1)"
  if [ $? -ne 0 ]; then
    echo "quota-watch: usage.sh failed (account=${ACCOUNT:-ambient}), stopping: $RAW" >&2
    exit 0
  fi

  PARSED="$(node -e "
    const j = JSON.parse(process.argv[1]);
    console.log(j.five_hour.utilization + ' ' + (j.five_hour.resets_at || 'n/a'));
  " "$RAW" 2>&1)"
  if [ $? -ne 0 ]; then
    echo "quota-watch: usage.sh raw output unparseable (account=${ACCOUNT:-ambient}), stopping: $PARSED" >&2
    exit 0
  fi
  UTIL="${PARSED%% *}"
  RESETS_AT="${PARSED#* }"

  BAND=$(( ${UTIL%.*} / 5 * 5 ))
  if [ "$BAND" != "$LAST_BAND" ]; then
    echo "kota (account=${ACCOUNT:-ambient}): %${UTIL} kullanildi, sifirlanma: ${RESETS_AT}"
    LAST_BAND="$BAND"
  fi

  sleep "$POLL"
done
