"""`am` — the kernel's single write/read surface.

One CLI is what lets bash (dispatch.sh), node (agent-bridge) and Python all
emit into the same event log without language bindings.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from .context import build_context, build_file_context, estimate_tokens
from .gate import evaluate_task, graph_delta
from .importer import import_snapshot
from .lifecycle import session_finish, session_start
from .hooks import install_hooks
from .resolver import build_graph, claim_evidence_files, resolve_claims
from .router import POLICY, memory_gaps, recommend
from .snapshot import take_snapshot
from .sync import sync as run_sync
from .workspace import locate_store, register, registered_workspaces
from .store import (
    DEFAULT_DB_RELPATH,
    Database,
    Repository,
    find_store,
    nearby_stores,
    resolve_db_path,
)

app = typer.Typer(
    add_completion=False,
    help="AgentMind kernel — event log, task history and claim store.",
    no_args_is_help=True,
)


@app.command("hooks-install")
def hooks_install(
    source: Path = typer.Argument(Path.cwd(), help="Repository to configure."),
    platform: str = typer.Option("all", "--platform", help="all, codex, or claude"),
) -> None:
    """Install non-destructive AgentMind lifecycle hooks in a repository."""
    for path in install_hooks(source, platform.lower()):
        console.print(f"[green]configured[/green] {path}")
# Windows consoles default to a legacy code page - cp1254 on a Turkish install -
# and agent-written claim text routinely carries characters it cannot encode
# (arrows, em-dashes, box drawing). That raised UnicodeEncodeError partway
# through rendering, killing the command over one character in one claim.
# Force UTF-8 where the stream allows it and replace what still will not fit.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):  # not a real tty, or already fixed
        pass

console = Console()


def _open(
    root: Optional[Path] = None, *, create: bool = False
) -> tuple[Database, Repository]:
    """Open the workspace store.

    Only `init` and `setup` pass create=True. Every other command refuses to
    conjure an empty database: silently creating one and then reporting zero
    tasks and zero claims reads as data loss, when the real cause is standing
    in the wrong directory.
    """
    if root is None:
        located, _how = locate_store()
        if located is not None:
            root = located
        elif not create:
            _no_store()
    elif not create and not (Path(root) / DEFAULT_DB_RELPATH).is_file():
        # An explicit --root used to mean "create here if missing", which let a
        # read command materialise a store inside whatever directory it was
        # pointed at - including a repo this tool is only ever meant to read.
        console.print(f"[red]no AgentMind store at[/red] {escape(str(root))}")
        console.print("  run [bold]am setup <repo> --root <path>[/bold] to create one.")
        raise typer.Exit(2)
    db = Database(resolve_db_path(root))
    db.init_db()
    return db, Repository(db)


def _no_store() -> None:
    console.print(
        "[red]no AgentMind store found[/red] here, above here, or in the "
        "workspace registry."
    )
    nearby = nearby_stores()
    if nearby:
        console.print("  there is one just below you:")
        for path in nearby:
            console.print(f"    [bold]cd {path.name}[/bold]   "
                          f"[dim]or: --root {path}[/dim]")
    else:
        console.print("  run [bold]am setup <repo>[/bold] to create one, "
                      "or pass --root <path> to point at an existing workspace.")
    raise typer.Exit(2)


def _target(
    repo: Repository, name: Optional[str], src: Optional[Path]
) -> tuple[str, Path]:
    """Work out which corpus and which source directory a command means.

    The path was already given once, at setup. Making every later command ask
    for it again is friction this tool put there itself, so a remembered
    corpus fills in both.
    """
    row = repo.corpus(name) if name else repo.only_corpus()
    if row is None:
        known = [r["name"] for r in repo.corpora()]
        if name:
            console.print(f"[red]unknown corpus[/red] {name!r}")
        elif known:
            console.print("[red]several corpora here[/red] - name one with --repo:")
            for entry in known:
                console.print(f"    {entry}")
        else:
            console.print("[red]no corpus yet[/red] - run `am setup <repo>` first.")
        raise typer.Exit(2)
    return row["name"], Path(src) if src else Path(row["source_path"])


def _fmt(value: object) -> str:
    """Stringify a stored value for display.

    Everything reaching this came out of the claim store, where the text was
    written by an agent: it routinely contains square brackets (array indices,
    `[candidate]`, log excerpts) which rich parses as markup and then dies on.
    Escaping here means no caller has to remember to.
    """
    return "" if value is None else escape(str(value))


# --------------------------------------------------------------------- init
@app.command()
def init(
    root: Path = typer.Option(None, "--root", help="Where to create .agentmind (default: cwd)."),
) -> None:
    """Create .agentmind/am.db and apply the schema."""
    target = Path(root) if root else Path.cwd()
    db, repo = _open(target, create=True)
    repo.add_event("kernel.init", actor="am init", payload={"root": str(target)})
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
    root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd)."),
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


# --------------------------------------------------------- dispatch lifecycle
@app.command("session-start")
def session_start_cmd(
    task_id: str = typer.Argument(...),
    role: str = typer.Option(..., "--role"),
    source: Path = typer.Option(..., "--src"),
    query: str = typer.Option(..., "--query"),
    out: Path = typer.Option(..., "--out"),
    repo_name: Optional[str] = typer.Option(None, "--repo"),
    budget: int = typer.Option(2000, "--budget"),
    root: Path = typer.Option(None, "--root"),
) -> None:
    """Prepare dispatch context. Fail-open so memory never blocks execution."""
    try:
        result = session_start(
            task_id,
            role,
            query,
            source,
            root=root,
            repo_name=repo_name,
            budget=budget,
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(result["context"], encoding="utf-8")
        console.print(
            f"[dim]AgentMind context: {result['tokens']} tokens, "
            f"{result['claims']} claims[/dim]"
        )
        if result["sync_error"]:
            console.print(
                f"[yellow]AgentMind sync warning:[/yellow] {result['sync_error']}",
                style="dim",
            )
        if result["context_error"]:
            console.print(
                f"[yellow]AgentMind context warning:[/yellow] "
                f"{result['context_error']}",
                style="dim",
            )
    except Exception as exc:
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("", encoding="utf-8")
        except OSError:
            pass
        console.print(
            f"[yellow]AgentMind session-start failed (ignored):[/yellow] {exc}",
            style="dim",
        )


@app.command("session-end")
def session_end_cmd(
    task_id: str = typer.Argument(...),
    role: str = typer.Option(..., "--role"),
    source: Path = typer.Option(..., "--src"),
    exit_code: int = typer.Option(..., "--exit-code"),
    status_name: Optional[str] = typer.Option(None, "--status"),
    repo_name: Optional[str] = typer.Option(None, "--repo"),
    root: Path = typer.Option(None, "--root"),
) -> None:
    """Ingest a dispatch result. Fail-open so bookkeeping never masks exit."""
    try:
        result = session_finish(
            task_id,
            role,
            source,
            exit_code=exit_code,
            status=status_name,
            root=root,
            repo_name=repo_name,
        )
        console.print(
            f"[dim]AgentMind session recorded: {result['status']}[/dim]"
        )
        if result["sync_error"]:
            console.print(
                f"[yellow]AgentMind sync warning:[/yellow] {result['sync_error']}",
                style="dim",
            )
    except Exception as exc:
        console.print(
            f"[yellow]AgentMind session-end failed (ignored):[/yellow] {exc}",
            style="dim",
        )


# ----------------------------------------------------------------- snapshot
@app.command()
def snapshot(
    source: Path = typer.Argument(..., help="Live model-dispatch repo to read."),
    with_logs: bool = typer.Option(False, "--with-logs", help="Also copy *.json run logs."),
    root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd)."),
) -> None:
    """Copy a live repo's dispatch history here. Read-only on the source."""
    db, repo = _open(root)
    base = db.path.parent.parent
    db.close()
    result = take_snapshot(source, base / "snapshots", with_logs=with_logs)
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
    root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd)."),
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
    root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd)."),
) -> None:
    """List imported and live dispatches."""
    db, repo = _open(root)
    rows = repo.list_tasks(role=role, account=account, limit=limit)
    table = Table(title=f"tasks ({repo.count_tasks()} total)", header_style="bold")
    for col in ("task", "role", "engine", "model", "account", "effort", "budget", "try", "diff", "when"):
        table.add_column(col, overflow="fold")
    for r in rows:
        table.add_row(
            _fmt(r["task_id"]),
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
    root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd)."),
) -> None:
    """Show the tail of the event log."""
    db, repo = _open(root)
    rows = repo.list_events(kind=kind, task_id=task_id, limit=limit)
    table = Table(title=f"events ({repo.count_events()} total)", header_style="bold")
    for col in ("id", "ts", "kind", "task", "actor", "payload"):
        table.add_column(col, overflow="fold")
    for r in rows:
        table.add_row(
            str(r["id"]), _fmt(r["ts"])[:19], _fmt(r["kind"]),
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
    root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd)."),
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
def stats(root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd).")) -> None:
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
    root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd)."),
) -> None:
    """Extract a repo with graphify and store the graph. Read-only on the source."""
    db, repo = _open(root)
    only = claim_evidence_files(repo) if from_claims else None
    if from_claims and not only:
        console.print("[yellow]no claim evidence to target — import a snapshot first[/yellow]")
        db.close()
        raise typer.Exit(1)

    result = build_graph(repo, source, repo_name=name, only_files=only)
    repo.remember_corpus(result.repo, source)
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
def graph_info(root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd).")) -> None:
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
    repo_name: Optional[str] = typer.Option(None, "--repo", help="Corpus name."),
    src: Optional[Path] = typer.Option(
        None, "--src",
        help="Working tree the evidence paths are relative to. With it, a miss "
             "can say whether the file is gone or merely unparsed.",
    ),
    root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd)."),
) -> None:
    """Join claim evidence to graph nodes (rebuilds node_refs)."""
    db, repo = _open(root)
    repo_name, src = _target(repo, repo_name, src)
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
        None, "--src", help="Working tree for freshness (default: remembered)."
    ),
    repo_name: Optional[str] = typer.Option(None, "--repo", help="Corpus name."),
    root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd)."),
) -> None:
    """What agents have claimed about this file, and whether it still holds."""
    from .freshness import evaluate

    db, repo = _open(root)
    if src is None and repo.corpora():
        _, src = _target(repo, repo_name, None)
    rows = repo.claims_for_file(file)
    if not rows:
        console.print(f"[yellow]no claims reference[/yellow] {escape(file)}")
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
        head += f"  [dim]{_fmt(r['source_task'])}[/dim]"
        console.print(head)
        console.print(f"          [dim]{_fmt(r['topic'])}[/dim]")
        claim_text = " ".join(str(r["claim"]).split())
        console.print("          " + escape(claim_text[:160]))
        target = (
            "[red]dangling[/red]" if r["dangling"]
            else f"[dim]-> {_fmt(r['graph_node_id'])}[/dim]"
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
    root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd)."),
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
        console.print(f"  [{tone}]{_fmt(r['reason'])}[/{tone}]  [bold]{_fmt(r['file'])}[/bold]")
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
    root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd)."),
) -> None:
    """Files the most claims point at — where agent attention has actually gone."""
    db, repo = _open(root)
    table = Table(title="most-cited files", header_style="bold")
    # 'refs bound' counts citations, not claims - one claim often cites the
    # same file at several lines, so it can exceed the claim count and the
    # old 'resolved' header made that read as a contradiction.
    for col in ("claims", "refs bound", "file"):
        table.add_column(col)
    for r in repo.hot_files(limit=limit):
        table.add_row(str(r["claims"]), _fmt(r["resolved"]), _fmt(r["file"]))
    console.print(table)
    db.close()


