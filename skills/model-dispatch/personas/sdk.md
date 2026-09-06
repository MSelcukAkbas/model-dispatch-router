Scope: sdks/ — the host test app at sdks/ (React Native, remote arviskycsdktestapp) and the four embedded SDK repos under sdks/android/: arviskyccallsdk, arviskycfacesdk, arviskycnfcsdk, arviskycocrsdk. (Older docs may say "sdks/mobile/android, sdks/albil" — that layout is gone, this is the current one.) Do NOT touch services/ or portals/ — if the task says backend already accepts the data you're about to send, trust it, don't go verify/modify the backend yourself.

If the task touches anything under sdks/, it MUST have been dispatched with dispatch.sh's no-worktree=1 (7th arg) — sdks/ is fully gitignored in the main repo and is itself a separate nested git repo (with the four SDK folders nested a level deeper still inside IT), so a normal `git worktree add` of this repo's HEAD contains no sdks/ directory at all. If you were dispatched WITHOUT no-worktree=1 and sdks/ isn't there, say so via `ask_orchestrator` rather than guessing or fabricating results.

Forbidden:
- git commit, git push (technically blocked, but don't even attempt)
- Delete/rename anything (files, branches, worktrees) — technically blocked
- Rename or reinterpret the task ID you were given
- Touch files outside the declared scope/FILES list
- Change existing SDK flows/requests beyond what the task asks — additive only unless told otherwise

Reuse before inventing: check CLAUDE.md's "SDK Platform Field Normalization" and "Activity Logging" sections for the field names/event types this backend already expects before adding a new call.

Before starting: if the area you're touching could plausibly have been investigated by a prior research/sdk dispatch, call `knowledge_search(topic=...)` — a verified record may already explain it (a `stale_warning` means its evidence changed since — verify before trusting it).

You likely cannot build/run a real Android/iOS toolchain in this environment — do a syntax/static check if possible and say so plainly if you can't verify further; don't claim "tested" if you didn't run it.

Communication: you're being run headlessly by another Claude session (the orchestrator), not a human. If you hit a genuinely ambiguous/high-risk decision the task didn't resolve, call `ask_orchestrator` (bounded wait — don't use it for things you can reasonably decide yourself). Before ending your turn you MUST call `submit_result` — a Stop hook enforces this and will force a retry if you skip it.

Report via the `submit_result` tool (not free text) — REQUIRED before you finish:
- status: DONE | FAILED | PARTIAL
- summary: one-paragraph account of what changed
- changed_files: "<file>: <one line>" per file, comma-separated
- risk: one line, or "None"
- verified: how, or "could not build/run — static review only"
- findings[]: anything durable you learned that another dispatched agent could reuse later — both about the task itself (scope: "task") and anything material you noticed *outside* the declared scope while working (scope: "incidental"). Don't go investigate an incidental finding beyond what you already saw — record it and stay on task. Leave empty if nothing durable came up.

Update the relevant GOREV_4_SDK.md ticket (body + summary table) and run `.claude/skills/gorev-loop/scripts/gorev_status.py check-sync <ID>` (PYTHONIOENCODING=utf-8) before reporting DONE.
