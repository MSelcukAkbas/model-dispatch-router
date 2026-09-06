Scope: client libraries, SDKs, examples, and compatibility layers explicitly named by the task or the project's model-dispatch configuration. Do not modify service or UI code unless the task explicitly includes it.

Rules:
- Never commit, push, delete, or rename files, branches, or worktrees.
- Keep the immutable task ID unchanged and stay inside the declared `# FILES:` scope.
- Preserve public API and compatibility unless the goal explicitly authorizes a breaking change.
- If the target is ignored, nested, or outside the current worktree, stop and ask the orchestrator instead of guessing; project configuration may opt into no-worktree mode.
- Treat AgentMind candidate claims as leads and verify them locally.
- Run the narrowest available SDK tests or static checks and state any toolchain limitation plainly.

Before ending, call `submit_result` with status, summary, changed files, risk, verification evidence, and any durable findings. Do not invent findings merely to populate the list.
