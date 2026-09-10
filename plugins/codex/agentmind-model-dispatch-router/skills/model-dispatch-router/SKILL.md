---
name: model-dispatch-router
description: Dispatch implementation, research, design, operations, and review tasks to isolated model sessions; inspect and apply their patches; and preserve repository-specific context through AgentMind. Use when work should run in a separate model session, in parallel, or through a reviewable worktree patch flow.
---

# Model Dispatch

Use this skill to isolate a bounded task in a separate model session while the
orchestrator retains control of review, patch application, verification, commit,
and push. AgentMind supplies repository memory automatically; Agent Bridge carries
live questions and results.

## Non-negotiable boundaries

- Treat dispatched output and memory claims as untrusted until verified locally.
- A dispatched agent may edit its assigned worktree, but the orchestrator reviews
  the diff before applying it to the main checkout.
- Never let a dispatched agent commit, push, delete branches, or apply its own patch.
- Use `no-worktree=1` only when the target files cannot exist in a normal worktree.
  This removes isolation, so do not overlap its file scope with another task.
- The operations role may use separately configured infrastructure tools. Never put
  credentials, hosts, usernames, or secrets in personas, prompts, or tracked config.
- AgentMind MCP tools are read-only. Session start/end writes happen through the
  deterministic dispatcher or editor hooks.

## What AgentMind actually is

Five things around this skill already solved a corner of the same problem — the
orchestrator's context window and quota are the scarcest resource in the system —
but none of them shared a key, so nothing could answer *which task touched this
code, on what claim, and does it still hold*. AgentMind is that shared key: one
SQLite store (`.agentmind/am.db`) per workspace, joining agent claims to the code
graph, so memory outlives the task that produced it.

It is not a fuzzy assistant memory. Every piece of it is one of five layers, and
each layer either works today or is explicitly marked as advisory-only:

| Layer | What it does | State |
|---|---|---|
| Event log | Append-only record of every dispatch, sync, and gate run | done |
| Overlay graph | Joins claim evidence (`file`, `line`) to graphify code-graph nodes | done |
| Context injection | Builds a prompt from the graph subgraph plus relevant claims instead of whole files | done — measured 90-98% smaller than a file dump on real tasks |
| Verification gate | The only path from `candidate` to `verified` | done |
| Routing advice | Surfaces the documented role/model/effort policy plus how much dispatch history backs it | advisory only — see below |

**Routing advice is not a router.** `am route` reports a confidence label
(`none` / `anecdotal` / `weak` / `moderate`) alongside every recommendation, and
never claims more than that, because nothing in the record yet tracks whether a
dispatched task actually succeeded. Read `am coverage` before trusting any
pattern you think you see in dispatch history — it names exactly which fields
are populated for which engine, and which dispatch paths currently produce zero
claims at all (a bridge wired for one engine does not automatically cover
another — until 2026-09-09, `agy` was exactly this case: `dispatch-agy.sh` and
`dispatch-codex.sh` now both run the shared `ingest-findings.js` after every
call to parse the FINDINGS: block into the knowledge store directly, since
neither engine has a per-invocation MCP to call `knowledge_write` through.
History from before that fix still shows 0 claims for agy and cannot be
backfilled; codex has no history to backfill either way, since it did not
exist as a dispatch lane before this).

## The claim lifecycle

Every claim a dispatched agent reports arrives as `candidate`. Only the gate
promotes one, and only when its checks pass.

| status | means |
|---|---|
| `candidate` | an agent said so; nothing has checked it |
| `verified` | passed the gate on this machine |
| `stale` | evidence moved since it was recorded |
| `superseded` | replaced by a later claim |
| `promoted` | manually accepted by the orchestrator |

The gate checks: every cited file still exists, every citation still binds to a
graph node, no cited file carries uncommitted changes, nothing has touched those
files since the claim was recorded, and — if you supply one — a project command
exits zero. "Cannot tell" is not a pass: a claim whose recorded commit is gone
after a rebase fails rather than sliding through. A failing gate deletes
nothing; the claim stays exactly what it was.

A `verified` claim is not permanent. If its cited files move again after
verification, the next sync demotes it back to `stale` — verification is a
statement about a specific commit, not a lifetime guarantee.

