"""Bring the store up to date with a live repo, incrementally.

`setup` is the first run; this is every run after it, and it is what makes the
tool usable daily rather than occasionally. It closes the loop without editing
the repo it watches: no hook in dispatch.sh, no wrapper around the agent, no
write of any kind on the other side. The live repo keeps producing .meta files
and knowledge rows as it always has, and this reads them.

The cost is honest: a sync sees work only after it has happened, not as it
happens. That is the trade for leaving the observed repo untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .freshness import commits_since_evidence
from .importer import import_snapshot
from .resolver import build_graph, claim_evidence_files, resolve_claims
from .snapshot import take_snapshot
from .store import Repository


@dataclass
class SyncResult:
    corpus: str
    new_tasks: int = 0
    new_claims: int = 0
    new_files: list[str] = field(default_factory=list)
    graph_rebuilt: bool = False
    nodes: int = 0
    edges: int = 0
    refs: int = 0
    resolved: int = 0
    dangling: int = 0
    promoted_stale: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(
            self.new_tasks or self.new_claims or self.new_files or self.promoted_stale
        )


def _graph_files(repo: Repository, corpus: str) -> set[str]:
    return {
        row["source_file"]
        for row in repo.all_nodes(corpus)
        if row["source_file"]
    }


def _demote_stale_verified(repo: Repository, src: Path) -> int:
    """A verified claim whose evidence has since moved drops back to stale.

    Verification is anchored to a commit, not granted for good: the gate says
    "this held at that sha", and once the cited files move on, that sentence
    stops being about the code in the tree. Leaving it green would make the
    gate a one-time rubber stamp, which is the failure mode it exists to
    prevent.
    """
    demoted = 0
    for claim in repo.verified_claims():
        files = sorted({
            row["file"] for row in repo.refs_for_claim(claim["id"]) if row["file"]
        })
        moved = commits_since_evidence(src, claim["last_verified_commit"]
                                       or claim["commit_sha"], files)
        if moved:
            repo.set_claim_status(claim["id"], "stale")
            demoted += 1
    return demoted


def sync(
    repo: Repository,
    source: Path | str,
    workspace: Path | str,
    *,
    corpus: str | None = None,
    mark_stale: bool = True,
) -> SyncResult:
    src = Path(source).expanduser().resolve()
    name = corpus or src.name
    result = SyncResult(corpus=name)

    tasks_before = repo.count_tasks()
    claims_before = repo.count_claims()
    cited_before = set(claim_evidence_files(repo, name))

    snap = take_snapshot(src, Path(workspace) / "snapshots")
    imported = import_snapshot(repo, snap.dest, corpus=name)
    # Claims stored before corpus tracking existed would otherwise never
    # resolve again; attribute them to whichever tree actually holds them.
    repo.adopt_unassigned_claims(name, src)
    result.notes.extend(imported.notes)

    result.new_tasks = repo.count_tasks() - tasks_before
    result.new_claims = repo.count_claims() - claims_before

    cited = set(claim_evidence_files(repo, name))
    known = _graph_files(repo, name)
    # Newly cited means new to us this run. Comparing against the graph instead
    # made every unparseable-but-cited file (.yaml, .json) look new forever,
    # so no sync was ever a no-op.
    result.new_files = sorted(cited - cited_before)

    # Re-extract only when a claim points somewhere the graph has never seen.
    # graphify caches ASTs per file, so a rebuild after a small change is cheap,
    # but skipping it entirely when nothing new is cited keeps a no-op sync
    # genuinely instant.
    needs_extract = bool([f for f in result.new_files if (src / f).is_file()])
    if needs_extract or not known:
        built = build_graph(repo, src, repo_name=name, only_files=sorted(cited))
        result.graph_rebuilt = True
        result.nodes, result.edges = built.nodes, built.edges
        result.notes.extend(built.notes)
    else:
        result.nodes, result.edges = repo.count_graph(name)

    resolved = resolve_claims(repo, name, source_root=src)
    result.refs = resolved.refs
    result.resolved = resolved.resolved
    result.dangling = resolved.dangling

    if mark_stale:
        result.promoted_stale = _demote_stale_verified(repo, src)

    repo.add_event(
        "sync.run",
        actor="am sync",
        payload={
            "corpus": name,
            "new_tasks": result.new_tasks,
            "new_claims": result.new_claims,
            "new_files": len(result.new_files),
            "graph_rebuilt": result.graph_rebuilt,
            "resolved": result.resolved,
            "dangling": result.dangling,
            "stale": result.promoted_stale,
        },
    )
    return result
