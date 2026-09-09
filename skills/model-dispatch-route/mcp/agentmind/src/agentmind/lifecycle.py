"""Automatic AgentMind lifecycle around a model-dispatch-route run.

The shell dispatcher owns process execution.  This module owns the two small
integration points around it: refresh and prepare memory before launch, then
ingest the task result after the agent exits.  Callers may treat failures as
fail-open; no function in here promotes a claim without the verification gate.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .context import build_context
from .store import Database, Repository, resolve_db_path
from .sync import sync as run_sync
from .workspace import locate_store, register


def _open_runtime(
    source: Path | str | None = None,
    root: Path | str | None = None,
    *,
    create: bool = False,
) -> tuple[Path, Database, Repository]:
    src = Path(source or Path.cwd()).expanduser().resolve()
    if root is not None:
        workspace = Path(root).expanduser().resolve()
    else:
        workspace, _ = locate_store(src)
        if workspace is None:
            if not create:
                raise RuntimeError("no AgentMind store found for this repository")
            workspace = src
    db = Database(resolve_db_path(workspace))
    db.init_db()
    repo = Repository(db)
    if create and repo.corpus_for_source(src) is None:
        base = src.name or "repository"
        name = base
        existing = repo.corpus(name)
        if existing is not None:
            digest = hashlib.sha256(str(src).encode("utf-8")).hexdigest()[:8]
            name = f"{base}-{digest}"
        repo.remember_corpus(name, src)
        register(workspace)
    return workspace, db, repo


def _corpus(repo: Repository, name: str | None, source: Path | str) -> str:
    row = repo.corpus(name) if name else repo.corpus_for_source(source)
    if row is None:
        known = [entry["name"] for entry in repo.corpora()]
        if name:
            raise RuntimeError(f"unknown AgentMind corpus: {name}")
        if not known:
            raise RuntimeError("AgentMind has no corpus; run am setup first")
        raise RuntimeError("no AgentMind corpus matches this repository")
    return str(row["name"])


def session_start(
    task_id: str,
    role: str,
    query: str,
    source: Path | str,
    *,
    root: Path | str | None = None,
    repo_name: str | None = None,
    budget: int = 2000,
) -> dict[str, Any]:
    """Refresh memory and build context before a dispatched conversation."""
    src = Path(source).expanduser().resolve()
    workspace, db, repo = _open_runtime(src, root, create=True)
    sync_result: dict[str, Any] | None = None
    sync_error: str | None = None
    context_error: str | None = None
    try:
        corpus = _corpus(repo, repo_name, src)
        try:
            synced = run_sync(repo, src, workspace, corpus=corpus)
            sync_result = asdict(synced)
        except Exception as exc:  # memory refresh must not prevent dispatch
            sync_error = str(exc)

        try:
            context = build_context(
                repo, corpus, query, budget=budget, src=src
            )
            text = context.text
            details = {
                "tokens": context.tokens,
                "nodes": context.nodes,
                "edges": context.edges,
                "claims": context.claims,
                "files": context.files,
            }
        except Exception as exc:  # existing memory may still be unavailable
            context_error = str(exc)
            text = ""
            details = {"tokens": 0, "nodes": 0, "edges": 0,
                       "claims": 0, "files": []}

        repo.add_event(
            "dispatch.context_prepared",
            task_id=task_id,
            actor="model-dispatch-route",
            payload={
                "role": role,
                "corpus": corpus,
                "query": query,
                **details,
                "sync_error": sync_error,
                "context_error": context_error,
            },
        )
        return {
            "ok": context_error is None,
            "task_id": task_id,
            "corpus": corpus,
            "context": text,
            "sync": sync_result,
            "sync_error": sync_error,
            "context_error": context_error,
            **details,
        }
    finally:
        db.close()


def session_finish(
    task_id: str,
    role: str,
    source: Path | str,
    *,
    exit_code: int,
    status: str | None = None,
    root: Path | str | None = None,
    repo_name: str | None = None,
) -> dict[str, Any]:
    """Ingest bridge findings and record completion after an agent exits."""
    src = Path(source).expanduser().resolve()
    workspace, db, repo = _open_runtime(src, root, create=True)
    try:
        corpus = _corpus(repo, repo_name, src)
        sync_error: str | None = None
        sync_result: dict[str, Any] | None = None
        try:
            synced = run_sync(repo, src, workspace, corpus=corpus)
            sync_result = asdict(synced)
        except Exception as exc:  # record the end event even if import failed
            sync_error = str(exc)

        final_status = status or ("done" if exit_code == 0 else "failed")
        repo.add_event(
            "dispatch.finished",
            task_id=task_id,
            actor="model-dispatch-route",
            payload={
                "role": role,
                "corpus": corpus,
                "status": final_status,
                "exit_code": exit_code,
                "sync_error": sync_error,
            },
        )
        return {
            "ok": sync_error is None,
            "task_id": task_id,
            "corpus": corpus,
            "status": final_status,
            "exit_code": exit_code,
            "sync": sync_result,
            "sync_error": sync_error,
        }
    finally:
        db.close()


def memory_status(
    source: Path | str | None = None,
    *,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Return a compact machine-readable AgentMind status."""
    _, db, repo = _open_runtime(source, root)
    try:
        resolution = repo.resolution_summary()
        nodes, edges = repo.count_graph()
        return {
            "tasks": repo.count_tasks(),
            "events": repo.count_events(),
            "claims": repo.count_claims(),
            "claim_statuses": {
                row["status"]: row["n"] for row in repo.claim_status_counts()
            },
            "graph": {"nodes": nodes, "edges": edges},
            "resolution": dict(resolution),
            "corpora": [dict(row) for row in repo.corpora()],
        }
    finally:
        db.close()
