#!/bin/bash
# Usage: wait-quota.sh [account] [max_utilization_pct] [poll_seconds]
#   account              optional local registry name (default: current session
#                        CLAUDE_CONFIG_DIR, same resolution as usage.sh)
#   max_utilization_pct  quota threshold to wait for (default 90) -- blocks
#                        while five_hour.utilization >= this value, exits 0
#                        once it drops back below
#   poll_seconds         polling interval (default 60)
#
# Companion to wait.sh, but waits on ACCOUNT QUOTA instead of a dispatched
# task. dispatch.sh/health.sh already refuse to dispatch when quota_status
# is "high" (>=90%) -- this is what to run instead of guessing a single
# ScheduleWakeup delay blind. Run it through the Bash tool with
# run_in_background:true, then watch it with the Monitor tool -- each
# printed line becomes a notification, so you get a live trickle of
# "still waiting, now at X%" instead of one silent block until the end.
#
# Every time five_hour.utilization crosses a NEW 5-point band since the
# last poll, prints one line -- that's the "warning every 5%" signal.
# Silent polls (no band change) print nothing, so Monitor doesn't spam.
#
# Exit 0: utilization dropped below threshold (quota usable again).
# Exit 1: usage.sh failed (network/credentials/unknown account) -- can't
#   tell where quota stands, don't guess, stop and report.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ACCOUNT="${1:-}"
MAX_PCT="${2:-90}"
POLL="${3:-60}"

LAST_BAND=-1

while true; do
  RAW="$(bash "$SCRIPT_DIR/usage.sh" --raw "$ACCOUNT" 2>&1)"
  CODE=$?
  if [ "$CODE" -ne 0 ]; then
    echo "usage.sh failed (account=${ACCOUNT:-current-claude-session}): $RAW" >&2
    exit 1
  fi

  PARSED="$(node -e "
    const j = JSON.parse(process.argv[1]);
    console.log(j.five_hour.utilization + ' ' + (j.five_hour.resets_at || 'n/a'));
  " "$RAW" 2>&1)"
  if [ $? -ne 0 ]; then
    echo "usage.sh raw output unparseable (account=${ACCOUNT:-current-claude-session}): $PARSED" >&2
    exit 1
  fi
  UTIL="${PARSED%% *}"
  RESETS_AT="${PARSED#* }"

  BAND=$(( ${UTIL%.*} / 5 * 5 ))
  if [ "$BAND" != "$LAST_BAND" ]; then
    echo "kota (account=${ACCOUNT:-current-claude-session}): %${UTIL} kullanildi, sifirlanma: ${RESETS_AT}"
    LAST_BAND="$BAND"
  fi

  BELOW="$(awk -v u="$UTIL" -v m="$MAX_PCT" 'BEGIN{print (u < m) ? "1" : "0"}')"
  if [ "$BELOW" = "1" ]; then
    echo "kota esik altina dustu (%${UTIL} < %${MAX_PCT}) -- devam edilebilir."
    exit 0
  fi

  sleep "$POLL"
done
