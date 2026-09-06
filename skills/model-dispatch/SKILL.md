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

## Dispatch workflow

1. Give the task one immutable identifier, one objective, and a bounded file scope.
2. Put the prompt in `.agent-logs/prompts/<task>.txt` with these optional headers:

   ```text
   # GOAL: one observable outcome
   # FILES: path/one,path/two
   ```

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
  a separately configured MCP surface.

For a task that spans independent file sets, dispatch separate tasks in parallel.
For overlapping files or sequential dependencies, serialize the work.

## Memory behavior

At dispatch start, AgentMind matches memory by resolved repository path, refreshes
the store, and injects relevant context. At completion it ingests Bridge findings
and records status. Codex and Claude Code main-session hooks use the same lifecycle.
Corpus labels are descriptive only; they are never used to guess repository identity.

If memory is unavailable, continue the task and report the warning. Never weaken the
verification gate or silently promote a candidate claim to make automation succeed.