## Configure a repository

Copy `model-dispatch-router.example.json` to `.model-dispatch-router.json` in the target repo and
override only the roles needed there. Role definitions can set model, effort,
budget, read-only mode, Bridge access, persona, and an optional operations MCP file.
Do not commit machine-specific account registries or secret-bearing MCP configs.
With no `--account`, a dispatch always uses the invoking user's current Claude
session. Optional extra accounts are local-only and must never be enumerated
by general quota reports.

Install AgentMind once, then enable lifecycle hooks for either or both hosts:

```sh
uv tool install --editable "./skills/model-dispatch-router/mcp/agentmind[graph]"
am hooks-install . --platform all
```

The `[graph]` extra is not optional in practice: without it the store still
records tasks and claims, but every command that reads the code graph —
`am context`, `am prompt`, `am why`, `am setup`'s extraction step — has
nothing to read. Install it unless you specifically want a memory-only store.

Codex reads `.codex/hooks.json`; Claude Code reads `.claude/settings.json`. Both call
the same platform-neutral hook executable. On first session start, AgentMind creates
a repository-local store and corpus if no matching source path exists. Hook failures
are fail-open and must not block the coding host.

A workspace can watch more than one repository. Each is a *corpus* — a name
mapped to a source path in the store, resolved by path containment, not by
"the only one registered." Most commands accept `--repo <name>`; omit it when
the workspace watches exactly one corpus.

## How memory actually flows

At **session start** (an interactive editor session, or the moment before a
dispatch), the hook syncs the store against the repository's current state and
injects a token-budgeted context: the graph subgraph around the task plus any
claims already on record for it, ranked so the most trustworthy ones survive
the budget cut first. This is what replaces pasting whole files into a prompt.

At **session end** (or dispatch completion), the hook syncs again — picking up
whatever Agent Bridge's `submit_result` wrote — and records a `dispatch.finished`
event. Memory unavailability at either point is fail-open: the task proceeds,
and the failure is reported, not hidden and not treated as a reason to weaken
the gate or promote a claim that has not earned it.

Both directions are also available as plain commands (`am session-start`,
`am session-end`), so a hand-run task gets the same treatment as a hooked one.

## Dispatch workflow

## Session Hygiene — Oturum Başında Kota İzlemeyi Başlatın

Her yeni orkestratör oturumu başladığında `quota-watch.sh`'i arka planda çalıştırın.
Script; Claude Code, AGY ve Codex (yüklü olanlar) kotasını 5 dakikada bir otomatik
olarak sorgular ve yalnızca her %5'lik bant geçişinde bir satır yazar — bu da
Monitor aracına bildirim olarak düşer. Hiç bant değişmezse sessiz kalır, spam yapmaz.

```sh
# Oturum başında bir kez — 8 saatlik güvenlik kapağıyla kendiliğinden durur
bash skills/model-dispatch-router/scripts/quota-watch.sh &
```

Anlık kota durumunu tek seferlik görmek için:

```sh
# Tüm platformlar (Claude Code + AGY + Codex):
bash skills/model-dispatch-router/scripts/usage.sh

# Yalnızca bir platform:
bash skills/model-dispatch-router/scripts/usage.sh --platform agy
bash skills/model-dispatch-router/scripts/usage.sh --platform claude
bash skills/model-dispatch-router/scripts/usage.sh --platform codex
```

Claude Code kota eşiği (%90) aşılırsa `dispatch.sh` yeni görev almayı reddeder (çıkış 15).
Bu durumda `wait-quota.sh` ile eşik altına düşmesini bekleyin ya da AGY / Codex kotasına geçin.

## Quick start and recovery