# ------------------------------------------------------------------ context
@app.command()
def context(
    query: str = typer.Argument(..., help="What the task is about."),
    repo_name: Optional[str] = typer.Option(None, "--repo", help="Corpus name."),
    depth: int = typer.Option(2, "--depth", help="Hops to expand from the seeds."),
    budget: int = typer.Option(2000, "--budget", help="Approx token budget."),
    src: Optional[Path] = typer.Option(None, "--src", help="Tree for freshness checks."),
    root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd)."),
) -> None:
    """Print the graph context for a task - what a prompt would carry."""
    db, repo = _open(root)
    repo_name, src = _target(repo, repo_name, src)
    result = build_context(repo, repo_name, query, depth=depth, budget=budget, src=src)
    if not result.text:
        console.print(f"[yellow]nothing in the graph matched[/yellow] {query!r}")
        db.close()
        raise typer.Exit(1)
    print(result.text)
    console.print()
    console.print(
        f"[dim]~{result.tokens} tokens - {result.nodes} nodes, {result.edges} edges, "
        f"{result.claims} claims, {len(result.files)} files[/dim]"
    )
    db.close()


# ------------------------------------------------------------------- prompt
@app.command()
def prompt(
    query: str = typer.Argument(..., help="What the task is about."),
    goal: str = typer.Option(..., "--goal", help="The one sentence for the # GOAL: header."),
    repo_name: Optional[str] = typer.Option(None, "--repo", help="Corpus name."),
    mode: str = typer.Option("graph", "--mode", help="graph | files"),
    src: Optional[Path] = typer.Option(None, "--src", help="Working tree (default: remembered)."),
    depth: int = typer.Option(2, "--depth"),
    budget: int = typer.Option(2000, "--budget"),
    out: Optional[Path] = typer.Option(None, "--out", help="Write to a file instead of stdout."),
    root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd)."),
) -> None:
    """Emit a dispatch.sh-ready prompt file.

    The two headers are dispatch.sh's contract, not decoration: it refuses a
    prompt with no `# GOAL:` (dispatch.sh:256) and uses `# FILES:` to reject a
    task overlapping a still-running one (dispatch.sh:262).
    """
    if mode not in ("graph", "files"):
        console.print("[red]--mode must be graph or files[/red]")
        raise typer.Exit(1)
    db, repo = _open(root)
    repo_name, src = _target(repo, repo_name, src)
    if mode == "graph":
        result = build_context(repo, repo_name, query, depth=depth, budget=budget, src=src)
    else:
        result = build_file_context(repo, repo_name, query, src, depth=depth)

    if not result.text:
        console.print(f"[yellow]nothing in the graph matched[/yellow] {query!r}")
        db.close()
        raise typer.Exit(1)

    header = [f"# GOAL: {goal}"]
    if result.files:
        header.append("# FILES: " + ",".join(result.files))
    body = ("\n".join(header) + "\n\n" + result.text + "\n")

    if out:
        Path(out).write_text(body, encoding="utf-8")
        repo.add_event(
            "prompt.built", actor="am prompt",
            payload={"repo": repo_name, "mode": mode, "query": query,
                     "tokens": estimate_tokens(body), "files": len(result.files)},
        )
        console.print(
            f"[green]wrote[/green] {out}  [dim]~{estimate_tokens(body)} tokens, "
            f"{len(result.files)} files[/dim]"
        )
    else:
        print(body)
    db.close()


