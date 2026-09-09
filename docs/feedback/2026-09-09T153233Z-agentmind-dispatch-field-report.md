---
title: "AgentMind Model Dispatch field report: successful artifact, orphaned lifecycle"
type: feedback
created_utc: 2026-09-09T15:32:33Z
reporter_host: Codex
plugin: agentmind-model-dispatch-router
plugin_version: 0.2.0+codex.20260908221819
agentmind_version: 0.1.0
source_commit_reviewed: 106cf5610b7b02519d25653261389296f5d600fd
dispatch_task: T-000001
dispatch_engine: claude
dispatch_model: claude-sonnet-4-6
dispatch_role: design
severity: high
status: reproducible-from-retained-artifacts
---

# AgentMind Model Dispatch field report

## 1. Executive summary

This report documents a real Codex-to-Claude dispatch against a repository with staged and
untracked changes. The user wanted Claude's larger context/output budget used to produce a detailed
API-key-management implementation plan while Codex retained review, apply, verification, commit,
and push authority.

The user-visible outcome succeeded:

- Claude produced the requested plan in an isolated snapshot worktree.
- The scope checker accepted every changed path.
- Codex reviewed and corrected the plan before applying it.
- `apply.sh` imported exactly one document without staging, committing, or pushing.
- Codex subsequently ran repository tests and disposable-database validation.

The control-plane outcome did not succeed:

- The first detached attempt became orphaned when its launching execution host ended.
- A second attempt completed only while an attached waiter kept the host execution alive.
- Claude's first rich `submit_result`, containing six findings, failed after about 28 seconds with
  `MCP error -32000: Connection closed`.
- A later minimal `submit_result` succeeded but contained no findings.
- The Claude transcript has a successful terminal result and Bridge state has `status: DONE`, yet
  no `final-status.json` or compatibility exit marker was published.
- `status.sh` and `collect.sh` still return exit 23, `orphaned`.
- AgentMind has no completion timestamp, graph nodes, or claims from the six findings.

The highest-value fix is to make core result persistence independent of optional embedding work
and independent of the wrapper process surviving long enough to invoke lifecycle finalization.

## 2. Versions and environment

### 2.1 Installed components

| Component | Observed value |
|---|---|
| Plugin | `agentmind-model-dispatch-router` |
| Plugin version | `0.2.0+codex.20260908221819` |
| AgentMind CLI | `agentmind 0.1.0` |
| Router source commit | `106cf5610b7b02519d25653261389296f5d600fd` |
| Claude Code | `2.1.81` |
| Claude model | `claude-sonnet-4-6` |
| Codex CLI | `0.153.4` |
| Node.js | `v22.23.2` |
| Git | `2.51.2` |
| Host | Linux `6.12.83`, x86_64 |
| AgentMind venv Python | `3.12.12` |
| Interactive shell Python | `3.13.12` |
| Shell | zsh |

AgentMind was correctly installed in a uv-managed Python 3.12 environment even though `uv` was
not available on the active shell `PATH` and the shell's default Python was 3.13.

### 2.2 Dispatch configuration

| Field | Value |
|---|---|
| Task | `T-000001` |
| Role | `design` |
| Engine | `claude` |
| Effort | `high` |
| Timeout | 25 minutes |
| Budget ceiling | USD 2.50 |
| Snapshot | enabled |
| Isolation | writer worktree |
| Bridge required | yes |
| Attempt recorded | 2 |
| Session ID | `e1c60ddb-db16-4679-9c62-2e0a40269df3` |

Invocation shape:

```sh
bash skills/model-dispatch-router/scripts/dispatch.sh \
  design T-000001 .agent-logs/prompts/T-000001.txt \
  --timeout 25 --effort high --budget 2.50 --snapshot
```

The prompt declared 15 existing/staged paths plus one permitted output document. No secret values
were included.

## 3. Scenario and intended contract

The target repository contained a large staged change involving API-key schema, OpenBao-to-ESO
pepper delivery, gateway authentication, security-event telemetry, and supporting documentation.
The dispatched task had one bounded write outcome: synthesize those inputs into a next-steps plan.

The orchestration contract was:

