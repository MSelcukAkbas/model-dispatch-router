"""`am` — the kernel's single write/read surface.

One CLI is what lets bash (dispatch.sh), node (agent-bridge) and Python all
emit into the same event log without language bindings.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .importer import import_snapshot
from .resolver import build_graph, claim_evidence_files, resolve_claims
from .snapshot import take_snapshot
from .store import Database, Repository, resolve_db_path

app = typer.Typer(
    add_completion=False,
    help="AgentMind kernel — event log, task history and claim store.",
    no_args_is_help=True,
)
console = Console()


def _open(root: Optional[Path] = None) -> tuple[Database, Repository]:
    db = Database(resolve_db_path(root))
    db.init_db()
    return db, Repository(db)


def _fmt(value: object) -> str:
    return "" if value is None else str(value)


# --------------------------------------------------------------------- init
@app.command()
def init(
    root: Path = typer.Option(Path.cwd(), "--root", help="Project root to initialise."),
) -> None:
    """Create .agentmind/am.db and apply the schema."""
    db, repo = _open(root)
    repo.add_event("kernel.init", actor="am init", payload={"root": str(root)})
    console.print(f"[green]initialised[/green] {db.path}")
    db.close()


# -------------------------------------------------------------------- event
@app.command()
def event(
    kind: str = typer.Argument(..., help="Event kind, e.g. task.dispatched."),
    task_id: Optional[str] = typer.Option(None, "--task-id"),
    run_id: Optional[str] = typer.Option(None, "--run-id"),
    actor: Optional[str] = typer.Option(None, "--actor"),
    payload: Optional[str] = typer.Option(None, "--json", help="JSON object payload."),
    root: Path = typer.Option(Path.cwd(), "--root"),
) -> None:
    """Append one event. Never fails the caller.

    This is called from inside dispatch pipelines, so a broken kernel must not
    take a dispatch down with it: every error is reported on stderr and the
    exit code stays 0.
    """
    try:
        data = json.loads(payload) if payload else {}
        if not isinstance(data, dict):
            raise ValueError("--json must be a JSON object")
        db, repo = _open(root)
        event_id = repo.add_event(
            kind, task_id=task_id, run_id=run_id, actor=actor, payload=data
        )
        db.close()
        console.print(f"[dim]event {event_id} {kind}[/dim]")
    except Exception as exc:  # fail-open by design
        console.print(f"[yellow]am event failed (ignored):[/yellow] {exc}", style="dim")


# ----------------------------------------------------------------- snapshot
@app.command()
def snapshot(
    source: Path = typer.Argument(..., help="Live model-dispatch repo to read."),
    with_logs: bool = typer.Option(False, "--with-logs", help="Also copy *.json run logs."),
    root: Path = typer.Option(Path.cwd(), "--root"),
) -> None:
    """Copy a live repo's dispatch history here. Read-only on the source."""
    result = take_snapshot(source, Path(root) / "snapshots", with_logs=with_logs)
    console.print(f"[green]snapshot[/green] {result.dest}")
    console.print(
        f"  agent-log files: {result.agent_log_files}   knowledge.db: {result.knowledge_db}"
    )
    for note in result.notes:
        console.print(f"  [yellow]note:[/yellow] {note}")


# ------------------------------------------------------------------- import
@app.command("import")
def import_cmd(
    snapshot_dir: Path = typer.Argument(..., help="snapshots/<stamp> directory."),
    root: Path = typer.Option(Path.cwd(), "--root"),
) -> None:
    """Load a snapshot into tasks/claims/events."""
    db, repo = _open(root)
    result = import_snapshot(repo, snapshot_dir)
    console.print(
        f"[green]imported[/green] tasks={result.tasks} claims={result.claims} "
        f"events={result.events}"
    )
    for note in result.notes:
        console.print(f"  [yellow]note:[/yellow] {note}")
    for skip in result.skipped[:10]:
        console.print(f"  [red]skipped:[/red] {skip}")
    db.close()


