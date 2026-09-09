"""Bind agent claims to code-graph nodes.

The whole overlay rests on one observation: knowledge.db records evidence as
``[{file, line, dirty}]`` and graphify records nodes as ``{source_file,
source_location: "L42"}``. Same coordinate space, never joined. This module is
that join.

Resolution rule: a claim's ``(file, line)`` binds to the node in that file with
the greatest ``source_line`` at or before ``line`` — the symbol the line sits
inside. When a file has nodes but none at or before the line (evidence points
above the first symbol), the file-level node is used.

An unresolved reference is kept, never dropped, and carries *why* it did not
resolve. That distinction matters: ``file_missing`` means the cited path is
gone, so the code genuinely moved and the claim needs revisiting;
``not_extracted`` means the file is still there but no extractor covers its
type (graphify parses no YAML, for instance). The first is code drift, the
second is a gap in our own tooling, and reporting them as one number makes the
tooling gap look like drift.
"""

from __future__ import annotations

import json
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .codegraph import extract_repo, location_line
from .store import Repository, utcnow


@dataclass
class BuildResult:
    repo: str
    nodes: int = 0
    edges: int = 0
    files_requested: int | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class ResolveResult:
    refs: int = 0
    resolved: int = 0
    dangling: int = 0
    claims_without_evidence: int = 0
    by_reason: dict[str, int] = field(default_factory=dict)


def normalise_nodes(raw_nodes: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """graphify node -> our row shape, with source_location parsed to an int."""
    out = []
    for node in raw_nodes:
        out.append(
            {
                "node_id": node["id"],
                "label": node.get("label"),
                "source_file": node.get("source_file"),
                "source_line": location_line(node.get("source_location")),
                "node_kind": node.get("node_kind"),
                "file_type": node.get("file_type"),
            }
        )
    return out


def normalise_edges(raw_edges: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for edge in raw_edges:
        out.append(
            {
                "source": edge["source"],
                "target": edge["target"],
                "relation": edge.get("relation"),
                "confidence": edge.get("confidence"),
                "source_file": edge.get("source_file"),
                "source_line": location_line(edge.get("source_location")),
            }
        )
    return out


def build_graph(
    repo: Repository,
    root: Path | str,
    *,
    repo_name: str | None = None,
    only_files: list[str] | None = None,
) -> BuildResult:
    """Extract a corpus and persist it under `repo_name` (default: dir name).

    `only_files` restricts extraction to specific repo-relative paths — used to
    map just the files claims actually cite instead of a whole monorepo.
    """
    root_path = Path(root).expanduser().resolve()
    name = repo_name or root_path.name
    result = BuildResult(repo=name)

    if only_files is None:
        extraction = extract_repo(root_path)
    else:
        result.files_requested = len(only_files)
        paths = []
        for rel in only_files:
            candidate = root_path / rel
            if candidate.is_file():
                paths.append(candidate)
        if not paths:
            result.notes.append("none of the requested files exist under the root")
            return result
        result.notes.append(f"{len(paths)}/{len(only_files)} requested files present")
        from .codegraph import _require_graphify

        _, extract = _require_graphify()
        extraction = extract(paths, root=root_path, parallel=False)

    nodes = normalise_nodes(extraction["nodes"])
    edges = normalise_edges(extraction["edges"])
    result.nodes, result.edges = repo.replace_graph(name, nodes, edges)
    return result


class FileIndex:
    """Line-anchored lookup for one file's nodes."""

    def __init__(self, rows: list[Any]) -> None:
        anchored = [(r["source_line"], r["node_id"]) for r in rows if r["source_line"]]
        anchored.sort()
        self._lines = [line for line, _ in anchored]
        self._ids = [node_id for _, node_id in anchored]
        # Fallback for evidence that lands above the first symbol: the node
        # with no line anchor is the file itself.
        unanchored = [r["node_id"] for r in rows if not r["source_line"]]
        self._file_node = unanchored[0] if unanchored else (self._ids[0] if self._ids else None)

    def __bool__(self) -> bool:
        return bool(self._ids or self._file_node)

    def lookup(self, line: int | None) -> str | None:
        if line is None or not self._lines:
            return self._file_node
        pos = bisect_right(self._lines, line)
        if pos == 0:
            return self._file_node
        return self._ids[pos - 1]


def resolve_claims(
    repo: Repository, repo_name: str, source_root: Path | str | None = None
) -> ResolveResult:
    """Rebuild node_refs for every claim against the stored graph.

    Only claims belonging to `repo_name` are considered, and only that
    corpus's rows are replaced. A workspace can watch several repositories, and
    a claim about one of them says nothing about the others.

    `source_root` is the working tree the evidence paths are relative to. With
    it, an unresolved ref can say whether the file is gone (`file_missing`) or
    merely unparsed (`not_extracted`); without it every miss is `unresolved`.
    """
    result = ResolveResult()
    now = utcnow()
    root = Path(source_root).expanduser().resolve() if source_root else None
    index_cache: dict[str, FileIndex] = {}
    exists_cache: dict[str, bool] = {}
    rows: list[dict[str, Any]] = []

    for claim in repo.claims_for_corpus(repo_name):
        try:
            evidence = json.loads(claim["evidence_json"] or "[]")
        except (TypeError, ValueError):
            evidence = []
        if not isinstance(evidence, list) or not evidence:
            result.claims_without_evidence += 1
            continue

        for idx, entry in enumerate(evidence):
            if not isinstance(entry, dict):
                continue
            file = str(entry.get("file") or "").strip()
            if not file:
                continue
            line = entry.get("line")
            line = int(line) if isinstance(line, (int, float)) else None

            if file not in index_cache:
                index_cache[file] = FileIndex(repo.nodes_for_file(repo_name, file))
            index = index_cache[file]
            node_id = index.lookup(line) if index else None

            if node_id:
                reason = "resolved"
            elif root is None:
                reason = "unresolved"
            else:
                if file not in exists_cache:
                    exists_cache[file] = (root / file).exists()
                reason = "not_extracted" if exists_cache[file] else "file_missing"

            rows.append(
                {
                    "claim_id": claim["id"],
                    "evidence_idx": idx,
                    "file": file,
                    "line": line,
                    "graph_node_id": node_id,
                    "resolved_at": now,
                    "dangling": 0 if node_id else 1,
                    "reason": reason,
                }
            )
            result.refs += 1
            result.by_reason[reason] = result.by_reason.get(reason, 0) + 1
            if node_id:
                result.resolved += 1
            else:
                result.dangling += 1

    repo.replace_node_refs(repo_name, rows)
    return result


def claim_evidence_files(repo: Repository, corpus: str | None = None) -> list[str]:
    """Distinct files claims cite — the extraction target for a monorepo.

    Scoped to one corpus when given, so building a graph for one watched
    repository never tries to extract paths belonging to another.
    """
    seen: dict[str, None] = {}
    claims = (
        repo.claims_for_corpus(corpus) if corpus
        else repo.list_claims(limit=1_000_000)
    )
    for claim in claims:
        try:
            evidence = json.loads(claim["evidence_json"] or "[]")
        except (TypeError, ValueError):
            continue
        if not isinstance(evidence, list):
            continue
        for entry in evidence:
            if isinstance(entry, dict) and entry.get("file"):
                seen.setdefault(str(entry["file"]).strip(), None)
    return list(seen)
