---
name: model-dispatch
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
claims at all (a bridge wired for one engine does not automatically cover a
second one added later).

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

Copy `model-dispatch.example.json` to `.model-dispatch.json` in the target repo and
override only the roles needed there. Role definitions can set model, effort,
budget, read-only mode, Bridge access, persona, and an optional operations MCP file.
Do not commit machine-specific account registries or secret-bearing MCP configs.

Install AgentMind once, then enable lifecycle hooks for either or both hosts:

```sh
pipx install ./skills/model-dispatch/mcp/agentmind
am hooks-install . --platform all
```

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

1. Give the task one immutable identifier, one objective, and a bounded file scope.
2. Put the prompt in `.agent-logs/prompts/<task>.txt` with these optional headers:

   ```text
   # GOAL: one observable outcome
   # FILES: path/one,path/two
   ```

   Prefer generating this with `am prompt "<task>" --goal "..." --out <path>`
   over writing it by hand — it emits the same headers from the graph context
   instead of whole files, and refuses to write a prompt with no goal.

3. Dispatch from the repository root:

   ```sh
   skills/model-dispatch/scripts/dispatch.sh ROLE TASK PROMPT [MINUTES] [EFFORT] [BUDGET] [ACCOUNT] [NO_WORKTREE]
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

## Role selection

Use the narrowest configured role that fits. Built-in defaults cover `backend`,
`design`, `sdk`, `general`, `ops`, `research`, and `judge`; repositories may replace
their model, effort, budget, and persona through `.model-dispatch.json`.

- Implementation roles can edit within the assigned scope.
- Research and judge roles are read-only and return evidence, not patches.
- Operations is for explicitly authorized diagnostics or remediation and should use
  a separately configured MCP surface (`opsMcpConfig` in `.model-dispatch.json`).
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

After a dispatch reports done:

```sh
am gate <task> --check "<verify command>" --promote   # the only path to `verified`
am gate-targets                                        # what is still waiting on this
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

## Memory behavior

At dispatch start, AgentMind matches memory by resolved repository path, refreshes
the store, and injects relevant context. At completion it ingests Bridge findings
and records status. Codex and Claude Code main-session hooks use the same lifecycle.
Corpus labels are descriptive only; they are never used to guess repository identity.

If memory is unavailable, continue the task and report the warning. Never weaken the
verification gate or silently promote a candidate claim to make automation succeed.