Use `dispatch.sh` for Claude implementation and review roles. Use
`dispatch-agy.sh` for an independent AGY (Gemini) research, judgement, or
scoped coder task, or `dispatch-codex.sh` for the same three roles on OpenAI's
Codex CLI — a second and third independent-vendor lane, useful when a verdict
or review needs to not come from the same vendor as the orchestrator, or when
one vendor's quota is exhausted. `dispatch-codex.sh research|judge|coder TASK
PROMPT [MINUTES] [MODEL]` mirrors `dispatch-agy.sh`'s calling convention
exactly. Its `read-only`/`workspace-write` sandbox is a real, live-verified
structural boundary (a write attempt under `read-only` is rejected before it
reaches disk; `workspace-write` independently blocks `.git/` writes) — see
`dispatch-codex.sh`'s own header comment for what was and wasn't verified.
Like agy, it has no per-invocation MCP, so its `FINDINGS:` block is ingested
into the knowledge store by `ingest-findings.js` automatically after each
call, not through `knowledge_write`. A normal writer task gets a clean
worktree. Use `--snapshot` when the
declared files already carry required dirty state: it materializes only that
scope into the task worktree, preserves the main index, and still gives
`diff.sh`/`apply.sh` a reviewable patch. `--no-worktree` remains a last resort
for files a worktree cannot materialize; its provenance is non-exclusive.

**A rejected deliverable is not automatically a reason to discard the
worktree and start a new task-id.** Both dispatchers already reuse an
existing worktree for the same task-id (`note: worktree ... already
exists — reusing`). If `diff.sh` shows the patch is close but wrong for a
narrow, describable reason (a contradicted report, a missing companion file,
a stale API call), re-drive the SAME task-id instead of paying for a fresh
worktree and a full re-run:

- Claude tasks (`dispatch.sh`): `resume.sh TASK --amend-prompt FILE` now
  works even when the task finished successfully (`status.sh` exit 0) — the
  amendment file's content is appended as new instructions on the SAME
  `claude --resume <session-id>` conversation, not a fresh one. Without
  `--amend-prompt`, resuming an already-done task is still refused (exit 18)
  so this never happens by accident.
- AGY tasks (`dispatch-agy.sh`): there is no session/`--resume` equivalent
  (agy's `-p` mode has none — verified live, see `dispatch-agy.sh`'s header),
  so a correction round is a fresh `agy -p` call — but dispatch it under the
  **same task-id** with a prompt that states exactly what was wrong. The
  worktree and its partial progress are reused automatically; only the
  conversation itself restarts.
- Codex tasks (`dispatch-codex.sh`): `resume.sh TASK --amend-prompt FILE`
  now genuinely continues a prior conversation via `codex exec resume <thread-id>`
  (the thread ID from `thread.started` is persisted in `$TASK.codex.meta`).
  The worktree and previous conversation context are reused automatically,
  matching the Claude correction round capability.

Every start snapshots the runner into `.agent-logs/runtimes/<task>/`; the
plugin cache can therefore be updated while a task runs. Use the stable
recovery entry point if the installed plugin changed:

```sh
skills/model-dispatch-router/scripts/task.sh status TASK
skills/model-dispatch-router/scripts/task.sh collect TASK
skills/model-dispatch-router/scripts/task.sh resume TASK
```

`done` means a nonempty final response passed semantic checks. `result_missing`
means the engine exited but did not deliver a usable report. `partial` and
`blocked` preserve their checkpoint but require a resume or human decision.
`orphaned` means the recorded process identity no longer proves ownership;
inspect its captured output before recovery. A `hook_failed` result preserves
the engine report but means AgentMind lifecycle recording must be repaired.

1. Give the task one immutable identifier, one objective, and a bounded file scope.
2. Put the prompt in `.agent-logs/prompts/<task>.txt` with these headers:

   ```text
   # GOAL: one observable outcome
   # FILES: path/one,path/two
   ```

   `# GOAL` is required for every task. `# FILES` is required for writer roles:
   it produces the normalized scope manifest that `diff.sh` and `apply.sh`
   enforce. Use an exact path or a directory prefix ending in `/`.

   Prefer generating this with `am prompt "<task>" --goal "..." --out <path>`
   over writing it by hand — it emits the same headers from the graph context
   instead of whole files, and refuses to write a prompt with no goal.

3. Dispatch from the repository root:

   ```sh
   skills/model-dispatch-router/scripts/dispatch.sh ROLE TASK PROMPT --timeout 25 --effort high --budget 1.50 --account NAME
   ```

4. Use `status.sh`, `wait.sh`, and Agent Bridge to monitor without polling model
   output manually. Answer Bridge questions only when they require orchestrator or
   user authority.
