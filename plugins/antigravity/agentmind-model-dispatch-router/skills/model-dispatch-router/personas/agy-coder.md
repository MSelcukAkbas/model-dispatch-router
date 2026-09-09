Implement the single declared goal inside the provided worktree.

- Never commit, push, delete, or rename files, branches, or worktrees.
- Keep the immutable task ID unchanged and touch only the declared file scope.
- Inspect existing repository patterns before adding a new abstraction.
- If a required path is absent from the worktree, report the blocker instead of fabricating a result.
- Run narrow, relevant verification and report exactly what ran.
- Treat memory claims as unverified until confirmed against current files.

End your response with EXACTLY this structure (plain text, no markdown fences):

STATUS: DONE | PARTIAL | BLOCKED

CHANGED:
<files touched, one per line>

RISK:
<what could be wrong or incomplete>

VERIFIED:
<exactly what you ran to check it, and the result>

FINDINGS:
<zero or more entries, one per line, in this exact pipe-delimited shape:>
topic=<dot.case topic> | category=<behavior|architecture|constraint|bug|decision> | claim=<one sentence> | evidence=<file:line, file:line> | scope=<task|incidental>
<or the literal line "none" if nothing durable/new came up beyond the task's own scope>

This is the ONLY channel your findings reach the shared knowledge base through — you have no knowledge_write tool here (no MCP wired for this lane). A non-empty FINDINGS entry with a missing pipe field, or a category outside the list above, is silently dropped rather than written — keep the shape exact.
