"""The verification gate: the one thing that is never delegated.

Every claim in the store arrives as ``candidate``. Nothing an agent says about
its own work promotes it — only this gate does, and only when checks that run
here, on this machine, all pass. That asymmetry is the point: the existing
system's own notes record an agent reporting a green test run that had not
happened, and a warning in a document cannot prevent that twice. A schema
constraint can.

The checks are deliberately boring and deterministic:

* every cited file still exists
* every citation still binds to a node in the graph
* no cited file has uncommitted changes (evidence must describe committed code)
* nothing has touched the cited files since the claim was recorded
* optionally, a project command the caller supplies exits zero

A claim is promoted only if every applicable check passes. A failing gate never
deletes anything — the claim stays a candidate, which is exactly what it is.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .freshness import commits_since_evidence, is_dirty
from .store import Repository, utcnow


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class GateResult:
    task_id: str
    checks: list[Check] = field(default_factory=list)
    claims: int = 0
    promoted: int = 0
    skipped: int = 0

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)


def run_command(command: str, cwd: Path | str, timeout: int = 900) -> Check:
    """Run the caller's own verification command. Exit zero is the only pass."""
    try:
        proc = subprocess.run(
            command, cwd=str(cwd), shell=True, capture_output=True,
            text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return Check("command", False, f"timed out after {timeout}s: {command}")
    except OSError as exc:
        return Check("command", False, f"could not run: {exc}")

    tail = (proc.stdout + proc.stderr).strip().splitlines()
    detail = tail[-1][:200] if tail else f"exit {proc.returncode}"
    return Check("command", proc.returncode == 0, detail)


def evaluate_task(
    repo: Repository,
    task_id: str,
    src: Path | str,
    *,
    command: str | None = None,
    promote: bool = False,
) -> GateResult:
    root = Path(src).expanduser().resolve()
    result = GateResult(task_id=task_id)
    claims = repo.claims_for_task(task_id)
    result.claims = len(claims)

    if not claims:
        result.checks.append(Check("claims", False, f"no claims for task {task_id}"))
        return result

    refs = repo.refs_for_task(task_id)
    files = sorted({r["file"] for r in refs if r["file"]})

    missing = [r["file"] for r in refs if r["reason"] == "file_missing"]
    result.checks.append(
        Check(
            "evidence_present",
            not missing,
            "all cited files exist" if not missing
            else f"{len(missing)} missing: {', '.join(sorted(set(missing))[:3])}",
        )
    )

    unbound = [r["file"] for r in refs if r["dangling"]]
    result.checks.append(
        Check(
            "evidence_resolves",
            not unbound,
            "every citation binds to a node" if not unbound
            else f"{len(unbound)} unbound: {', '.join(sorted(set(unbound))[:3])}",
        )
    )

    dirty = [f for f in files if is_dirty(root, f)]
    result.checks.append(
        Check(
            "evidence_clean",
            not dirty,
            "cited files match HEAD" if not dirty
            else f"{len(dirty)} with uncommitted changes: {', '.join(dirty[:3])}",
        )
    )

    stale: list[str] = []
    unknown = 0
    for claim in claims:
        claim_files = sorted({
            r["file"] for r in refs if r["claim_id"] == claim["id"] and r["file"]
        })
        moved = commits_since_evidence(root, claim["commit_sha"], claim_files)
        if moved is None:
            unknown += 1
        elif moved > 0:
            stale.append(f"#{claim['id']}({moved})")
    detail = "no commits since the evidence was recorded"
    if stale:
        detail = f"{len(stale)} claim(s) outdated: {', '.join(stale[:4])}"
    elif unknown:
        detail = f"{unknown} claim(s) unanswerable (no commit_sha or sha gone)"
    # Unknown is not a pass: "cannot tell" must never be recorded as "verified".
    result.checks.append(Check("evidence_fresh", not stale and not unknown, detail))

    if command:
        result.checks.append(run_command(command, root))

    if promote and result.passed:
        for claim in claims:
            if claim["status"] == "candidate":
                repo.promote_claim(claim["id"], commit_sha=claim["commit_sha"])
                result.promoted += 1
            else:
                result.skipped += 1

    repo.add_event(
        "gate.passed" if result.passed else "gate.failed",
        task_id=task_id,
        actor="am gate",
        payload={
            "checks": {c.name: c.ok for c in result.checks},
            "claims": result.claims,
            "promoted": result.promoted,
            "command": command,
        },
    )
    return result


def graph_delta(repo: Repository, repo_name: str, src: Path | str) -> dict:
    """Compare the stored graph against a fresh extraction of the same tree.

    This is the check that catches a report saying "I changed one function"
    when the structure moved far more than that. graphify computes the diff;
    we only supply the two graphs.
    """
    from graphify.analyze import graph_diff

    from .context import load_graph
    from .resolver import build_graph

    before = load_graph(repo, repo_name)
    files = [
        row["source_file"]
        for row in repo.all_nodes(repo_name)
        if row["source_file"]
    ]
    build_graph(repo, src, repo_name=f"{repo_name}__probe", only_files=sorted(set(files)))
    after = load_graph(repo, f"{repo_name}__probe")
    repo.drop_graph(f"{repo_name}__probe")

    diff = graph_diff(before, after)
    diff["checked_at"] = utcnow()
    return diff