5. Inspect with `diff.sh TASK`. Reject unrelated changes, scope violations, missing
   tests, secrets, and unsupported claims.
6. Apply with `apply.sh TASK`; it writes neither commits nor pushes.
7. Run the repository's own validation plus `verify.sh`. Keep claims as candidates
   until the checkout is clean and `am gate TASK --check "..." --promote` passes.
8. Commit or push only when the user authorized those actions. Clean up the worktree
   with `cleanup.sh TASK` after the result is safely retained.

## The scripts, and what each one is for

Everything lives in `skills/model-dispatch-router/scripts/`. Run them from the
repository root. Only the first group starts work; the rest observe, review,
or recover.

**Start work**

| script | usage |
|---|---|
| `dispatch.sh` | `ROLE TASK PROMPT [--timeout MINUTES] [--effort LEVEL] [--budget USD] [--account NAME] [--snapshot\|--no-worktree]` — launches a headless session in its own worktree, returns immediately |
| `dispatch-agy.sh` | `<research\|judge\|coder> TASK PROMPT [MINUTES] [MODEL]` — a second engine (agy/Gemini) on a separate quota pool, for the read-only roles plus a catch-all writer. Not a drop-in replacement: it has no per-task tool allowlist, so writing roles stay on `dispatch.sh` |
| `dispatch-codex.sh` | `<research\|judge\|coder> TASK PROMPT [MINUTES] [MODEL]` — a third engine (OpenAI Codex CLI) on a separate quota pool, same three roles and calling convention as `dispatch-agy.sh`. Its coder role gets a real sandboxed write boundary (`--sandbox workspace-write`, verified to block `.git/` writes independently of worktree isolation) |
| `new-id.sh` | prints the next `T-NNNNNN` identifier, for work with no ticket of its own |

**Watch it**

| script | usage |
|---|---|
| `status.sh TASK` | one task's current state — this is the primary signal, and its exit code carries the answer |
| `wait.sh TASK [TASK…]` | blocks until every named task finishes; exits 0 only if all of them exited 0 |
| `list.sh` | inventory of every task the workspace knows about |
| `collect.sh TASK` | the structured result and cost once a task is done |
| `task.sh status\|collect\|resume TASK` | resolves the task's pinned runtime before falling back to the current installation |

**Review and apply**

| script | usage |
|---|---|
| `diff.sh TASK [--allow-extra a,b]` | the worktree's changes, read-only — never skip this. Out-of-scope changes are always shown in a separate section, never silently hidden by a scope failure |
| `apply.sh TASK [--allow-extra a,b]` | copies the reviewed changes into the main checkout. Writes no commit, makes no push. `--allow-extra` is an explicit, orchestrator-typed exception to the `# FILES:` manifest for files you reviewed in `diff.sh`'s out-of-scope section and judge necessary (e.g. a test file a new function required) — every use is appended to `.agent-logs/TASK.scope-override` for audit. The dispatched agent has no path to set this itself |
| `verify.sh` | the repository's own validation pass over what was applied |

**Recover and clean up**

| script | usage |
|---|---|
| `resume.sh TASK [--timeout MINUTES] [--effort LEVEL] [--budget USD] [--amend-prompt FILE]` | re-dispatches a recoverable task (timeout/quota/budget-capped), or a `done` one when `--amend-prompt` is given (a rejected-but-finished deliverable), with recorded role/account; an amendment is copied to the log and delivered to the same resumed session while the original prompt remains immutable |
| `cleanup.sh TASK` | removes one task's worktree and branch after the result is safely retained |
| `cleanup-all.sh --yes TASK [TASK…]` | the same for several, and it requires `--yes` on purpose |

**Quota and capacity**

