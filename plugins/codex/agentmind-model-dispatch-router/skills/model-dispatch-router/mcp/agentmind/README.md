# AgentMind

An orchestration kernel for the `model-dispatch-router` / `graphify` / `agentic-ssh-mcp`
stack. It gives a dispatch pipeline three things it did not have: a memory that
survives the task that produced it, a prompt built from that memory instead of
from whole files, and a gate that decides what an agent's word is worth.

## The premise

The orchestrator's context window and quota are the scarcest resources in the
system. Every piece around this one already solves a corner of that — dispatch
spends a second account's quota, ssh-mcp keeps raw output out of the context,
graphify replaces reading files with querying a graph, the knowledge store
remembers instead of re-deriving. None of them shared a key, so nothing could
answer the question they all circle:

> Which task touched this code, on what claim, and does it still hold?

That question is what `am` answers.

## What it does

**Remembers, joined to the code.** `knowledge.db` has recorded evidence as
`[{file, line}]` since day one; graphify records nodes as `{source_file,
source_location}`. Same coordinate space, never joined. AgentMind is that join,
so a claim is attached to the symbol it is about — not to a filename in a text
blob.

**Builds prompts from the graph.** Instead of pasting whole files into a
dispatch prompt, `am prompt` sends the subgraph around the work plus what has
already been claimed about it. Measured on a real corpus, five real tasks, both
modes pointed at the same target files:

```
567,433 -> 20,538 tokens        97% less, 27.6x
```

**Refuses to take an agent's word.** Every claim arrives as `candidate`. Only
`am gate` promotes one to `verified`, and only when checks that run here all
pass. This is deliberate: the surrounding system's own notes record an agent
reporting a green test run that had not happened. A warning in a document
cannot prevent that twice; a gate can.

## Install

From the workspace root:

```bash
uv tool install --editable "./skills/model-dispatch-router/mcp/agentmind[graph]"
```

That puts `am` on your PATH, so it works from any directory. `--editable`
means source edits take effect immediately - without it, `uv tool install`
reuses a cached wheel and a fix you just made silently does not ship.

For working on the kernel itself, `uv sync --extra graph --group dev` inside
`skills/model-dispatch-router/mcp/agentmind/` gives you the test environment.

Python is pinned to 3.12 - the `graph` extra pulls 29 tree-sitter grammar
wheels, and the newest CPython does not have wheels for all of them.

## Use

```bash
am setup ~/path/to/your-repo     # snapshot, import, extract, join
am status                        # everything at a glance
```

`setup` is read-only on the source: it copies the dispatch history and
knowledge store into `.agentmind/snapshots/`, and every later command reads that copy.
Nothing in this tool writes to the repo it learns from.

The store lives in `.agentmind/` at your workspace root, and `am` finds it by
searching upward from wherever you are, the way git finds `.git`. A command
that cannot find one says so and stops - it will not quietly create an empty
database and report zero of everything.

Then:

```bash
am hot                                  # where agent attention has actually gone
am why <file> --src <repo>              # what has been claimed here, still fresh?
am dangling --reason file_missing       # claims stranded on deleted code
am gate-targets                         # tasks holding unverified claims
am route [role]                         # where to send a task, and on what evidence
am coverage                             # what the record can and cannot answer
am gate <task> --src <repo> --promote   # verify, and record it
am bench "<task>" --repo <name> --src <repo>
am prompt "<task>" --goal "..." --repo <name> --out prompt.txt
```

`am prompt` emits `# GOAL:` and `# FILES:` headers because those are
`dispatch.sh`'s contract, not decoration — it refuses a prompt without a goal
and uses the file list to reject a task overlapping a running one.

## The claim lifecycle

`candidate -> verified` is the only promotion, and only the gate performs it.

| status | means |
|---|---|
| `candidate` | an agent said so; nothing has checked it |
| `verified` | passed the gate on this machine |
| `stale` | evidence moved since it was recorded |
| `superseded` | replaced by a later claim |
| `promoted` | manually accepted by the orchestrator |

The vocabulary is `knowledge-store.js`'s, adopted verbatim rather than
reinvented — it was already in production before this kernel existed.

The gate's checks: every cited file still exists, every citation still binds to
a graph node, no cited file has uncommitted changes, nothing has touched those
files since the claim was recorded, and optionally a project command you supply
exits zero. **"Cannot tell" is not a pass** — a claim whose commit is gone after
a rebase fails rather than sliding through.

## Layout

```
agentmind/                                  repo root
├── skills/model-dispatch-router/                orchestration skill
│   ├── mcp/bridge/                       live agent bridge
│   └── mcp/agentmind/                    this Python package
├── docs/                                  project state and research notes
└── references/                            read-only source material
```

## Layers

| | Layer | State |
|---|---|---|
| L0 | Event log + entity ids | done |
| L1 | Overlay graph — claims joined to code | done |
| L2 | Token-budgeted context injection | done |
| L3 | Verification gate | done |
| L4 | Routing advice | done, but not "measured" — see below |
| L5 | TUI | next |

The plan called L4 a *measured* router. The recorded history does not support
that word, so `am route` does not use it. It makes the existing policy explicit
and reports how many dispatches stand behind each rule — `none`, `anecdotal`,
`weak`, `moderate`, and deliberately nothing stronger. `am coverage` shows why:
nothing yet records whether a task succeeded, and the two dispatch engines fill
in different halves of the record.

What the history does say clearly is about plumbing rather than model quality:

```
dispatches that remember nothing
    research on agy: 59 runs, 0 claims
    judge on agy:     8 runs, 0 claims
```

Two thirds of all dispatches produce no institutional memory at all, because
the agent-bridge MCP server that carries `submit_result` is wired for Claude
and `dispatch-agy.sh` has no per-task MCP config to attach it with. Those runs
found things; none of it survived them.

## Testing

```bash
uv run pytest -q
```

`tests/test_graphify_contract.py` pins the graphify output shape the join
depends on. If an upgrade changes it, that test fails instead of the resolver
quietly emitting dangling references. It skips cleanly without the `graph`
extra.

## Boundaries

- `graphify` is a pinned dependency, never a fork.
- Verification is never delegated. An agent saying "tests passed" is not evidence.
- Reading a repo is not writing to it: snapshots are one-way, and a test
  fingerprints the source tree before and after to prove it.
- A failing gate deletes nothing. The claim stays what it always was.
