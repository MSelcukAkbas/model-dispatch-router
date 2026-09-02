---
name: antigravity-usage-limit-delegation-bias
description: "User wants Claude's own usage/context limits (not just dollar cost) factored into agy delegation decisions — bias toward delegating context-hungry work"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 
  modified:
---

When deciding whether to delegate a task to Antigravity's `agy` CLI, weigh
Claude's own usage limits as a driver, not just the dollar-cost framing the
`antigravity` plugin's built-in policy already applies.

**Why:** the user explicitly asked me to know my own Claude Code usage
limitations and use agy "with that in mind so it's best of both worlds."
Claude Code sessions are capped on an axis agy isn't — a rolling
session/weekly usage limit tied to the user's plan, plus a hard
per-conversation context ceiling whose overflow forces lossy
auto-summarization of the conversation. agy runs on the user's separate
Google/Antigravity quota, so spending its tokens doesn't touch either Claude
limit at all.

**How to apply:** bias slightly more aggressive toward delegating anything
that would otherwise burn Claude's context or usage window for work that
doesn't need Claude's judgment (long-context reads that reduce to a digest,
bulk generation, exhaustive search) than a pure dollar-cost calculation alone
would suggest — Claude's usage is the resource that actually blocks or
degrades the user's session, not agy's. This doesn't lower the floor: a
cheap, judgment-free lookup (running one existing script, a single small
edit) still belongs to Claude directly, since delegating those is a net loss
on round-trip cost regardless of usage limits.

The durable, edit-in-place version of this lives in
[[antigravity-claude-delegation-setup]]'s policy doc at
`~/Workspace/Agents/antigravity-delegation-policy.md` (section "Claude's own
usage limits are a delegation driver, not just cost") — this memory exists so
the rationale carries across sessions even without reading that file.