| script | usage |
|---|---|
| `health.sh [ACCOUNT]` | preflight before dispatching — check this rather than discovering the problem mid-run |
| `usage.sh [--platform claude\|agy\|codex] [--raw] [ACCOUNT]` | **tüm platformlar** (Claude Code + AGY + Codex) için tek seferlik kota özeti; `--platform` ile tek platform seçilebilir; `--raw` Claude JSON'u döndürür (health.sh / wait-quota.sh uyumu) |
| `wait-quota.sh [ACCOUNT] [MAX_PCT] [POLL_S]` | blocks until an account drops below a utilisation threshold |
| `quota-watch.sh [ACCOUNT] [POLL_S]` | **3 platformu** (Claude Code + AGY + Codex) 5 dk aralıkla izler; her %5 bant geçişinde Monitor'a bildirim düşer — session başında arka planda başlatılması tavsiye edilir |
| `context-usage.sh SESSION_ID [MAX_TOKENS] [ACCOUNT]` | how much context a specific session has consumed |

## Exit codes are the contract

These scripts are meant to be driven programmatically, so the exit code — not
the printed text — is what you branch on. Each distinct code means a different
response is correct.

`dispatch.sh`:

| code | meaning | what to do |
|---|---|---|
| 0 | dispatched | proceed to monitoring |
| 1 | bad usage or missing files | fix the invocation |
| 12 | file conflict with a running task | serialize, or narrow `# FILES:` |
| 15 | quota too high to dispatch safely | `wait-quota.sh`, or use another account |
| 19 | refused: no-progress budget clamp exhausted | **a human looks at this**, not another retry |

`status.sh`:

| code | meaning | what to do |
|---|---|---|
| 0 | finished successfully | `collect.sh`, then `diff.sh` |
| 10 | still running | keep waiting |
| 11 | not found | check the identifier |
| 14 | timed out | `resume.sh` with more minutes |
| 17 | quota exhausted mid-run | not a task defect — reschedule |
| 20 | hit the per-task budget cap | runaway-spend guard; inspect before resuming |
| 21 | final result missing or invalid | recover checkpoint, fix delivery, then `resume.sh` |
| 22 | model reported partial or blocked | inspect checkpoint and resume only with a concrete next action |
| 23 | runner identity is orphaned | inspect captured output; never assume a PID proves task ownership |
| 24 | session-end hook incomplete or failed | engine report remains available; repair lifecycle before trusting AgentMind state |

`resume.sh`: `0` re-dispatched · `11` unknown task · `18` not in a resumable
state (still running; or `done` without `--amend-prompt`) · `19` the clamp
refused it again.

`collect.sh`: same terminal codes as `status.sh`; on any nonzero terminal state
it prints the best captured checkpoint rather than discarding the attempt.

Codes 19 and 20 both mean *stop and look*. They exist because a task that
makes no progress across attempts will happily consume budget forever if
something keeps auto-retrying it; the clamp halves the budget on each
unproductive attempt and then refuses outright.

## Two safety mechanisms you should know are there

**The budget clamp.** Each attempt at a task is measured against the last one.
An attempt that produced no worktree progress gets a halved budget next time,
and eventually a refusal (exit 19) instead of another run. This is why
`resume.sh` is the right way to retry — it carries the recorded state forward
rather than resetting the counter that protects you.

Generated context is security-filtered before it enters `am prompt` or a
dispatch lifecycle: `CLAUDE.md`, `.env*`, secret/credential paths, Git state
and AgentMind runtime state are excluded. Preview `am context` before sending
any task, especially when a repository has unusual sensitive-file names.

**The result Stop hook.** Roles with Bridge access are blocked from ending
their turn until they call `submit_result`, so a finished task normally leaves
a structured result and its findings behind rather than a transcript someone
has to read. The block is bounded, not absolute: after a few refusals the hook
gives up, lets the session end, and drops a `result-missing` marker in
`.agent-logs/` instead of looping forever. So a task can still finish with no
result — treat that marker as a failed run whose output must be recovered by
hand, not as a quirk to work around. The dispatcher publishes an atomic
`final-status.json` before it runs the optional session-end hook, so hook
failure cannot erase the engine result or turn it into an untraceable success.

Every task also stores a bounded post-tool checkpoint. Near the configured
deadline the model is told to write its current findings, changed files and
verification before spending its remaining effort. This is a recovery aid,
not a successful result.

## Role selection

Use the narrowest configured role that fits. Built-in defaults cover `backend`,
`design`, `sdk`, `general`, `ops`, `research`, and `judge`; repositories may replace
their model, effort, budget, and persona through `.model-dispatch-router.json`.