# -------------------------------------------------------------------- tasks
@app.command()
def tasks(
    role: Optional[str] = typer.Option(None, "--role"),
    account: Optional[str] = typer.Option(None, "--account"),
    limit: int = typer.Option(30, "--limit"),
    root: Path = typer.Option(Path.cwd(), "--root"),
) -> None:
    """List imported and live dispatches."""
    db, repo = _open(root)
    rows = repo.list_tasks(role=role, account=account, limit=limit)
    table = Table(title=f"tasks ({repo.count_tasks()} total)", header_style="bold")
    for col in ("task", "role", "engine", "model", "account", "effort", "budget", "try", "diff", "when"):
        table.add_column(col, overflow="fold")
    for r in rows:
        table.add_row(
            r["task_id"],
            _fmt(r["role"]),
            _fmt(r["engine"]),
            _fmt(r["model"]),
            _fmt(r["account"]) or "ambient",
            _fmt(r["effort"]),
            _fmt(r["budget_usd"]),
            _fmt(r["attempt"]),
            _fmt(r["diffstat"]),
            (_fmt(r["started_at"])[:16] + ("" if r["started_at_exact"] else " ~")),
        )
    console.print(table)
    console.print("[dim]~ = time approximated from the .meta file's mtime[/dim]")
    db.close()


# ------------------------------------------------------------------- events
@app.command()
def events(
    kind: Optional[str] = typer.Option(None, "--kind"),
    task_id: Optional[str] = typer.Option(None, "--task-id"),
    limit: int = typer.Option(20, "--limit"),
    root: Path = typer.Option(Path.cwd(), "--root"),
) -> None:
    """Show the tail of the event log."""
    db, repo = _open(root)
    rows = repo.list_events(kind=kind, task_id=task_id, limit=limit)
    table = Table(title=f"events ({repo.count_events()} total)", header_style="bold")
    for col in ("id", "ts", "kind", "task", "actor", "payload"):
        table.add_column(col, overflow="fold")
    for r in rows:
        table.add_row(
            str(r["id"]), _fmt(r["ts"])[:19], r["kind"],
            _fmt(r["task_id"]), _fmt(r["actor"]), _fmt(r["payload_json"])[:80],
        )
    console.print(table)
    db.close()


# ------------------------------------------------------------------- claims
@app.command()
def claims(
    status: Optional[str] = typer.Option(None, "--status", help="candidate|verified|stale|superseded|promoted"),
    topic: Optional[str] = typer.Option(None, "--topic"),
    limit: int = typer.Option(20, "--limit"),
    root: Path = typer.Option(Path.cwd(), "--root"),
) -> None:
    """List agent claims carried over from knowledge.db."""
    db, repo = _open(root)
    rows = repo.list_claims(status=status, topic=topic, limit=limit)
    table = Table(title=f"claims ({repo.count_claims()} total)", header_style="bold")
    for col in ("id", "topic", "cat", "status", "task", "claim"):
        table.add_column(col, overflow="fold")
    for r in rows:
        table.add_row(
            str(r["id"]), _fmt(r["topic"]), _fmt(r["category"]),
            _fmt(r["status"]), _fmt(r["source_task"]), _fmt(r["claim"])[:70],
        )
    console.print(table)
    db.close()


# -------------------------------------------------------------------- stats
@app.command()
def stats(root: Path = typer.Option(Path.cwd(), "--root")) -> None:
    """Baseline summary — the data Phase 4's router will learn from."""
    db, repo = _open(root)
    console.print(
        f"tasks={repo.count_tasks()}  claims={repo.count_claims()}  "
        f"events={repo.count_events()}"
    )

    table = Table(title="dispatch history by role/engine/account", header_style="bold")
    for col in ("role", "engine", "account", "n", "retried", "avg budget"):
        table.add_column(col)
    for r in repo.task_stats():
        table.add_row(
            _fmt(r["role"]), _fmt(r["engine"]), _fmt(r["account"]), str(r["n"]),
            _fmt(r["retried"]), _fmt(r["avg_budget"]),
        )
    console.print(table)

    status = Table(title="claims by status", header_style="bold")
    status.add_column("status")
    status.add_column("n")
    for r in repo.claim_status_counts():
        status.add_row(_fmt(r["status"]), str(r["n"]))
    console.print(status)
    db.close()


