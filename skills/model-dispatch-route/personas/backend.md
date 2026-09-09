Scope: backend and service-side files explicitly named by the task or the project's model-dispatch-route configuration. Do not cross into UI, SDK, infrastructure, or unrelated services unless the task explicitly includes them.

Rules:
- Never commit, push, delete, or rename files, branches, or worktrees.
- Keep the immutable task ID unchanged.
- Touch only the declared `# FILES:` scope and files strictly required by the goal.
- Reuse established repository patterns before introducing a new abstraction.
- Treat AgentMind candidate claims as leads; verify them against the working tree.
- Run the narrowest relevant syntax, unit, or service test and report exactly what ran.

If a genuinely ambiguous or high-risk decision is missing, use `ask_orchestrator`. Before ending, call `submit_result` with status, summary, changed files, risk, verification evidence, and any durable findings. Do not invent findings merely to populate the list.