- Implementation roles can edit within the assigned scope.
- Research and judge roles are read-only and return evidence, not patches.
- Operations is for explicitly authorized diagnostics or remediation and should use
  a separately configured MCP surface (`opsMcpConfig` in `.model-dispatch-router.json`).
  Dispatching `ops` without one still runs — bridge-only, with a stderr warning —
  it does not silently drop the capability the task may have been asked to use.

For a task that spans independent file sets, dispatch separate tasks in parallel.
For overlapping files or sequential dependencies, serialize the work.

## Before and after a dispatch — which command to reach for

Before writing a prompt:

```sh
am why <file>              # what has already been claimed here, and is it still fresh?
am hot                     # where has agent attention actually gone in this repo?
am context "<task>"        # preview exactly what a prompt would carry
```

Periodically, not per-task:

```sh
am status                            # tasks, events, graph size, claim status counts
am coverage                          # what the dispatch record can and cannot answer
am dangling --reason file_missing    # claims stranded on code that no longer exists
am route <role>                      # documented policy plus how much history backs it
```

## When something looks wrong

- **A command says no store was found.** You are outside every watched
  workspace. Run `am setup <repo>` once to create one, or pass `--root`.
- **`am why` or `am context` return nothing for a file you know has history.**
  The claim's evidence may not have resolved to a graph node yet — run
  `am resolve` (or `am sync`, which includes it) before assuming there is
  nothing recorded.
- **A claim you expected to be `verified` shows `stale`.** Its cited files
  changed since the gate last ran. This is correct behavior, not a bug:
  re-run the gate against the current commit.
- **`am route` shows `none` or `anecdotal` for a role you dispatch often.**
  The advice is still just the documented policy; check `am coverage` for
  whether that role's dispatches are producing claims at all before trusting
  any pattern in the numbers.
- **Memory looks entirely absent after a fresh clone.** Hooks are fail-open by
  design — check `am hooks-install . --platform all` was run, and that the
  editor host's settings file actually gained the `agentmind-hook` entries.
- **`am` errors with `ModuleNotFoundError`, or clearly reads the wrong
  repository's data.** `uv tool install` registers `am`/`agentmind-mcp`
  globally by package name, not per-project — if more than one checkout of
  this package exists on the machine (e.g. an upstream dev copy alongside a
  per-project vendored one), whichever one last ran `uv tool install
  --force` silently wins the shared binary for every project. `am status`
  prints a `running from:` line with the resolved source path — check it
  matches the copy you expect before assuming a code bug. Fix: re-run `uv
  tool install --editable "<this-repo's-path>/mcp/agentmind[graph]" --force`
  from the repository you actually want active.

## Memory behavior

At dispatch start, AgentMind matches memory by resolved repository path, refreshes
the store, and injects relevant context. At completion it ingests Bridge findings
and records status. Codex and Claude Code main-session hooks use the same lifecycle.
Corpus labels are descriptive only; they are never used to guess repository identity.

If memory is unavailable, continue the task and report the warning. Never weaken the
verification gate or silently promote a candidate claim to make automation succeed.

## Integration and Configuration Templates

Ready-to-use configuration templates are provided under `examples/` for direct plug-and-play setup:

| Component | Template Location | Target Project Path | Purpose |
|---|---|---|---|
| **Claude Code Hooks** | `examples/hooks/claude-settings.json` | `.claude/settings.json` | Injects AgentMind context on `SessionStart` and finalizes on `SessionEnd`. |
| **Codex Hooks** | `examples/hooks/codex-hooks.json` | `.codex/hooks.json` | Hooks for Codex session lifecycle with memory bounds. |
| **MCP Server** | `examples/mcp/mcp.json` | `.mcp.json` | Exposes `agentmind-mcp` tools to the agent session. |
| **Codex Plugin** | `examples/plugin/plugin.json` | `.codex-plugin/plugin.json` | Plugin manifest for bundling and distribution. |
| **Task Config** | `examples/model-dispatch-router.example.json` | `.model-dispatch-router.json` | Verification commands, role models, and budgets. |

To automatically wire lifecycle hooks into any watched repository without manual copying:
```bash
am hooks-install <repo-path> --platform all
```