# -------------------------------------------------------------------- graph
graph_app = typer.Typer(help="Code graph: extract a corpus and inspect it.", no_args_is_help=True)
app.add_typer(graph_app, name="graph")


@graph_app.command("build")
def graph_build(
    source: Path = typer.Argument(..., help="Repo to extract."),
    name: Optional[str] = typer.Option(None, "--name", help="Corpus name (default: dir name)."),
    from_claims: bool = typer.Option(
        False, "--from-claims",
        help="Only extract files the imported claims cite — for a monorepo where "
             "a full extraction is neither needed nor cheap.",
    ),
    root: Path = typer.Option(Path.cwd(), "--root"),
) -> None:
    """Extract a repo with graphify and store the graph. Read-only on the source."""
    db, repo = _open(root)
    only = claim_evidence_files(repo) if from_claims else None
    if from_claims and not only:
        console.print("[yellow]no claim evidence to target — import a snapshot first[/yellow]")
        db.close()
        raise typer.Exit(1)

    result = build_graph(repo, source, repo_name=name, only_files=only)
    repo.add_event(
        "graph.built", actor="am graph build",
        payload={"repo": result.repo, "nodes": result.nodes, "edges": result.edges,
                 "from_claims": from_claims},
    )
    console.print(
        f"[green]built[/green] repo={result.repo} nodes={result.nodes} edges={result.edges}"
    )
    for note in result.notes:
        console.print(f"  [yellow]note:[/yellow] {note}")
    db.close()


@graph_app.command("info")
def graph_info(root: Path = typer.Option(Path.cwd(), "--root")) -> None:
    """Which corpora are stored and how big they are."""
    db, repo = _open(root)
    table = Table(title="code graphs", header_style="bold")
    for col in ("repo", "nodes", "edges", "built"):
        table.add_column(col)
    for r in repo.graph_repos():
        _, edges = repo.count_graph(r["repo"])
        table.add_row(r["repo"], str(r["nodes"]), str(edges), _fmt(r["built_at"])[:19])
    console.print(table)
    db.close()


# ------------------------------------------------------------------ resolve
@app.command()
def resolve(
    repo_name: str = typer.Option(..., "--repo", help="Corpus name from `am graph info`."),
    src: Optional[Path] = typer.Option(
        None, "--src",
        help="Working tree the evidence paths are relative to. With it, a miss "
             "can say whether the file is gone or merely unparsed.",
    ),
    root: Path = typer.Option(Path.cwd(), "--root"),
) -> None:
    """Join claim evidence to graph nodes (rebuilds node_refs)."""
    db, repo = _open(root)
    result = resolve_claims(repo, repo_name, source_root=src)
    repo.add_event(
        "claims.resolved", actor="am resolve",
        payload={"repo": repo_name, "refs": result.refs,
                 "resolved": result.resolved, "dangling": result.dangling,
                 "by_reason": result.by_reason},
    )
    pct = (100 * result.resolved / result.refs) if result.refs else 0
    console.print(
        f"[green]resolved[/green] {result.resolved}/{result.refs} refs ({pct:.0f}%)  "
        f"claims-without-evidence={result.claims_without_evidence}"
    )
    for reason, n in sorted(result.by_reason.items(), key=lambda kv: -kv[1]):
        if reason != "resolved":
            console.print(f"  [yellow]{reason}[/yellow]: {n}")
    if src is None and result.dangling:
        console.print("[dim]pass --src <repo> to split misses into file_missing vs not_extracted[/dim]")
    db.close()


