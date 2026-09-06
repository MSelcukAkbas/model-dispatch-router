#!/bin/bash
# Usage: health.sh [account]
#   account   optional name from accounts.sh's ACCOUNT_CONFIG_DIR registry
#             (currently: akb34) — checks THAT account's quota instead of
#             the ambient one. Default "": ambient (whatever CLAUDE_CONFIG_DIR
#             the calling shell already has). Unknown name: exit 1.
# Pre-flight check — run BEFORE dispatch.sh, with the SAME account you intend
# to dispatch to (a multi-account setup can have one account healthy/idle
# while another is capped — check the one you're about to use, not just
# whichever is ambient). Prints a JSON object and exits with a code you can
# branch on without parsing text:
#   0  everything healthy
#   1  a non-quota check failed (git/worktree/claude_cli/disk_space)
#   15 quota check failed specifically (session usage too high)
set -uo pipefail
ACCOUNT="${1:-}"
# shellcheck source=accounts.sh
source "$(cd "$(dirname "$0")" && pwd)/accounts.sh"
if [ -n "$ACCOUNT" ]; then
  # Validate up front — an unknown name must fail loudly (exit 1), not fall
  # through to usage.sh returning empty output and getting misread as
  # "quota unknown, fail open" (a typo'd account name is a usage bug, not a
  # quota-check hiccup).
  resolve_account_config_dir "$ACCOUNT" > /dev/null || exit 1
fi
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "")"

GIT_OK="false"
[ -n "$REPO_ROOT" ] && GIT_OK="true"

WORKTREE_OK="false"
if [ "$GIT_OK" = "true" ]; then
  git -C "$REPO_ROOT" worktree list >/dev/null 2>&1 && WORKTREE_OK="true"
fi

CLI_OK="false"
command -v claude >/dev/null 2>&1 && CLI_OK="true"

DISK_OK="false"
DISK_FREE_MB="0"
if [ -n "$REPO_ROOT" ]; then
  DISK_FREE_KB="$(df -k "$REPO_ROOT" 2>/dev/null | awk 'NR==2{print $4}')"
  if [ -n "${DISK_FREE_KB:-}" ]; then
    DISK_FREE_MB=$((DISK_FREE_KB / 1024))
    [ "$DISK_FREE_MB" -gt 500 ] && DISK_OK="true"  # need >500MB free for a worktree checkout
  fi
fi

# QUOTA_STATUS has three real states (2026-07-30 fix — H6): "ok" | "high" |
# "unknown". The old boolean QUOTA_OK collapsed "usage.sh's endpoint 4xx/5xx'd
# or gave unparseable output" into the SAME false value as "confirmed >=90%
# used" — both fell through to exit 15 ("kota yüksek"). SKILL.md's flow then
# computes `ScheduleWakeup delaySeconds = (quota_resets_in_minutes + 2) * 60`
# off a `null` reset time, i.e. NaN — an endpoint hiccup got misreported as a
# real quota block AND broke the auto-reschedule math built on top of it.
# usage.sh's own rule is "if the endpoint 4xx/5xx's, don't guess quota, just
# say you can't check it" — health.sh used to violate that rule by reporting
# a confident-looking "quota_ok: false". Unknown now fails OPEN (exit 0, like
# dispatch.sh's own pre-check already does on the identical failure — "could
# not check quota... proceeding anyway, watch manually"), with a warning, so
# the two scripts agree instead of one silently blocking dispatch that the
# other would have allowed.
QUOTA_STATUS="unknown"
QUOTA_PCT="null"
QUOTA_RESET_AT="null"
QUOTA_RESET_MIN="null"
QUOTA_JSON="$(bash "$(dirname "$0")/usage.sh" --raw "$ACCOUNT" 2>/dev/null || true)"
if [ -n "$QUOTA_JSON" ]; then
  read -r QUOTA_PCT QUOTA_RESET_AT QUOTA_RESET_MIN <<< "$(echo "$QUOTA_JSON" | node -e "
let d='';process.stdin.on('data',c=>d+=c);
process.stdin.on('end',()=>{
  try {
    const j = JSON.parse(d);
    const pct = j.five_hour.utilization;
    const resetsAt = j.five_hour.resets_at;
    const minsLeft = resetsAt ? Math.round((new Date(resetsAt) - new Date()) / 60000) : 'null';
    console.log(pct + ' ' + resetsAt + ' ' + minsLeft);
  } catch (e) { console.log('null null null'); }
});
" 2>/dev/null)"
  if [ "$QUOTA_PCT" != "null" ] && [ -n "$QUOTA_PCT" ]; then
    if awk -v p="$QUOTA_PCT" 'BEGIN{exit !(p<90)}'; then
      QUOTA_STATUS="ok"
    else
      QUOTA_STATUS="high"
    fi
  fi
fi
QUOTA_OK="false"
[ "$QUOTA_STATUS" = "ok" ] && QUOTA_OK="true"

echo "{"
echo "  \"account\": \"${ACCOUNT:-ambient}\","
echo "  \"git\": $GIT_OK,"
echo "  \"worktree\": $WORKTREE_OK,"
echo "  \"claude_cli\": $CLI_OK,"
echo "  \"disk_space\": $DISK_OK,"
echo "  \"disk_free_mb\": $DISK_FREE_MB,"
echo "  \"quota_ok\": $QUOTA_OK,"
echo "  \"quota_status\": \"$QUOTA_STATUS\","
echo "  \"quota_session_percent\": ${QUOTA_PCT:-null},"
echo "  \"quota_resets_at\": \"${QUOTA_RESET_AT:-null}\","
echo "  \"quota_resets_in_minutes\": ${QUOTA_RESET_MIN:-null}"
echo "}"

if [ "$GIT_OK" != "true" ] || [ "$WORKTREE_OK" != "true" ] || [ "$CLI_OK" != "true" ] || [ "$DISK_OK" != "true" ]; then
  exit 1
fi
if [ "$QUOTA_STATUS" = "high" ]; then
  exit 15
fi
if [ "$QUOTA_STATUS" = "unknown" ]; then
  echo "warning: could not verify quota (usage.sh unavailable or gave unparseable output) — not blocking dispatch (fail-open, matches dispatch.sh's own pre-check), but do not compute a ScheduleWakeup delay off quota_resets_in_minutes here, it's null." >&2
fi
exit 0
