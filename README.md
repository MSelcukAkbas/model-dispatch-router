# AgentMind

Orchestration kernel for the model-dispatch / graphify / agentic-ssh-mcp
stack. One event log, one overlay graph, one token-budgeted context builder.

The premise: **the orchestrator's context window and quota are the scarcest
resource in the system.** Every existing piece already solves some corner of
that; none of them share a key. This kernel is that key.

## Layers

| | Layer | State |
|---|---|---|
| L0 | Event log + entity ids | Phase 0 — this repo |
| L1 | Overlay graph (claims joined to graphify nodes) | Phase 1 |
| L2 | Token-budgeted context injection | Phase 2 |
| L3 | Verification gate (`graph_diff` + freshness) | later |
| L4 | Measured router | later |
| L5 | TUI | later |

## Install

```bash
uv sync --group dev          # kernel only
uv sync --extra graph        # adds graphify (Phase 1+)
```

Python is pinned to 3.12: the `graph` extra pulls ~28 tree-sitter grammar
wheels and the newest CPython does not have wheels for all of them yet.

## Use

```bash
uv run am init
uv run am snapshot ~/Desktop/projeler/arvis_code   # read-only on the source
uv run am import snapshots/<stamp>
uv run am tasks
uv run am stats
uv run am event task.dispatched --task-id KYC-64 --json '{"role":"backend"}'
```

`am event` is fail-open by design — it is called from inside dispatch
pipelines and must never take one down.

## Boundaries

- `graphify` is a pinned dependency, never a fork.
- Verification is never delegated: an agent saying "tests passed" is not
  evidence.
- The claim status lifecycle (`candidate/verified/stale/superseded/promoted`)
  is knowledge-store.js's, adopted verbatim rather than re-invented.