1. Materialize dirty inputs using `--snapshot`.
2. Let Claude write only the plan in its worktree.
3. Monitor lifecycle status rather than trusting a PID.
4. Inspect `diff.sh` before import.
5. Apply only the reviewed patch.
6. Verify locally with Codex.
7. Leave commit/push authority with Codex and the user.

## 4. Timeline and observations

Times are UTC and reconstructed from retained task artifacts and the orchestration transcript.

### 4.1 Workspace setup

1. `am status` initially reported no store for the target repository.
2. The first `am setup .` failed when writing the user-level registry under
   `~/.agentmind/workspaces`; the managed sandbox allowed repository writes but not arbitrary home
   writes.
3. Re-running setup with explicit elevated filesystem permission succeeded.
4. `am hooks-install . --platform all` configured Codex, Claude, and Antigravity lifecycle files.
5. Those hook files stayed out of Git status, consistent with local/ignored integration state.

Post-setup, AgentMind still reported `0 nodes, 0 edges`. The graph extra imports successfully, but
`am context` returns no match and `am why` returns no claims.

### 4.2 Prompt generation

`am prompt` could not generate context because the graph was empty:

```text
nothing in the graph matched '<task>'
```

It exited 1 and did not create an output file. Codex created a manual prompt with the required
`# GOAL` and `# FILES` headers. This is safe behavior, but first-run users reach a dead end without
an obvious context-free fallback.

### 4.3 Preflight and routing

The health check reported Git, worktrees, Claude CLI, and disk space as healthy. Quota was
`unknown`, with `quota_ok: false`; dispatch correctly treated that as fail-open. Routing evidence
was initially `none` and became `anecdotal` after one recorded run, appropriately avoiding a claim
of measured routing quality.

### 4.4 First dispatch attempt

The first invocation returned after starting its background subshell. Its execution host then
ended before a stable lifecycle/result record was produced, and the runner became orphaned.

This is consistent with the current launch pattern:

```sh
(
  # run engine, finalize, session-end
) &
```

There is no `nohup`, `setsid`, service manager, or foreground `--wait` mode protecting it from
harnesses that reap background children or close the PTY/process group when the foreground command
returns.

### 4.5 Second dispatch attempt

The same task ID was redispatched while an attached `wait.sh` invocation kept the execution host
alive. The recorded run started at `2026-09-09T14:25:14.020Z`. Claude worked for approximately
8 minutes 12 seconds and created the plan.

| Metric | Value |
|---|---:|
| Duration | 492,450 ms |
| API duration | 489,433 ms |
| Turns | 27 |
| Output tokens | 25,141 |
| Cache creation input tokens | 110,685 |
| Cache-read input tokens | 1,110,579 |
| Total cost | USD 1.12545045 |
| Terminal subtype | `success` |
| Stop reason | `end_turn` |

### 4.6 Rich result failure and minimal retry

Claude's first `submit_result` included `DONE`, summary, changed files, verification, risk, and six
structured findings with file/line evidence. It failed with:

```text
MCP error -32000: Connection closed
```

The call-to-error interval was approximately 28 seconds. The Bridge processes all finding
embeddings before persisting the result:

```js
const { written, skipped } = await writeFindings(args.findings, taskId, sourceRole);
withLock(taskId, (state) => { state.result = record; });
```

The embedding layer may wait 25 seconds for cold Ollama startup and then up to 10 seconds for a
request. Findings are sequential. The server also exits immediately when stdin closes:

```js
process.stdin.on('end', () => process.exit(0));
```

Evidence strongly suggests the rich call crossed the MCP client's lifetime while waiting on
optional embedding work. This is a root-cause hypothesis, not a captured stack trace, but the code
and timings align closely.

Claude retried with a minimal payload containing no findings. It succeeded at
`2026-09-09T14:33:25.694Z`. Retained Bridge state consequently says `DONE` but contains:

```json
{
  "findings_written": 0,
  "findings_skipped": []
}
```

The six useful claims from the first submission were lost.

### 4.7 Engine completion without lifecycle completion

The JSONL transcript ends with valid Claude terminal success, and Bridge state independently has a
valid `DONE`. The runner disappeared before creating either:

