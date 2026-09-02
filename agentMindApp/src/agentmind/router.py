"""Routing advice, with the evidence behind it stated plainly.

The plan called this the "measured router". The data does not support that
word yet, and saying it anyway would be the exact failure this system exists to
prevent — a confident claim with nothing checking it. So this module does two
separate things and never blurs them:

* It makes the existing policy explicit. The rules already live in
  model-dispatch's SKILL.md and in its ROLE_MODEL/ROLE_EFFORT arrays, as prose
  and as bash. Here they are data, so a recommendation can be inspected and
  argued with.
* It reports what the recorded history actually says about each rule, and how
  much history that is. A rule backed by nine dispatches says so; a rule backed
  by none says that too.

When those two disagree, the disagreement is the output. That is the useful
part — not a number pretending to be a decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .store import Repository

# From model-dispatch/SKILL.md and dispatch.sh's ROLE_MODEL / ROLE_EFFORT /
# ROLE_MAX_BUDGET_USD arrays. Encoded, not invented.
POLICY: dict[str, dict[str, object]] = {
    "backend": {"engine": "claude", "model": "sonnet", "effort": "high", "budget": 1.50},
    "design": {"engine": "claude", "model": "sonnet", "effort": "high", "budget": 2.50},
    "sdk": {"engine": "claude", "model": "sonnet", "effort": "high", "budget": 2.00,
            "note": "sdks/ is a nested gitignored repo - dispatch with no-worktree=1"},
    "general": {"engine": "claude", "model": "sonnet", "effort": "medium", "budget": 1.00},
    "ops": {"engine": "claude", "model": "sonnet", "effort": "high", "budget": 2.00,
            "note": "only role with ssh-mcp; SSH command content is not filtered"},
    "research": {"engine": "agy", "model": "gemini", "effort": "low", "budget": 0.50,
                 "note": "agy first by user decision (2026-08-27) - its quota is "
                         "separate from every Claude account"},
    "judge": {"engine": "agy", "model": "gemini", "effort": "high", "budget": 4.00,
              "note": "agy first; falls back to Claude opus"},
}

# How much history a rule needs before its numbers mean anything. Deliberately
# blunt: with a handful of dispatches a retry rate is noise, and presenting it
# as a finding would be worse than presenting nothing.
CONFIDENCE_BANDS = ((30, "moderate"), (10, "weak"), (1, "anecdotal"), (0, "none"))


def confidence(n: int) -> str:
    for threshold, label in CONFIDENCE_BANDS:
        if n >= threshold:
            return label
    return "none"


@dataclass
class Evidence:
    dispatches: int = 0
    retried: int = 0
    retry_known: int = 0
    claims: int = 0
    accounts: dict[str, int] = field(default_factory=dict)

    @property
    def confidence(self) -> str:
        return confidence(self.dispatches)

    @property
    def retry_rate(self) -> float | None:
        if not self.retry_known:
            return None
        return self.retried / self.retry_known

    @property
    def claims_per_task(self) -> float:
        return self.claims / self.dispatches if self.dispatches else 0.0


@dataclass
class Recommendation:
    role: str
    engine: str
    model: str
    effort: str
    budget: float
    note: str = ""
    evidence: Evidence = field(default_factory=Evidence)
    warnings: list[str] = field(default_factory=list)


def gather_evidence(repo: Repository, role: str, engine: str | None = None) -> Evidence:
    rows = repo.tasks_for_role(role, engine=engine)
    ev = Evidence(dispatches=len(rows))
    for row in rows:
        if row["attempt"] is not None:
            ev.retry_known += 1
            if row["attempt"] > 1:
                ev.retried += 1
        account = row["account"] or ("n/a" if row["engine"] == "agy" else "ambient")
        ev.accounts[account] = ev.accounts.get(account, 0) + 1
    ev.claims = repo.claims_from_role(role, engine=engine)
    return ev


def recommend(repo: Repository, role: str) -> Recommendation:
    rule = POLICY.get(role)
    if rule is None:
        raise KeyError(role)

    engine = str(rule["engine"])
    rec = Recommendation(
        role=role,
        engine=engine,
        model=str(rule["model"]),
        effort=str(rule["effort"]),
        budget=float(rule["budget"]),
        note=str(rule.get("note", "")),
        evidence=gather_evidence(repo, role, engine=engine),
    )

    ev = rec.evidence
    if ev.dispatches == 0:
        rec.warnings.append(
            f"no recorded {role} dispatch on {engine} - this is policy only, "
            "nothing has tested it here"
        )
    if ev.retry_rate is not None and ev.retry_rate >= 0.4 and ev.retry_known >= 5:
        rec.warnings.append(
            f"{ev.retried} of {ev.retry_known} recorded runs needed a second "
            f"attempt ({ev.confidence} evidence) - worth looking at before "
            "spending more here"
        )
    if ev.dispatches >= 10 and ev.claims == 0:
        rec.warnings.append(
            f"{ev.dispatches} dispatches on {engine} produced no claims at all - "
            "whatever they found did not reach the knowledge store"
        )
    return rec


def memory_gaps(repo: Repository) -> list[dict]:
    """Engine/role pairs that run often and remember nothing.

    A dispatch that leaves no claim is work the next task cannot build on. This
    is the single clearest thing the recorded history says, and it is about
    plumbing rather than model quality.
    """
    gaps = []
    for row in repo.role_engine_counts():
        claims = repo.claims_from_role(row["role"], engine=row["engine"])
        if row["n"] >= 5 and claims == 0:
            gaps.append({
                "role": row["role"],
                "engine": row["engine"],
                "dispatches": row["n"],
                "claims": 0,
            })
    return gaps