# -------------------------------------------------------------------- bench
@app.command()
def bench(
    queries: list[str] = typer.Argument(..., help="One or more task descriptions."),
    repo_name: Optional[str] = typer.Option(None, "--repo", help="Corpus name."),
    src: Optional[Path] = typer.Option(None, "--src", help="Working tree (default: remembered)."),
    depth: int = typer.Option(2, "--depth"),
    budget: int = typer.Option(2000, "--budget"),
    root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd)."),
) -> None:
    """Measure graph context against the file-dump baseline, per task.

    This is the number the whole design is a bet on. Both modes are pointed at
    the same target files, so what is being compared is amount-of-text, not
    scope.
    """
    db, repo = _open(root)
    repo_name, src = _target(repo, repo_name, src)
    table = Table(title="prompt cost: files vs graph", header_style="bold")
    for col in ("task", "files", "files ~tok", "graph ~tok", "saved", "claims",
                "largest file drives"):
        table.add_column(col, overflow="fold")

    total_files = total_graph = 0
    skewed: list[tuple[str, str, int]] = []
    for query in queries:
        baseline = build_file_context(repo, repo_name, query, src, depth=depth)
        graph_ctx = build_context(
            repo, repo_name, query, depth=depth, budget=budget, src=None
        )
        if not graph_ctx.text:
            table.add_row(query[:28], "-", "-", "[yellow]no match[/yellow]", "-", "-")
            continue
        total_files += baseline.tokens
        total_graph += graph_ctx.tokens
        saved = 100 - (100 * graph_ctx.tokens // max(baseline.tokens, 1))
        tone = "green" if saved > 0 else "red"
        # Surfaced because a single huge file in the match set inflates the
        # ratio on its own; without this the reader cannot tell a real result
        # from one document's size.
        driver = ""
        if baseline.biggest_file:
            skew = "yellow" if baseline.biggest_share >= 50 else "dim"
            name = Path(baseline.biggest_file).name
            driver = f"[{skew}]{baseline.biggest_share}% {escape(name)}[/{skew}]"
            if baseline.biggest_share >= 50:
                skewed.append((query, baseline.biggest_file, baseline.biggest_share))
        table.add_row(
            query[:28], str(len(baseline.files)), f"{baseline.tokens:,}",
            f"{graph_ctx.tokens:,}", f"[{tone}]{saved}%[/{tone}]", str(graph_ctx.claims),
            driver,
        )

    console.print(table)
    if total_files:
        overall = 100 - (100 * total_graph // total_files)
        ratio = total_files / max(total_graph, 1)
        console.print(
            f"[bold]overall[/bold] {total_files:,} -> {total_graph:,} tokens  "
            f"([green]{overall}% less[/green], {ratio:.1f}x)"
        )
        repo.add_event(
            "bench.run", actor="am bench",
            payload={"repo": repo_name, "queries": len(queries),
                     "files_tokens": total_files, "graph_tokens": total_graph,
                     "saved_pct": overall},
        )
    if skewed:
        console.print()
        console.print(
            "[yellow]read these with care[/yellow] - in the runs below, one file is "
            "most of the baseline, so the ratio measures that file's size as much "
            "as this tool:"
        )
        for query, path, share in skewed:
            console.print(f"    {escape(query[:28])}: {share}% is {escape(path)}")
    console.print(
        "[dim]token counts use graphify's ~3-chars-per-token estimate, "
        "identical for both modes[/dim]"
    )
    db.close()


# --------------------------------------------------------------------- gate
@app.command()
def gate(
    task_id: str = typer.Argument(..., help="Task whose claims to verify."),
    src: Optional[Path] = typer.Option(
        None, "--src", help="Working tree the evidence lives in (default: remembered)."
    ),
    repo_name: Optional[str] = typer.Option(None, "--repo", help="Corpus name."),
    check: Optional[str] = typer.Option(
        None, "--check", help="Project command that must exit zero, e.g. 'pytest -q'."
    ),
    promote: bool = typer.Option(
        False, "--promote", help="On a full pass, move this task's candidates to verified."
    ),
    root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd)."),
) -> None:
    """Verify a task's claims. The only path from candidate to verified."""
    db, repo = _open(root)
    _, src = _target(repo, repo_name, src)
    result = evaluate_task(repo, task_id, src, command=check, promote=promote)

    table = Table(title=f"gate: {task_id}", header_style="bold")
    table.add_column("check")
    table.add_column("")
    table.add_column("detail", overflow="fold")
    for c in result.checks:
        mark = "[green]pass[/green]" if c.ok else "[red]FAIL[/red]"
        table.add_row(c.name, mark, escape(c.detail))
    console.print(table)

    if result.passed:
        console.print(f"[green]gate passed[/green] - {result.claims} claim(s)")
        if promote:
            console.print(f"  promoted {result.promoted} candidate(s) to verified")
        else:
            console.print("  [dim]add --promote to record that on the claims[/dim]")
    else:
        console.print(
            f"[red]gate failed[/red] - {result.claims} claim(s) stay candidate"
        )
        raise typer.Exit(1)
    db.close()


@app.command("gate-targets")
def gate_targets(
    limit: int = typer.Option(20, "--limit"),
    root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd)."),
) -> None:
    """Tasks holding unverified claims - the queue the gate exists to drain."""
    db, repo = _open(root)
    table = Table(title="tasks with claims", header_style="bold")
    for col in ("task", "claims", "candidate", "verified"):
        table.add_column(col, overflow="fold")
    for r in repo.tasks_with_claims(limit=limit):
        table.add_row(
            _fmt(r["task_id"]), str(r["claims"]),
            _fmt(r["candidates"]), _fmt(r["verified"]),
        )
    console.print(table)
    db.close()