- `.agent-logs/T-000001.final-status.json`; or
- `.agent-logs/T-000001.exitcode`.

Current status remains:

```text
orphaned: task=T-000001 — Runner identity missing, gone, or changed; inspect captured output
```

Both `status.sh` and `collect.sh` return 23. Collection recovers the final response and cost but
also labels the same response as a partial checkpoint because task state is nonzero. AgentMind
coverage reports `finished_at: 0/1`.

### 4.8 Review and import

The repository-safety path worked despite lifecycle failure:

- JSONL retained 647,811 bytes of output.
- Pinned runtimes retained the exact scripts/personas used by both attempts.
- Snapshot metadata retained original head, scoped tree, exact paths, and pinned ref.
- `diff.sh` found exactly one new output document.
- Scope validation accepted every changed path.
- `apply.sh` imported one path without staging.
- The main index and its staged state stayed intact.
- `verify.sh` reported no supported-file syntax failures.
- Codex performed semantic review and corrected repository-specific errors before commit.

## 5. Findings and recommendations

### F1 — Background runner is not durable across command-host exit

**Priority:** P1

The documented asynchronous contract is not portable to execution hosts that terminate background
children after the foreground command exits.

Recommended changes:

1. Add `dispatch.sh --wait`; recommend it by default for headless orchestration.
2. Make detached mode durable with `setsid`/`nohup` and fully redirected descriptors on Unix, or a
   small persistent runner process.
3. Have the parent wait until `run.json` exists and process identity is confirmed.
4. Return a distinct launch failure if the child disappears during that handshake.
5. Document detached-mode host/process-lifetime assumptions.

Acceptance test: launch a fixture from a shell that exits immediately; require terminal status and
`final-status.json` without an attached waiter.

### F2 — Successful engine output can remain permanently orphaned

**Priority:** P1

Valid terminal success plus valid Bridge `DONE` exists, but missing wrapper finalization produces
status 23 forever.

Recommended changes:

1. If the runner is gone and final status is missing, classify durable engine output and Bridge
   state before returning orphaned.
2. If semantic completion is provable, atomically synthesize `done_recovered`, or expose
   `task.sh recover-finalize`.
3. Track wrapper/session-end incompleteness separately from engine success.
4. Never require users to infer completion manually when two durable artifacts agree.

Acceptance test: create `run.json` with a dead PID, successful Claude result, and Bridge `DONE`, but
no final status; require a recoverable completion state.

### F3 — Optional embedding is on the critical result path

**Priority:** P0/P1

Embeddings are described as fail-soft, but their latency can prevent mandatory result persistence
and acknowledgement.

Recommended changes:

1. Persist status, summary, changed files, risk, verification, and raw findings immediately.
2. Acknowledge only after that core atomic write.
3. Enrich/index findings asynchronously or in a bounded post-persistence phase.
4. Bound total enrichment below MCP client timeout.
5. Process embeddings with a small concurrent pool rather than sequentially.
6. Track enrichment as `pending`, `complete`, `partial`, or `failed`.
7. Store findings for BM25 even when vectors are unavailable.

Acceptance test: keep Ollama unavailable beyond 25 seconds. Core result must be quickly durable and
acknowledged, with raw findings retained for deferred/no-vector indexing.

### F4 — MCP server does not drain in-flight async work

**Priority:** P1

`process.stdin.on('end', () => process.exit(0))` may kill an async handler during persistence or
embedding.

Recommended changes:

1. Track in-flight handler promises.
2. On stdin end, stop accepting messages and drain handlers with a bounded grace period.
3. Persist core result before slow awaits.
4. Emit a sidecar diagnostic if graceful drain times out.

Acceptance test: close stdin during slow enrichment; the core result must remain readable and the
process must not exit before its atomic write.

### F5 — A smaller retry can erase richer findings

**Priority:** P1

The successful minimal retry replaced the intended rich result. AgentMind ended with zero claims
although the transcript contains six findings.

Recommended changes:

1. Add an idempotency key per logical submission.
2. Make updates monotonic: retries may add information but must not delete findings or richer risk
   and verification data.
3. Persist raw findings before enrichment.
4. Return the prior recorded result on duplicate submission.
5. If necessary, separate result and finding durability boundaries.

