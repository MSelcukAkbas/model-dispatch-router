#!/bin/bash
# Usage: verify.sh
# Scans the MAIN checkout for every modified or new file not yet committed
# (git status --porcelain, repo-wide — not scoped to any one task) and
# syntax-checks it: `node --check` for backend .js, `esbuild --loader:.js=jsx`
# for anything under portals/. Then, best-effort, runs each touched
# services/*/ or portals/*/ directory's own `npm run lint` if one exists
# (syntax-only was too weak a safety net — a file can parse fine and still
# be broken; the project already carries per-service lint config, use it).
# Run this before committing anything, or as a standing safety net after
# apply.sh. Read-only — never edits/commits.
# Exit codes: 0 all pass (or nothing to check) | 13 at least one file/lint failed
set -uo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# cut -c4- (not awk '{print $NF}') — 2026-07-30 fix — H8: --porcelain does
# NOT quote spaces in filenames, so `?? foo bar.js` has "foo bar.js" as its
# path but awk's last-field split picks only "bar.js" — that mangled path
# then fails every `[ -f "$f" ]` check and gets silently reported as
# "SKIP (deleted/missing)", i.e. a real file goes completely unchecked. Same
# `--untracked-files=all` fix apply.sh/dispatch.sh's diffstat already use
# (plain --porcelain collapses a new directory into one `?? dir/` line).
# `sed 's/.* -> //'` reduces a rename line ("old -> new") to just the new
# path, which is the one that still exists to check.
CHANGED="$(git status --porcelain --untracked-files=all | cut -c4- | sed 's/.* -> //')"

if [ -z "$CHANGED" ]; then
  echo "Nothing uncommitted to verify."
  exit 0
fi

TMP_OUT="$(mktemp)"
TMP_ERR="$(mktemp)"
trap 'rm -f "$TMP_OUT" "$TMP_ERR"' EXIT

PASS=0
FAIL=0
SKIP=0

while IFS= read -r f; do
  [ -z "$f" ] && continue
  [ ! -f "$f" ] && { echo "SKIP (deleted/missing): $f"; SKIP=$((SKIP+1)); continue; }

  case "$f" in
    *.js)
      if [[ "$f" == portals/* ]]; then
        if npx --yes esbuild "$f" --loader:.js=jsx --bundle=false --outfile="$TMP_OUT" >"$TMP_ERR" 2>&1; then
          echo "PASS (esbuild): $f"
          PASS=$((PASS+1))
        else
          echo "FAIL (esbuild): $f"
          sed 's/^/    /' "$TMP_ERR"
          FAIL=$((FAIL+1))
        fi
      else
        if node --check "$f" 2>"$TMP_ERR"; then
          echo "PASS (node --check): $f"
          PASS=$((PASS+1))
        else
          echo "FAIL (node --check): $f"
          sed 's/^/    /' "$TMP_ERR"
          FAIL=$((FAIL+1))
        fi
      fi
      ;;
    *.sql|*.md|*.yaml|*.yml|*.json|*.hbs|*.css)
      echo "SKIP (no syntax checker wired up): $f"
      SKIP=$((SKIP+1))
      ;;
    *)
      echo "SKIP (unhandled extension): $f"
      SKIP=$((SKIP+1))
      ;;
  esac
done <<< "$CHANGED"

# --- Best-effort service-local lint, per touched services/*/ or portals/*/ dir ---
echo
echo "== service-local lint (best-effort) =="
declare -A SEEN_DIRS
while IFS= read -r f; do
  [ -z "$f" ] && continue
  case "$f" in
    services/*/*|portals/*/*)
      DIR="$(echo "$f" | cut -d/ -f1-2)"
      SEEN_DIRS["$DIR"]=1
      ;;
  esac
done <<< "$CHANGED"

for DIR in "${!SEEN_DIRS[@]}"; do
  PKG="$REPO_ROOT/$DIR/package.json"
  [ -f "$PKG" ] || continue

  if ! node -e "process.exit((require(process.argv[1]).scripts||{}).lint ? 0 : 1)" "$PKG" 2>/dev/null; then
    echo "SKIP (lint): $DIR — no 'lint' script in package.json"
    SKIP=$((SKIP+1))
    continue
  fi
  if [ ! -d "$REPO_ROOT/$DIR/node_modules" ]; then
    echo "SKIP (lint): $DIR — node_modules missing, would trigger an install, skipped"
    SKIP=$((SKIP+1))
    continue
  fi

  if (cd "$REPO_ROOT/$DIR" && timeout 90s npm run lint --silent) > "$TMP_ERR" 2>&1; then
    echo "PASS (lint): $DIR"
    PASS=$((PASS+1))
  else
    echo "FAIL (lint): $DIR"
    sed 's/^/    /' "$TMP_ERR" | head -50
    FAIL=$((FAIL+1))
  fi
done

echo
echo "== verify.sh summary: $PASS pass, $FAIL fail, $SKIP skipped =="
[ "$FAIL" -gt 0 ] && exit 13
exit 0
