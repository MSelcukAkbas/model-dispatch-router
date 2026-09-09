"""Build a dispatch prompt from the graph instead of from file contents.

This is the layer the whole kernel is an argument for. A dispatched agent today
gets whole files pasted into its prompt; here it gets the subgraph around the
work plus what has already been claimed about that code, under a token budget.

Everything that decides *what survives the budget* is graphify's and is reused
rather than reimplemented: ``_query_terms`` for tokenising the ask,
``_score_nodes`` for ranking, ``_bfs`` for expansion and ``_subgraph_to_text``
for rendering (which ranks by hop distance from the seeds, so the queried
symbol is never what the cut discards). What this module adds is the overlay:
the claims attached to those nodes, each carrying its status and whether its
evidence is still fresh.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .freshness import evaluate
from .store import Repository

CHARS_PER_TOKEN = 3  # graphify's own ratio, kept identical so budgets compare

# These paths may contain machine-local instructions, credentials, or an
# irrelevant amount of operational context. They are never eligible for an
# automatically generated dispatch prompt. An explicit human-written prompt is
# still possible, but it must not be produced by graph expansion accidentally.
SENSITIVE_PATH_NAMES = {"claude.md", "secrets.md", "credentials", "credentials.json"}
SENSITIVE_PATH_PARTS = {".git", ".agentmind", ".agent-logs", ".worktrees", ".ssh"}


def is_safe_context_path(path: str | None) -> bool:
    """Return whether a repo-relative path may enter generated prompt context."""
    if not path:
        return False
    candidate = Path(path)
    parts = {part.lower() for part in candidate.parts}
    name = candidate.name.lower()
    if candidate.is_absolute() or ".." in candidate.parts:
        return False
    if name in SENSITIVE_PATH_NAMES or name.startswith(".env"):
        return False
    if parts & SENSITIVE_PATH_PARTS:
        return False
    lowered = "/".join(candidate.parts).lower()
    return not any(token in lowered for token in ("secret", "credential", "private_key", "id_rsa"))


def _without_sensitive_nodes(graph):
    """Copy the graph minus nodes whose source path cannot be auto-shared."""
    unsafe = [
        node_id for node_id, attrs in graph.nodes(data=True)
        if not is_safe_context_path(attrs.get("source_file"))
    ]
    if unsafe:
        graph = graph.copy()
        graph.remove_nodes_from(unsafe)
    return graph


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def _graphify():
    try:
        import networkx as nx
        from graphify.serve import _bfs, _query_terms, _score_nodes, _subgraph_to_text
    except ImportError as exc:  # pragma: no cover - depends on install extras
        raise RuntimeError(
            "graphify is not installed - run `uv sync --extra graph`"
        ) from exc
    return nx, _bfs, _query_terms, _score_nodes, _subgraph_to_text


@dataclass
class ContextResult:
    text: str
    tokens: int
    seeds: list[str] = field(default_factory=list)
    nodes: int = 0
    edges: int = 0
    claims: int = 0
    files: list[str] = field(default_factory=list)
    # Largest single file in a file-mode baseline, and its share of the total.
    # A saving ratio is only as meaningful as the thing it is measured against:
    # one enormous document in the match set produces a spectacular number that
    # says more about that document than about this tool.
    biggest_file: str = ""
    biggest_share: int = 0


def load_graph(repo: Repository, repo_name: str):
    """Rebuild the nx.Graph from our tables, in graphify's own node shape.

    source_line is stored as an int but rendered back to "L<n>": the renderer
    reads source_location, and a shape mismatch here would silently produce
    context with no line anchors at all.
    """
    nx, *_ = _graphify()
    graph = nx.Graph()
    for row in repo.all_nodes(repo_name):
        graph.add_node(
            row["node_id"],
            label=row["label"],
            source_file=row["source_file"],
            source_location=f"L{row['source_line']}" if row["source_line"] else "",
            node_kind=row["node_kind"],
        )
    for row in repo.all_edges(repo_name):
        if graph.has_node(row["source"]) and graph.has_node(row["target"]):
            graph.add_edge(
                row["source"],
                row["target"],
                relation=row["relation"],
                confidence=row["confidence"],
            )
    return graph


def pick_seeds(graph, query: str, limit: int = 5) -> list[str]:
    _, _, query_terms, score_nodes, _ = _graphify()
    terms = query_terms(query)
    if not terms:
        return []
    scored = score_nodes(graph, terms)
    return [node_id for _, node_id in scored[:limit]]


# Which claims earn a place when the budget cannot hold them all. A claim that
# passed a gate outranks one that never did; a superseded claim is last because
# something newer already replaced it.
STATUS_RANK = {
    "verified": 0,
    "promoted": 1,
    "candidate": 2,
    "stale": 3,
    "superseded": 4,
}


def _collect_claims(repo: Repository, nodes, src) -> list[dict]:
    collected: dict[int, dict] = {}
    for node_id in sorted(nodes):
        for claim in repo.claims_for_node(node_id):
            if claim["id"] in collected:
                continue
            entry = dict(claim)
            if src is not None:
                entry["freshness"] = evaluate(
                    src, claim["commit_sha"], [claim["file"]]
                ).label
            collected[claim["id"]] = entry
    ordered = sorted(
        collected.values(),
        key=lambda c: (
            STATUS_RANK.get(c["status"], 9),
            c.get("freshness") not in (None, "fresh"),
            c["file"] or "",
            c["line"] or 0,
        ),
    )
    return ordered


def _render_claim(claim: dict) -> list[str]:
    fresh = f" freshness={claim['freshness']}" if claim.get("freshness") else ""
    line_no = claim["line"] or "?"
    return [
        f"- [{claim['status']}{fresh}] {claim['topic']} "
        f"({claim['file']}:{line_no}, task {claim['source_task']})",
        "  " + " ".join(str(claim["claim"]).split()),
    ]


def _claim_lines(
    repo: Repository, nodes, src, budget: int | None = None
) -> tuple[list[str], int, int]:
    """Render claims highest-value first, stopping at the budget.

    Returns (lines, shown, total). The budget applies here too: an unbounded
    claims section silently dwarfed the graph body it was appended to, which
    made `--budget` a promise the output did not keep.
    """
    claims = _collect_claims(repo, nodes, src)
    if budget is None:
        lines: list[str] = []
        for claim in claims:
            lines += _render_claim(claim)
        return lines, len(claims), len(claims)

    char_budget = budget * CHARS_PER_TOKEN
    lines = []
    used = 0
    shown = 0
    for claim in claims:
        rendered = _render_claim(claim)
        cost = sum(len(line) + 1 for line in rendered)
        if used + cost > char_budget and shown > 0:
            break
        lines += rendered
        used += cost
        shown += 1
    return lines, shown, len(claims)


def build_context(
    repo: Repository,
    repo_name: str,
    query: str,
    *,
    depth: int = 2,
    budget: int = 2000,
    src: Path | str | None = None,
    with_claims: bool = True,
) -> ContextResult:
    """`budget` bounds the graph body and the claims section separately, so the
    worst case is roughly twice it rather than unbounded."""
    _, bfs, _, _, subgraph_to_text = _graphify()
    graph = _without_sensitive_nodes(load_graph(repo, repo_name))
    seeds = pick_seeds(graph, query)
    if not seeds:
        return ContextResult(text="", tokens=0)

    nodes, edges = bfs(graph, seeds, depth)
    body = subgraph_to_text(graph, nodes, edges, token_budget=budget, seeds=seeds)

    files = sorted(
        {
            graph.nodes[n].get("source_file")
            for n in nodes
            if graph.nodes[n].get("source_file")
        }
    )

    sections = [f"## Code graph around: {query}", "", body]
    claim_count = 0

    if with_claims:
        lines, shown, total = _claim_lines(repo, nodes, src, budget=budget)
        claim_count = shown
        if lines:
            heading = "## What agents have already claimed about this code"
            if shown < total:
                heading += f" (top {shown} of {total})"
            sections += [
                "",
                heading,
                "",
                "Status is the claim's own lifecycle state; freshness is computed",
                "from git, not from what the agent reported. A `candidate` claim",
                "has passed no verification gate - treat it as a lead, not a fact.",
                "",
                *lines,
            ]

    text = "\n".join(sections)
    return ContextResult(
        text=text,
        tokens=estimate_tokens(text),
        seeds=seeds,
        nodes=len(nodes),
        edges=len(edges),
        claims=claim_count,
        files=[f for f in files if f],
    )


def build_file_context(
    repo: Repository,
    repo_name: str,
    query: str,
    src: Path | str,
    *,
    depth: int = 2,
) -> ContextResult:
    """The baseline: whole contents of the files the graph context would cite.

    This is what a dispatch prompt carries today. Measuring against the *same*
    target files is the only honest comparison - same subject, different amount
    of text about it.
    """
    graph_result = build_context(
        repo, repo_name, query, depth=depth, budget=10**9, with_claims=False
    )
    root = Path(src).expanduser().resolve()
    chunks = [f"## Files relevant to: {query}", ""]
    sizes: dict[str, int] = {}
    for rel in graph_result.files:
        path = root / rel
        if not path.is_file():
            continue
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        sizes[rel] = len(body)
        chunks += [f"### {rel}", "```", body, "```", ""]
    text = "\n".join(chunks)

    biggest_file, biggest_share = "", 0
    if sizes:
        biggest_file = max(sizes, key=sizes.__getitem__)
        biggest_share = 100 * sizes[biggest_file] // max(sum(sizes.values()), 1)

    return ContextResult(
        text=text,
        tokens=estimate_tokens(text),
        seeds=graph_result.seeds,
        files=graph_result.files,
        biggest_file=biggest_file,
        biggest_share=biggest_share,
    )
