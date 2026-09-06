#!/bin/bash
# Syntax-check changed files in the main checkout without modifying them.
# Project-level tests belong in .model-dispatch.json as verifyCommand.
# Exit: 0 all supported checks pass | 13 at least one check fails.
set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT" || exit 13
CHANGED="$(git status --porcelain --untracked-files=all | cut -c4- | sed 's/.* -> //')"

if [ -z "$CHANGED" ]; then
  echo "Nothing uncommitted to verify."
  exit 0
fi

PASS=0
FAIL=0
SKIP=0
TMP_ERR="$(mktemp)"
trap 'rm -f "$TMP_ERR"' EXIT

while IFS= read -r file; do
  [ -z "$file" ] && continue
  if [ ! -f "$file" ]; then
    echo "SKIP (deleted/missing): $file"
    SKIP=$((SKIP + 1))
    continue
  fi
  case "$file" in
    *.js|*.cjs|*.mjs)
      CHECK=(node --check "$file")
      ;;
    *.py)
      CHECK=(python -m py_compile "$file")
      ;;
    *.json)
      CHECK=(python -m json.tool "$file")
      ;;
    *.sh)
      CHECK=(bash -n "$file")
      ;;
    *)
      echo "SKIP (no checker): $file"
      SKIP=$((SKIP + 1))
      continue
      ;;
  esac
  if "${CHECK[@]}" >/dev/null 2>"$TMP_ERR"; then
    echo "PASS: $file"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $file"
    sed 's/^/    /' "$TMP_ERR"
    FAIL=$((FAIL + 1))
  fi
done <<< "$CHANGED"

echo "verify.sh: $PASS pass, $FAIL fail, $SKIP skipped"
[ "$FAIL" -gt 0 ] && exit 13
exit 0