@app.command("graph-diff")
def graph_diff_cmd(
    repo_name: Optional[str] = typer.Option(None, "--repo"),
    src: Optional[Path] = typer.Option(None, "--src"),
    root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd)."),
) -> None:
    """Structural change between the stored graph and the tree as it is now.

    This is what catches a report claiming one small edit when the structure
    moved far more than that.
    """
    db, repo = _open(root)
    repo_name, src = _target(repo, repo_name, src)
    diff = graph_delta(repo, repo_name, src)
    table = Table(title=f"graph delta: {repo_name}", header_style="bold")
    table.add_column("metric")
    table.add_column("value", overflow="fold")
    for key, value in diff.items():
        if isinstance(value, list):
            value = f"{len(value)}: " + ", ".join(str(v) for v in value[:5])
        table.add_row(str(key), str(value))
    console.print(table)
    db.close()


# -------------------------------------------------------------------- setup
@app.command()
def setup(
    source: Path = typer.Argument(..., help="Live model-dispatch repo to learn from."),
    name: Optional[str] = typer.Option(None, "--name", help="Corpus name."),
    root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd)."),
) -> None:
    """One command: snapshot, import, build the graph, resolve. Read-only on the source."""
    from .resolver import build_graph, claim_evidence_files, resolve_claims

    located, _how = locate_store()
    target = Path(root) if root else (located or Path.cwd())
    db, repo = _open(target, create=True)
    corpus = name or Path(source).expanduser().resolve().name

    console.print("[bold]1/4[/bold] snapshotting (read-only)")
    snap = take_snapshot(source, Path(target) / "snapshots")
    console.print(f"      {snap.agent_log_files} log files, knowledge.db={snap.knowledge_db}")

    console.print("[bold]2/4[/bold] importing dispatch history and claims")
    imported = import_snapshot(repo, snap.dest)
    console.print(f"      {imported.tasks} tasks, {imported.claims} claims")

    console.print("[bold]3/4[/bold] extracting the code the claims cite")
    built = build_graph(
        repo, source, repo_name=corpus, only_files=claim_evidence_files(repo)
    )
    console.print(f"      {built.nodes} nodes, {built.edges} edges")

    console.print("[bold]4/4[/bold] joining claims to the graph")
    resolved = resolve_claims(repo, corpus, source_root=source)
    pct = (100 * resolved.resolved / resolved.refs) if resolved.refs else 0
    console.print(f"      {resolved.resolved}/{resolved.refs} refs bound ({pct:.0f}%)")

    repo.remember_corpus(corpus, source)
    repo.touch_corpus(corpus)
    register(target)

    console.print()
    console.print(f"[green]ready[/green]  corpus=[bold]{corpus}[/bold]")
    console.print("  am sync                       catch up after more work happens")
    console.print("  am hot                        where agent attention has gone")
    console.print("  am why <file>                 what is already known there")
    console.print("  am dangling --reason file_missing")
    console.print(f"  am bench \"<task>\" --repo {corpus} --src {source}")
    db.close()


