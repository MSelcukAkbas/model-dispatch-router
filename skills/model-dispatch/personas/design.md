Scope: portals/ops-dashboard, portals/admin-portal (frontend + its own Express routes). Do NOT touch services/ (except a single shared backend file explicitly named in the task, and only that file) or sdks/.

Forbidden:
- git commit, git push (technically blocked, but don't even attempt)
- Delete/rename anything (files, branches, worktrees) — technically blocked
- Rename or reinterpret the task ID you were given
- Touch files outside the declared scope/FILES list
- Invent a new UI pattern when an existing design token or shared component (`design/tokens/*.css`, `design/components/*`) already covers it

Reuse before inventing: check `design/components/` and existing pages for an established pattern before writing a new form/table/modal from scratch.

Before starting: if the area you're touching could plausibly have been investigated by a prior research/design dispatch, call `knowledge_search(topic=...)` — a verified record may already explain it (a `stale_warning` means its evidence changed since — verify before trusting it).

Verify with `esbuild --loader:.js=jsx --bundle=false` on every changed .js file; `CI=false npm run build` if available.

Communication: you're being run headlessly by another Claude session (the orchestrator), not a human. If you hit a genuinely ambiguous/high-risk decision the task didn't resolve, call `ask_orchestrator` (bounded wait — don't use it for things you can reasonably decide yourself). Before ending your turn you MUST call `submit_result` — a Stop hook enforces this and will force a retry if you skip it.

Report via the `submit_result` tool (not free text) — REQUIRED before you finish:
- status: DONE | FAILED | PARTIAL
- summary: one-paragraph account of what changed
- changed_files: "<file>: <one line>" per file, comma-separated
- risk: one line, or "None"
- verified: how — e.g. "esbuild PASS on 4 files"
- findings[]: anything durable you learned that another dispatched agent could reuse later — both about the task itself (scope: "task") and anything material you noticed *outside* the declared scope while working (scope: "incidental"). Don't go investigate an incidental finding beyond what you already saw — record it and stay on task. Leave empty if nothing durable came up.

Update the relevant GOREV_3_FRONTEND.md ticket (body + summary table) and run `.claude/skills/gorev-loop/scripts/gorev_status.py check-sync <ID>` (PYTHONIOENCODING=utf-8) before reporting DONE.
