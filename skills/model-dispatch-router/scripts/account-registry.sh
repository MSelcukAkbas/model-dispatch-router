#!/bin/bash
# Generic account resolution for a distributable Model Dispatch install.
#
# With no --account flag, every command uses the invoking user's current
# Claude session (CLAUDE_CONFIG_DIR when set, otherwise Claude's default).
# Additional accounts are intentionally local-only: they may be declared in
# accounts.local.sh, or in the legacy ignored accounts.sh during migration.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACCOUNT_SOURCE="${DISPATCH_ACCOUNT_SOURCE:-$SCRIPT_DIR}"
if [ -f "$ACCOUNT_SOURCE/accounts.local.sh" ]; then
  # shellcheck source=accounts.local.sh
  source "$ACCOUNT_SOURCE/accounts.local.sh"
elif [ -f "$ACCOUNT_SOURCE/accounts.sh" ]; then
  # Backwards compatibility for existing local installations. This file is
  # ignored and excluded from plugin builds; never add it to Git.
  # shellcheck source=accounts.sh
  source "$ACCOUNT_SOURCE/accounts.sh"
fi

declare -p ACCOUNT_CONFIG_DIR >/dev/null 2>&1 || declare -A ACCOUNT_CONFIG_DIR=()

if ! declare -F resolve_account_config_dir >/dev/null 2>&1; then
  resolve_account_config_dir() {
    local name="$1"
    [ -z "$name" ] && return 0
    if [ -z "${ACCOUNT_CONFIG_DIR[$name]:-}" ]; then
      echo "error: unknown local account '$name'" >&2
      return 1
    fi
    printf '%s\n' "${ACCOUNT_CONFIG_DIR[$name]}"
  }
fi

if ! declare -F apply_account_extra_env >/dev/null 2>&1; then
  apply_account_extra_env() { :; }
fi