# ------------------------------------------------------------------- status
@app.command()
def status(root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd).")) -> None:
    """Everything at a glance: history, memory, graph, and what is unverified."""
    db, repo = _open(root)

    tasks_n = repo.count_tasks()
    claims_n = repo.count_claims()
    events_n = repo.count_events()
    nodes_n, edges_n = repo.count_graph()
    statuses = {r["status"]: r["n"] for r in repo.claim_status_counts()}
    verified = statuses.get("verified", 0)
    candidates = statuses.get("candidate", 0)
    summary = repo.resolution_summary()

    console.print()
    console.print("[bold]AgentMind[/bold]  [dim]" + str(db.path) + "[/dim]")
    console.print()

    left = Table.grid(padding=(0, 2))
    left.add_column(style="dim")
    left.add_column()
    left.add_row("dispatch history", f"{tasks_n} tasks")
    left.add_row("event log", f"{events_n} events")
    left.add_row("code graph", f"{nodes_n} nodes, {edges_n} edges")
    bound = summary["resolved"] or 0
    total = summary["total"] or 0
    pct = f"{100 * bound // total}%" if total else "-"
    left.add_row("claims joined", f"{bound}/{total} refs ({pct})")
    console.print(left)
    console.print()

    bar = Table(title="claim memory", header_style="bold")
    for col in ("status", "n", "meaning"):
        bar.add_column(col, overflow="fold")
    meanings = {
        "verified": "passed the gate on this machine",
        "candidate": "an agent said so; nothing has checked it",
        "stale": "evidence moved since it was recorded",
        "superseded": "replaced by a later claim",
        "promoted": "manually accepted by the orchestrator",
    }
    for name, n in sorted(statuses.items(), key=lambda kv: -kv[1]):
        tone = "green" if name == "verified" else "yellow" if name == "candidate" else "dim"
        bar.add_row(f"[{tone}]{name}[/{tone}]", str(n), meanings.get(name, ""))
    console.print(bar)

    if candidates:
        share = 100 * candidates // max(claims_n, 1)
        console.print(
            f"[yellow]{candidates} of {claims_n} claims ({share}%) have never been "
            f"verified[/yellow] - `am gate-targets` lists them by task"
        )
    if verified:
        console.print(f"[green]{verified} verified[/green] by a gate run")

    repos = repo.graph_repos()
    if repos:
        console.print()
        console.print("[dim]corpora: " + ", ".join(r["repo"] for r in repos) + "[/dim]")
    else:
        console.print()
        console.print("[dim]no code graph yet - run `am setup <repo>`[/dim]")
    db.close()