Acceptance test: persist a rich result, drop its response, then retry minimal; all rich fields must
remain.

### F6 — Setup can appear complete while graph remains empty

**Priority:** P1/P2

The graph extra is installed, but the non-empty JavaScript/SQL target remained at zero graph nodes.

Recommended changes:

1. Print structured setup counts: discovered, parsed, skipped, nodes, edges, and errors.
2. Return nonzero or prominent degraded state when a non-empty repository yields zero nodes.
3. Add `am doctor --graph` for parser/dependency diagnostics.
4. Let `am prompt` optionally emit a context-free goal/files template while clearly labeling zero
   injected memory.

### F7 — Global registry conflicts with repository-only sandboxes

**Priority:** P2

`am setup` required elevation because it writes outside the repository.

Recommended changes:

1. Document the global path before setup.
2. Support repository-local registry or a configurable registry location.
3. On permission denial, print the exact path and minimal remediation.
4. Do not report complete setup until local store and registry are consistent.

### F8 — Git subprocesses fail opaquely under managed sandboxes

**Priority:** P2

`diff.sh` and `apply.sh` initially hit `spawnSync git EPERM`; explicit elevation worked.

Recommended changes:

1. Distinguish `EPERM` from repository/scope failure.
2. State the read/write capability each command needs.
3. Publish a sandbox permission profile for setup, worktree, diff, and apply.
4. Keep fail-closed scope behavior.

### F9 — Verification can skip the dispatched artifact

**Priority:** P2

The only dispatched output was Markdown. `verify.sh` skipped Markdown/YAML/SQL and reported four
JavaScript passes belonging to other staged changes, which can be mistaken for task verification.

Recommended changes:

1. Accept task ID and focus on that task's applied paths.
2. Report checked versus skipped task-output files separately from unrelated changes.
3. Return a distinct degraded state when no dispatched output has a checker.
4. Support repository-configured Markdown-link/style, YAML, and SQL checks.

### F10 — Packaged scripts are mode 0644

**Priority:** P3

Source and installed `dispatch.sh`, `status.sh`, `diff.sh`, `apply.sh`, and `verify.sh` are not
executable. `bash script.sh` works and examples generally use that form, so this is friction rather
than a correctness defect.

Recommendation: ship mode 0755 and test packaging, or explicitly require `bash` beside the command
table.

### F11 — Ambient Claude plugins inflate isolated dispatch context

**Priority:** P2

The session loaded unrelated SessionStart hooks and a large ambient skill/plugin catalog.
AgentMind injected `0 tokens, 0 claims`, yet the run used over 1.1 million cache-read and 110,685
cache-creation input tokens. Not all overhead belongs to the router, and caching reduced cost, but
file isolation did not imply configuration isolation.

Recommended changes:

1. Offer a minimal generated `CLAUDE_CONFIG_DIR` by default.
2. Make ambient plugin inheritance opt-in.
3. Preflight which hooks/plugins will execute.
4. Report context size by source: persona, AgentMind, ambient hooks, and user prompt.

### F12 — Lifecycle evidence and outcome accounting diverge

**Priority:** P1

AgentMind knows one launch but has no `finished_at`. Bridge says done, engine says success, lifecycle
says orphaned, and the patch was later applied and verified. These facts are not reconciled.

Recommended changes:

1. Track engine outcome, Bridge delivery, wrapper finalization, session-end, patch apply, and gate
   verification as separate fields.
2. Let a later apply/gate attach outcome evidence to a recovered dispatch.
3. Make `am coverage` name the missing completion boundary.
4. Do not train routing advice on launch count as if it were outcome evidence.

## 6. What worked well

### 6.1 Snapshot mode preserved staged work

`--snapshot` materialized the declared dirty scope without disturbing the main index. Snapshot
metadata retained original head, scoped tree, path manifest, and pinned snapshot ref.

### 6.2 Scope enforcement was effective

Claude changed one file. `diff.sh` displayed it and reported:

```text
Scope manifest accepted every changed path.
```

No unrelated file was imported.

### 6.3 Streamed JSONL enabled recovery

