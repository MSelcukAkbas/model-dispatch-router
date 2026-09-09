#!/usr/bin/env bash
# Fresh-install smoke test.
#
# This exercises the tool the way a new user meets it, not the way a developer
# already holding a working environment does. Every check here corresponds to a
# real onboarding failure that a passing unit-test suite did not catch: an
# install missing the graph extra, a setup that reported success having done
# nothing, a missing optional dependency surfacing as a traceback, and hook
# files committed into the repository.
#
# It installs into throwaway virtual environments rather than with
# `uv tool install`, so running it locally cannot disturb whatever version you
# have on PATH.
#
# Usage: scripts/smoke-test.sh
#
# To run it against Linux from a Windows machine, without waiting for CI:
#
#   docker run --rm -v "$PWD:/src:ro" ghcr.io/astral-sh/uv:python3.12-bookworm-slim \
#     bash -c 'apt-get update -qq && apt-get install -y -qq git &&
#              cp -r /src /work && cd /work &&
#              rm -rf skills/model-dispatch-route/mcp/agentmind/.venv &&
#              git config --global user.email ci@example.invalid &&
#              git config --global user.name ci &&
#              git config --global --add safe.directory /work &&
#              bash scripts/smoke-test.sh'
#
# The copy matters: it leaves the mounted checkout read-only, so a run cannot
# disturb the working tree it is testing.
set -euo pipefail

APP="skills/model-dispatch-route/mcp/agentmind"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

FAILURES=0
ok()   { printf '  ok    %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1" >&2; FAILURES=$((FAILURES + 1)); }

# Virtualenv layouts differ between platforms and CI runs on both.
bindir() { [ -d "$1/bin" ] && printf '%s/bin' "$1" || printf '%s/Scripts' "$1"; }

# --- a repository for the tool to point at ----------------------------------
SAMPLE="$WORK/sample"
mkdir -p "$SAMPLE"
git init -q "$SAMPLE"
printf 'def check(score):\n    return score > 85\n' > "$SAMPLE/gate.py"
git -C "$SAMPLE" add -A
git -C "$SAMPLE" -c user.email=ci@example.invalid -c user.name=ci commit -qm init

echo "== install without the graph extra =="
uv venv -q "$WORK/plain"
VIRTUAL_ENV="$WORK/plain" uv pip install -q "./$APP"
PLAIN="$(bindir "$WORK/plain")"

"$PLAIN/am" --help >/dev/null 2>&1 \
  && ok "am runs without the graph extra" \
  || fail "am is unusable without the graph extra"

# A bug report that cannot name the build it came from costs more to answer
# than it did to file.
case "$("$PLAIN/am" --version 2>&1 || true)" in
  *agentmind*[0-9]*) ok "am --version reports a version" ;;
  *) fail "am --version does not report a version" ;;
esac

SETUP_OUT="$("$PLAIN/am" setup "$SAMPLE" --root "$WORK/ws-plain" 2>&1 || true)"
case "$SETUP_OUT" in
  *partial*) ok "setup reports 'partial' when it cannot build a graph" ;;
  *) fail "setup did not warn that no graph was built; said: $(printf '%s' "$SETUP_OUT" | tail -3 | tr '\n' ' ')" ;;
esac

# A missing optional dependency is a setup problem with a known fix. It should
# be reported, not raised through the stack.
CONTEXT_OUT="$("$PLAIN/am" context "gate" --root "$WORK/ws-plain" 2>&1 || true)"
case "$CONTEXT_OUT" in
  *Traceback*) fail "context leaked a traceback instead of explaining the cause" ;;
  *graphify*)  ok "context explains the missing dependency" ;;
  *) fail "context gave no usable message: $(printf '%s' "$CONTEXT_OUT" | tail -2 | tr '\n' ' ')" ;;
esac

echo "== install with the graph extra =="
uv venv -q "$WORK/full"
VIRTUAL_ENV="$WORK/full" uv pip install -q "./$APP[graph]"
FULL="$(bindir "$WORK/full")"

for exe in am agentmind-hook agentmind-mcp; do
  if [ -x "$FULL/$exe" ] || [ -x "$FULL/$exe.exe" ]; then
    ok "$exe is installed"
  else
    fail "$exe is declared in pyproject but was not installed"
  fi
done

"$FULL/am" setup "$SAMPLE" --root "$WORK/ws-full" >/dev/null 2>&1 \
  && ok "setup completes with the graph extra" \
  || fail "setup failed with the graph extra"

"$FULL/am" graph build "$SAMPLE" --name sample --root "$WORK/ws-full" >/dev/null 2>&1 \
  && ok "graph build completes" \
  || fail "graph build failed"

GRAPH_OUT="$("$FULL/am" status --root "$WORK/ws-full" 2>&1 || true)"
case "$GRAPH_OUT" in
  *"0 nodes"*) fail "graph build produced no nodes" ;;
  *node*) ok "the built graph has nodes" ;;
  *) fail "status did not report a graph" ;;
esac

echo "== hooks =="
HOOK_REPO="$WORK/hookrepo"
mkdir -p "$HOOK_REPO"
git init -q "$HOOK_REPO"
"$FULL/am" hooks-install "$HOOK_REPO" --platform all >/dev/null 2>&1 || true
[ -f "$HOOK_REPO/.claude/settings.json" ] && ok "claude hook written" || fail "claude hook not written"
[ -f "$HOOK_REPO/.codex/hooks.json" ] && ok "codex hook written" || fail "codex hook not written"

# The hook runs on every session start of every host that installs it, so a
# non-zero exit or a crash there is felt immediately and everywhere.
HOOK_OUT="$(printf '{"session_id":"smoke","cwd":"%s","source":"startup"}' "$SAMPLE" \
  | "$FULL/agentmind-hook" start 2>&1 || true)"
case "$HOOK_OUT" in
  *Traceback*) fail "session-start hook raised: $(printf '%s' "$HOOK_OUT" | tail -2 | tr '\n' ' ')" ;;
  *) ok "session-start hook runs without raising" ;;
esac

echo "== repository hygiene =="
# These are the output of `am hooks-install`, and they name a command that only
# exists once this package is installed. Shipping them hands every clone a
# session hook it cannot run.
for tracked in .claude/settings.json .codex/hooks.json; do
  if git ls-files --error-unmatch "$tracked" >/dev/null 2>&1; then
    fail "$tracked is tracked; it is machine-local hook output"
  else
    ok "$tracked is not tracked"
  fi
done

if git grep -qIE '(^|[^A-Za-z])(sk-[A-Za-z0-9]{16,})' -- . 2>/dev/null; then
  fail "a token-shaped string is tracked in this repository"
else
  ok "no token-shaped strings tracked"
fi

echo
if [ "$FAILURES" -eq 0 ]; then
  echo "smoke test passed"
else
  echo "smoke test failed: $FAILURES check(s)" >&2
  exit 1
fi