# --------------------------------------------------------------------- sync
@app.command()
def sync(
    source: Optional[Path] = typer.Argument(
        None, help="Live repo to catch up with. Omit to use the remembered one."
    ),
    name: Optional[str] = typer.Option(None, "--name", help="Corpus name."),
    keep_stale: bool = typer.Option(
        False, "--keep-stale",
        help="Leave verified claims verified even if their evidence has moved.",
    ),
    root: Path = typer.Option(None, "--root"),
) -> None:
    """Catch up with a repo: new dispatches, new claims, moved code.

    Run this whenever you want the store current. It reads the repo and writes
    nothing to it, so the loop closes without a hook or a wrapper on that side.
    """
    db, repo = _open(root)
    base = db.path.parent.parent
    corpus_name, source_path = (
        (name or Path(source).expanduser().resolve().name, Path(source))
        if source else _target(repo, name, None)
    )
    result = run_sync(
        repo, source_path, base, corpus=corpus_name, mark_stale=not keep_stale
    )
    repo.remember_corpus(result.corpus, source_path)
    repo.touch_corpus(result.corpus)

    if not result.changed:
        console.print(f"[dim]already current[/dim]  corpus={result.corpus}")
    else:
        console.print(f"[green]synced[/green]  corpus={result.corpus}")
        if result.new_tasks:
            console.print(f"  +{result.new_tasks} dispatch(es)")
        if result.new_claims:
            console.print(f"  +{result.new_claims} claim(s)")
        if result.new_files:
            shown = ", ".join(_fmt(f) for f in result.new_files[:3])
            more = f" (+{len(result.new_files) - 3} more)" if len(result.new_files) > 3 else ""
            console.print(f"  +{len(result.new_files)} newly cited file(s): {shown}{more}")
        if result.promoted_stale:
            console.print(
                f"  [yellow]{result.promoted_stale} verified claim(s) went stale[/yellow]"
                " - their evidence moved since the gate ran"
            )

    pct = (100 * result.resolved / result.refs) if result.refs else 0
    console.print(
        f"  [dim]{result.nodes} nodes, {result.edges} edges, "
        f"{result.resolved}/{result.refs} refs bound ({pct:.0f}%)[/dim]"
    )
    for note in result.notes:
        console.print(f"  [yellow]note:[/yellow] {_fmt(note)}")
    db.close()