The 647 KB transcript retained final response, cost, turns, calls, checkpoint, MCP error, retry,
and terminal success. Without stream-json persistence, the lifecycle failure could have caused
total work loss.

### 6.4 Runtime pinning preserved reproducibility

Each attempt retained the exact scripts/personas it used, allowing diagnosis after plugin changes.

### 6.5 Apply retained orchestrator control

`apply.sh` imported one path and did not stage, commit, or push. Codex could review and correct the
artifact before the repository owner accepted it.

### 6.6 Collection degraded usefully

Although it returned 23, `collect.sh` printed the best terminal response and cost instead of
discarding them.

### 6.7 Cleanup is consent-sensitive

Cleanup explicitly deletes the worktree, branch, logs, and snapshot ref, so the retained evidence
was not automatically destroyed after an ambiguous lifecycle. This is the correct safety default.

## 7. Suggested implementation order

### Immediate reliability

1. Persist core Bridge result before embeddings.
2. Drain/bound in-flight MCP work on stdin closure.
3. Make retries monotonic and idempotent.
4. Recover terminal success when wrapper finalization is missing.
5. Add durable or synchronous dispatch launch behavior.

### Next usability

6. Diagnose zero-node setup explicitly.
7. Make verification task-output-aware.
8. Improve sandbox diagnostics and registry location control.
9. Isolate ambient Claude configuration or report its cost.
10. Resolve executable-mode/documentation ambiguity.

## 8. Proposed regression matrix

| Test | Fault injected | Expected result |
|---|---|---|
| Detached-parent exit | Launcher exits immediately | Task continues and finalizes |
| Finalize interruption | Kill wrapper after terminal success | Recover success with hook-incomplete metadata |
| Cold Ollama | Embedding startup exceeds MCP timeout | Core result acknowledged; findings retained |
| Stdin closure | Close MCP stdin during enrichment | Core write drains before exit |
| Lost acknowledgement | Persist rich result, retry minimal | Rich fields/findings remain |
| Missing graph | Non-empty repo yields zero nodes | Explicit extraction diagnosis |
| Repository-only sandbox | Home registry unwritable | Local mode or actionable error |
| Git spawn denied | `spawnSync git` gives EPERM | Capability-specific error, no partial apply |
| Markdown-only patch | No built-in checker | Task output reported unverified, not generic pass |
| Dirty snapshot | Main index has scoped changes | Worktree sees them; main index unchanged |
| Scope escape | Agent edits undeclared path | Diff/apply refuse |
| Cache update mid-run | Plugin installation changes | Pinned runtime completes unchanged |

## 9. Evidence inventory

The original artifacts are intentionally not copied into this repository because they contain a
full model transcript and machine-specific paths.

| Artifact | Evidence |
|---|---|
| `T-000001.run.json` | run ID, PID identity, Bridge requirement, start time |
| `T-000001.meta` | role, timeout, effort, budget, attempt, snapshot |
| `T-000001.json` | transcript, MCP failure/retry, terminal success, cost |
| `T-000001.bridge.json` | minimal Bridge `DONE`, zero findings |
| `T-000001.checkpoint.json` | last tool and connection-closing summary |
| `T-000001.snapshot.json` | snapshot head/tree/scope/ref |
| `T-000001.scope` | exact allowed paths |
| `T-000001.agentmind-start.log` | `0 tokens, 0 claims` |
| `T-000001.err` | empty engine stderr |
| `runtimes/T-000001/*` | exact scripts/personas used |

Retained sizes at report time:

- Claude JSONL transcript: about 636 KiB on disk;
- task runtime snapshots: about 1.7 MiB;
- repository AgentMind state: about 180 KiB.

## 10. Final assessment

The router protected the repository better than it tracked the task. Worktree isolation, snapshot
materialization, scope enforcement, streamed recovery, and controlled apply delivered real value.
The artifact survived and was useful.

The weak boundary is completion durability. Optional knowledge enrichment, MCP lifetime,
background-process lifetime, wrapper finalization, and AgentMind accounting are too tightly
coupled. A successful model task can look permanently orphaned, lose structured findings, and
provide no outcome data to routing decisions.

Result-first persistence and terminal-output recovery would convert this incident from a manual
forensic exercise into clean, automatic recovery.
