"""AgentMind MCP server.

The model-dispatch shell scripts call the same lifecycle functions directly
through the ``am`` CLI for deterministic start/end hooks.  These MCP tools make
the same memory available to the orchestrator and dispatched agents on demand.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

from ..context import build_context
from ..freshness import evaluate
from ..lifecycle import (
    _corpus,
    _open_runtime,
    memory_status,
    session_finish,
    session_start,
)

mcp = MCPServer("agentmind")


def _source(source_path: str | None) -> Path:
    """Resolve the watched repo without making the model guess its path."""
    value = source_path or os.environ.get("DISPATCH_REPO_ROOT") or Path.cwd()
    return Path(value).expanduser().resolve()


@mcp.tool()
def memory_status_tool(source_path: str | None = None) -> dict[str, Any]:
    """Show AgentMind task, claim, graph, and verification counts."""
    return memory_status(_source(source_path))


@mcp.tool()
def memory_context(
    query: str,
    source_path: str | None = None,
    repo_name: str | None = None,
    budget: int = 2000,
) -> dict[str, Any]:
    """Return code-graph context and prior claims relevant to a task."""
    src = _source(source_path)
    _, db, repo = _open_runtime(src)
    try:
        corpus = _corpus(repo, repo_name)
        result = build_context(repo, corpus, query, budget=budget, src=src)
        return {
            "context": result.text,
            "tokens": result.tokens,
            "nodes": result.nodes,
            "edges": result.edges,
            "claims": result.claims,
            "files": result.files,
        }
    finally:
        db.close()


@mcp.tool()
def memory_for_file(file: str, source_path: str | None = None) -> dict[str, Any]:
    """Return claims attached to one repository-relative file."""
    src = _source(source_path)
    _, db, repo = _open_runtime(src)
    try:
        claims = []
        for row in repo.claims_for_file(file):
            item = dict(row)
            item["freshness"] = evaluate(src, row["commit_sha"], [file]).label
            claims.append(item)
        return {"file": file, "claims": claims}
    finally:
        db.close()


@mcp.tool()
def dispatch_session_start(
    task_id: str,
    role: str,
    query: str,
    source_path: str | None = None,
    repo_name: str | None = None,
    budget: int = 2000,
) -> dict[str, Any]:
    """Refresh memory and prepare context at dispatch conversation start."""
    return session_start(
        task_id, role, query, _source(source_path),
        repo_name=repo_name, budget=budget
    )


@mcp.tool()
def dispatch_session_finish(
    task_id: str,
    role: str,
    exit_code: int,
    source_path: str | None = None,
    status: str | None = None,
    repo_name: str | None = None,
) -> dict[str, Any]:
    """Ingest findings and record the end of a dispatched conversation."""
    return session_finish(
        task_id,
        role,
        _source(source_path),
        exit_code=exit_code,
        status=status,
        repo_name=repo_name,
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
