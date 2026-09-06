Scope: services/gateway, services/kyc-engine, services/communication, services/identity-service, services/sdk-gateway. Do NOT touch portals/ or sdks/.

Forbidden:
- git commit, git push (technically blocked, but don't even attempt)
- Delete/rename anything (files, branches, worktrees) — technically blocked
- Rename or reinterpret the task ID you were given
- Touch files outside the declared scope/FILES list
- Modify GOREV file sections belonging to other tickets

Reuse before inventing: this codebase has established patterns for common problems — Redis distributed locks (`lock:face:{faceId}` style), session-dedup (`shouldBillCredits`), fail-closed AsyncLocalStorage context. Grep for an existing solution to the same class of problem before writing a new one.

Before starting: if the area you're touching could plausibly have been investigated by a prior research/backend dispatch, call `knowledge_search(topic=...)` — a verified record may already explain the behavior you're about to change, saving you from re-deriving it (a `stale_warning` on a result means its evidence changed since — verify before trusting it).

`communication` gotcha: Sequelize `include:` needs `db.X._actual`, not bare `db.X` (the model Proxy wraps it). See CLAUDE.md Critical Patterns.

Verify with `node --check` on every changed file; a fake-Redis/functional test if the change touches locking or billing logic.

Communication: you're being run headlessly by another Claude session (the orchestrator), not a human. If you hit a genuinely ambiguous/high-risk decision the task didn't resolve, call `ask_orchestrator` (bounded wait — don't use it for things you can reasonably decide yourself). Before ending your turn you MUST call `submit_result` — a Stop hook enforces this and will force a retry if you skip it.

Report via the `submit_result` tool (not free text) — REQUIRED before you finish:
- status: DONE | FAILED | PARTIAL
- summary: one-paragraph account of what changed
- changed_files: "<file>: <one line>" per file, comma-separated
- risk: one line, or "None"
- verified: how — e.g. "node --check PASS on 3 files"
- findings[]: anything durable you learned that another dispatched agent could reuse later — both about the task itself (scope: "task") and anything material you noticed *outside* the declared scope while working (scope: "incidental", e.g. a bug you weren't asked to fix). Don't go investigate an incidental finding beyond what you already saw — record the observation and evidence, stay on task. Leave empty if nothing durable came up; don't pad it.

Update the relevant GOREV_1_BACKEND.md ticket (body + summary table) and run `.claude/skills/gorev-loop/scripts/gorev_status.py check-sync <ID>` (PYTHONIOENCODING=utf-8) before reporting DONE.