# -------------------------------------------------------------------- route
@app.command()
def route(
    role: Optional[str] = typer.Argument(None, help="Role to advise on. Omit for all."),
    root: Path = typer.Option(None, "--root"),
) -> None:
    """Where to send a task, and how much history stands behind that advice.

    The recommendation is the documented policy made explicit. The evidence
    column is what the recorded dispatches actually say about it. When they
    disagree, that disagreement is the point.
    """
    db, repo = _open(root)
    roles = [role] if role else sorted(POLICY)
    unknown = [r for r in roles if r not in POLICY]
    if unknown:
        console.print(f"[red]unknown role[/red] {unknown[0]!r}")
        console.print("  known: " + ", ".join(sorted(POLICY)))
        db.close()
        raise typer.Exit(2)

    table = Table(title="routing advice", header_style="bold")
    for col in ("role", "engine", "model", "effort", "budget", "runs", "evidence"):
        table.add_column(col, overflow="fold")

    warnings: list[tuple[str, str]] = []
    for name in roles:
        rec = recommend(repo, name)
        ev = rec.evidence
        tone = {"moderate": "green", "weak": "yellow"}.get(ev.confidence, "dim")
        table.add_row(
            name, rec.engine, rec.model, rec.effort, f"${rec.budget:.2f}",
            str(ev.dispatches), f"[{tone}]{ev.confidence}[/{tone}]",
        )
        for text in rec.warnings:
            warnings.append((name, text))
        if rec.note:
            warnings.append((name, f"[dim]{escape(rec.note)}[/dim]"))
    console.print(table)

    for name, text in warnings:
        console.print(f"  [bold]{name}[/bold]: {text}")

    console.print()
    console.print(
        "[dim]evidence is how many recorded dispatches back the rule, not a "
        "measured outcome - nothing here tracks whether a task succeeded[/dim]"
    )
    db.close()


