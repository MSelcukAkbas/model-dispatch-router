---
name: antigravity-claude-delegation-setup
description: "Claude Code set up as orchestrator delegating to Antigravity's agy CLI (Gemini/Claude/GPT-OSS models) via the yuting0624 plugin; agy path is done, only external-API layering remains"
metadata: 
  node_type: memory
  type: project
  originSessionId: 
  modified: 
---

Goal: run Claude Code (this assistant, on the user's Anthropic subscription) as the
supervising/conducting agent inside Google Antigravity IDE, delegating bulk/cheap
subtasks to Antigravity's own models via its CLI, rather than paying for a separate
external API. User also wants the ability to plug in other external model APIs
(OpenRouter, Qwen, Gemini API) later — none held yet as of 2026-09-01.

**Current state (as of 2026-09-01, machine: NixOS, zsh):**
- `agy` (Antigravity CLI, real product, launched ~May 2026) installed at
  `~/.local/bin/agy`, version 1.1.23. Runs fine on NixOS (Go static binary).
  Installer appended `export PATH="$HOME/.local/bin:$PATH"` to `~/.zshrc`.
- `agy` authenticated (browser sign-in, same Google account as Antigravity IDE).
  `agy models` confirmed working, lists: gemini-3.7-flash-{high,medium,low},
  gemini-3.6-flash-{high,medium,low}, gemini-3.1-pro-{high,low},
  **claude-sonnet-4-6, claude-opus-4-6-thinking, gpt-oss-120b-medium** — i.e. agy
  is multi-model and exposes Claude/GPT-OSS slugs too, not just Gemini, on this
  account.
- Community plugin `yuting0624/antigravity-for-claude-code` (MIT, ~295★, repo
  audited file-by-file: hooks + wrapper scripts are clean — no network calls, no
  eval, only mktemp-scoped writes; the one real risk knob is `--yolo`
  (`--dangerously-skip-permissions`) which is opt-in per call) is installed:
  marketplace registered + plugin enabled (`antigravity@antigravity-for-claude-code`
  in `~/.claude/settings.json` enabledPlugins, v0.25.2, cache at
  `~/.claude/plugins/cache/antigravity-for-claude-code/antigravity/0.25.2/`).
  It gives Claude a `agy-delegate` wrapper + `/antigravity:*` slash commands
  (setup, delegate, review, research, status/result/cancel, migrate) and a
  SessionStart hook that injects a cost-aware routing policy (delegate only
  above break-even; keep Claude's context lean via digests; always verify agy's
  output independently — agy has been observed faking green test runs).

**Known environment gotchas (apply to any future session on this machine):**
- The in-chat `/plugin` slash command is **blocked** in this embedded
  Antigravity/VS Code chat harness ("isn't available in this environment").
- `claude plugin install` from the CLI is **blocked for Claude itself** by the
  harness's auto-mode classifier (self-modifying its own plugin config) — the
  user has to run it themselves in a terminal, OR use Antigravity's GUI plugin
  panel, which does work and writes the same state files correctly.
- **PATH gotcha — corrected understanding (2026-09-01) + permanently fixed.**
  It's not just "non-interactive zsh skips `.zshrc`": Claude's Bash tool (and
  any subagent's) runs against a **fixed PATH snapshot taken at
  session/process start**, not a shell that re-sources `.zshrc` *or*
  `.zshenv` per command — explicitly invoking `zsh -c '...'` picks up
  `.zshenv` (zsh always sources it), but bare commands and `bash -c`/`sh -c`
  do not. Adding to `.zshenv` alone is therefore NOT a fix for this harness.
  **Real fix applied:** symlinked `~/.local/bin/agy` into the plugin's own
  bin dir (`~/.claude/plugins/cache/antigravity-for-claude-code/antigravity/
  0.25.2/bin/agy`), which *was already* on that baked PATH snapshot (that's
  how `agy-doctor`/`agy-delegate` resolved even before this fix — the plugin
  installer's PATH addition predated the snapshot, the standalone `agy`
  installer's `.zshrc` edit postdated it). Confirmed working with a bare
  `which agy` / `agy --version`, no export needed, in both the main session
  and a freshly-spawned `antigravity-delegate` subagent. If `agy` is ever
  reinstalled/updated to a new path, redo this symlink rather than relying on
  `.zshrc`/`.zshenv`.
- A plugin install only takes effect for Claude Code sessions/processes started
  **after** the install timestamp — reloading the IDE window did not replace an
  already-running chat's backing process in this environment. Verify via the
  plugin cache dir's `.in_use/<pid>` markers against `ps -p <pid> -o lstart` vs.
  the install time in `~/.claude/plugins/installed_plugins.json`.

**Done (2026-09-01, continued session):**
1. Ran `agy-doctor` (via `/antigravity:setup`) — all checks green: agy 1.1.23
   authenticated (11 models), all plugin scripts executable, plugin v0.25.2
   ready. No GCP project/region configured in
   `~/.gemini/antigravity-cli/settings.json` (browser-auth only, no
   `permissions` key present — confirms read-only-by-default was already
   true, no explicit lockdown needed).
2. Wrote the delegation-policy doc. **Moved (same session, per user request)**
   from inline `~/.claude/CLAUDE.md` content to a new generic, cross-project
   home: `~/Workspace/Agents/antigravity-delegation-policy.md` (new top-level
   `Agents/` folder, sibling to `Projects/`/`Books/`/etc., created for this
   and future agent-config docs unrelated to any one project — see its
   `README.md`). `~/.claude/CLAUDE.md` is now just a one-line `@`-import
   pointer to that file, so it still auto-loads into every Claude Code
   session without living inside a project folder or duplicating content.
   Content codifies: default read-only (no config needed, it's the natural
   state absent a `write_file` permissions.allow rule or `--yolo`); Claude
   decides per-task escalation, prefers a narrow `write_file(<dir>)` rule over
   `--yolo`, treats grants as task-scoped not permanent, tells the user when
   it escalates; verification is never delegated (always re-run the real
   gate, never trust agy's self-reported green); tier mapping left at plugin
   defaults.
3. Decided: **keep default Gemini tier mapping** (flash/flash-lo/pro →
   Gemini 3.7 Flash High/Low, Gemini 3.1 Pro High), not remapped to the
   Claude/GPT-OSS slugs — the plugin's own `default_model` doc argues a
   non-Claude executor gives a cross-model verification benefit that a
   same-family executor wouldn't. No settings.json edit was needed since this
   just keeps the plugin's shipped defaults. Revisit only if a specific task
   class turns out to need a Claude-tier executor (would require the
   Antigravity GUI plugin panel — `/plugin` and CLI plugin-config edits are
   blocked for Claude itself in this environment, see gotchas below).

4. Ran a real end-to-end delegation as a live demo (same session): digested
   the 19 currently-open GOREV tickets (per `gorev_status.py status`) out of
   4 Turkish-language docs totaling 8845 lines, via the
   `antigravity-delegate` subagent. This is what surfaced and led to fixing
   the PATH gotcha above. Spot-checked 4 of the 19 digest entries against the
   source docs with `grep` — all accurate; pipeline confirmed working
   end-to-end, not just doctor-green.
5. Added a Claude-usage-limits section to the policy doc (user's explicit
   ask): bias slightly more aggressive toward delegating context/usage-window
   -hungry work than pure dollar-cost would suggest, since Claude's own
   session/context caps are a harder, more immediate constraint on the user
   than agy's separate quota. Full rationale in
   [[antigravity-usage-limit-delegation-bias]] (feedback memory) and in the
   policy doc itself.

**Not yet done:**
6. Later: layer in external APIs (OpenRouter etc.) once the user actually holds
   keys — same delegate-and-verify pattern, sibling wrapper to `agy-delegate`.
   No further action until the user has keys to hand over.

Setup is now functionally complete for the agy/Gemini path, verified with a
real delegation round-trip — only the external-API layering (item 6) remains,
and it's blocked on the user acquiring keys, not on any pending Claude-side
work.

See the repository-local setup notes for any project-specific context this
setup work happened alongside.
