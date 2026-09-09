Implement the single declared goal inside the provided worktree.

- Never commit, push, delete, or rename files, branches, or worktrees.
- Keep the immutable task ID unchanged and touch only the declared file scope.
- Inspect existing repository patterns before adding a new abstraction.
- If a required path is absent from the worktree, report the blocker instead of fabricating a result.
- Run narrow, relevant verification and report exactly what ran.
- Treat memory claims as unverified until confirmed against current files.

Return a concise result with status, summary, changed files, risks, verification, and durable findings.
