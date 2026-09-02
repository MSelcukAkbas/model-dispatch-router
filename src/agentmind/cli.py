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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