# ---------------------------------------------------------------------- why
@app.command()
def why(
    file: str = typer.Argument(..., help="Repo-relative path, e.g. app/jobs/manager.py"),
    src: Optional[Path] = typer.Option(
        None, "--src", help="Working tree to check evidence freshness against."
    ),
    root: Path = typer.Option(Path.cwd(), "--root"),
) -> None:
    """What agents have claimed about this file, and whether it still holds."""
    from .freshness import evaluate

    db, repo = _open(root)
    rows = repo.claims_for_file(file)
    if not rows:
        console.print(f"[yellow]no claims reference[/yellow] {file}")
        db.close()
        return

    fresh = evaluate(src, rows[0]["commit_sha"], [file]).label if src else ""
    console.print()
    console.print(f"[bold]{file}[/bold]  [dim]— {len(rows)} claim(s)[/dim]")
    console.print()

    status_colour = {
        "candidate": "yellow", "verified": "green", "stale": "red",
        "superseded": "dim", "promoted": "cyan",
    }
    for r in rows:
        colour = status_colour.get(r["status"], "white")
        line = f"L{r['line']}" if r["line"] else "  —"
        head = (
            f"  [cyan]{line:>6}[/cyan]  [dim]#{r['id']}[/dim]  "
            f"[{colour}]{r['status']}[/{colour}]"
        )
        if src:
            f = evaluate(src, r["commit_sha"], [file])
            tone = "green" if f.label == "fresh" else "red"
            head += f"  [{tone}]{f.label}[/{tone}]"
        head += f"  [dim]{r['source_task'] or ''}[/dim]"
        console.print(head)
        console.print(f"          [dim]{r['topic']}[/dim]")
        claim_text = " ".join(str(r["claim"]).split())
        console.print(f"          {claim_text[:160]}")
        target = (
            "[red]dangling[/red]" if r["dangling"]
            else f"[dim]-> {r['graph_node_id']}[/dim]"
        )
        console.print(f"          {target}")
        console.print()

    if src is None:
        console.print("[dim]pass --src <repo> to check whether the evidence is still fresh[/dim]")
    db.close()


# ----------------------------------------------------------------- dangling
@app.command()
def dangling(
    limit: int = typer.Option(30, "--limit"),
    reason: Optional[str] = typer.Option(
        None, "--reason", help="file_missing | not_extracted | unresolved"
    ),
    root: Path = typer.Option(Path.cwd(), "--root"),
) -> None:
    """Evidence pointing at code the graph has no node for — the code moved."""
    db, repo = _open(root)
    rows = repo.dangling_refs(limit=limit, reason=reason)
    summary = repo.resolution_summary()
    if not rows:
        console.print("[green]no dangling references[/green]")
        db.close()
        return

    breakdown = Table(title="why references did not resolve", header_style="bold")
    for col in ("reason", "refs", "files"):
        breakdown.add_column(col)
    for r in repo.reason_counts():
        if r["reason"] == "resolved":
            continue
        breakdown.add_row(_fmt(r["reason"]), str(r["n"]), str(r["files"]))
    console.print(breakdown)
    console.print(
        "[dim]file_missing = the cited path is gone (real code drift)   "
        "not_extracted = file present, no extractor for its type[/dim]"
    )
    console.print()

    console.print(
        f"[bold]{summary['dangling']}/{summary['total']}[/bold] references "
        f"could not be bound"
    )
    console.print()
    for r in repo.dangling_by_file(limit=limit, reason=reason):
        tone = "red" if r["reason"] == "file_missing" else "yellow"
        console.print(f"  [{tone}]{r['reason']}[/{tone}]  [bold]{r['file']}[/bold]")
        tasks = ", ".join(sorted(set((r["tasks"] or "").split(","))))
        console.print(
            f"      {r['claims']} claim(s), {r['refs']} ref(s)   [dim]{tasks}[/dim]"
        )
    console.print()
    console.print("[dim]am dangling --reason file_missing   shows only real code drift[/dim]")
    db.close()


# ---------------------------------------------------------------------- hot
@app.command()
def hot(
    limit: int = typer.Option(15, "--limit"),
    root: Path = typer.Option(Path.cwd(), "--root"),
) -> None:
    """Files the most claims point at — where agent attention has actually gone."""
    db, repo = _open(root)
    table = Table(title="most-cited files", header_style="bold")
    for col in ("claims", "resolved", "file"):
        table.add_column(col)
    for r in repo.hot_files(limit=limit):
        table.add_row(str(r["claims"]), _fmt(r["resolved"]), r["file"])
    console.print(table)
    db.close()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