# ----------------------------------------------------------------- coverage
@app.command()
def coverage(root: Path = typer.Option(None, "--root")) -> None:
    """What the recorded history can and cannot answer.

    Worth reading before trusting any analysis built on this table: the two
    dispatch engines write different .meta shapes, so several columns exist
    for only one of them.
    """
    db, repo = _open(root)

    table = Table(title="dispatch record coverage", header_style="bold")
    for col in ("field", "recorded", "of", "note"):
        table.add_column(col, overflow="fold")
    notes = {
        "effort": "dispatch.sh only; agy writes no effort",
        "budget_usd": "dispatch.sh only; agy has no --max-budget-usd",
        "attempt": "dispatch.sh only",
        "session_id": "dispatch.sh only",
        "diffstat": "sidecar file, absent here",
        "finished_at": "nothing records completion yet",
    }
    for field_name, n, total in repo.field_coverage():
        share = 100 * n // max(total, 1)
        tone = "green" if share > 80 else "yellow" if share > 30 else "red"
        table.add_row(
            field_name, f"[{tone}]{n}[/{tone}]", str(total), notes.get(field_name, "")
        )
    console.print(table)

    gaps = memory_gaps(repo)
    if gaps:
        console.print()
        console.print("[yellow]dispatches that remember nothing[/yellow]")
        for gap in gaps:
            console.print(
                f"    {gap['role']} on {gap['engine']}: "
                f"{gap['dispatches']} runs, 0 claims"
            )
        console.print(
            "  [dim]those runs happened and found things; none of it reached the\n"
            "  knowledge store, so the next task starts from nothing[/dim]"
        )
    db.close()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
