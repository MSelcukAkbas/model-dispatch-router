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

from .context import build_context, build_file_context, estimate_tokens
from .gate import evaluate_task, graph_delta
from .importer import import_snapshot
from .resolver import build_graph, claim_evidence_files, resolve_claims
from .snapshot import take_snapshot
from .store import Database, Repository, find_store, nearby_stores, resolve_db_path

app = typer.Typer(
    add_completion=False,
    help="AgentMind kernel — event log, task history and claim store.",
    no_args_is_help=True,
)
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
    if root is None and not create and find_store() is None:
        console.print(
            "[red]no AgentMind store found[/red] here or in any parent directory."
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
    db = Database(resolve_db_path(root))
    db.init_db()
    return db, Repository(db)


def _fmt(value: object) -> str:
    return "" if value is None else str(value)


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


# ----------------------------------------------------------------- snapshot
@app.command()
def snapshot(
    source: Path = typer.Argument(..., help="Live model-dispatch repo to read."),
    with_logs: bool = typer.Option(False, "--with-logs", help="Also copy *.json run logs."),
    root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd)."),
) -> None:
    """Copy a live repo's dispatch history here. Read-only on the source."""
    base = Path(root) if root else (find_store().parent.parent if find_store() else Path.cwd())
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
    repo_name: str = typer.Option(..., "--repo", help="Corpus name from `am graph info`."),
    src: Optional[Path] = typer.Option(
        None, "--src",
        help="Working tree the evidence paths are relative to. With it, a miss "
             "can say whether the file is gone or merely unparsed.",
    ),
    root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd)."),
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
    root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd)."),
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
    root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd)."),
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


# ------------------------------------------------------------------ context
@app.command()
def context(
    query: str = typer.Argument(..., help="What the task is about."),
    repo_name: str = typer.Option(..., "--repo", help="Corpus name."),
    depth: int = typer.Option(2, "--depth", help="Hops to expand from the seeds."),
    budget: int = typer.Option(2000, "--budget", help="Approx token budget."),
    src: Optional[Path] = typer.Option(None, "--src", help="Tree for freshness checks."),
    root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd)."),
) -> None:
    """Print the graph context for a task - what a prompt would carry."""
    db, repo = _open(root)
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
    repo_name: str = typer.Option(..., "--repo", help="Corpus name."),
    mode: str = typer.Option("graph", "--mode", help="graph | files"),
    src: Optional[Path] = typer.Option(None, "--src", help="Working tree (required for files mode)."),
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
    if mode == "files" and src is None:
        console.print("[red]files mode needs --src[/red]")
        raise typer.Exit(1)

    db, repo = _open(root)
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
    repo_name: str = typer.Option(..., "--repo", help="Corpus name."),
    src: Path = typer.Option(..., "--src", help="Working tree the files live in."),
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
    table = Table(title="prompt cost: files vs graph", header_style="bold")
    for col in ("task", "files", "files ~tok", "graph ~tok", "saved", "claims"):
        table.add_column(col, overflow="fold")

    total_files = total_graph = 0
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
        table.add_row(
            query[:28], str(len(baseline.files)), f"{baseline.tokens:,}",
            f"{graph_ctx.tokens:,}", f"[{tone}]{saved}%[/{tone}]", str(graph_ctx.claims),
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
    console.print(
        "[dim]token counts use graphify's ~3-chars-per-token estimate, "
        "identical for both modes[/dim]"
    )
    db.close()


# --------------------------------------------------------------------- gate
@app.command()
def gate(
    task_id: str = typer.Argument(..., help="Task whose claims to verify."),
    src: Path = typer.Option(..., "--src", help="Working tree the evidence lives in."),
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
    result = evaluate_task(repo, task_id, src, command=check, promote=promote)

    table = Table(title=f"gate: {task_id}", header_style="bold")
    table.add_column("check")
    table.add_column("")
    table.add_column("detail", overflow="fold")
    for c in result.checks:
        mark = "[green]pass[/green]" if c.ok else "[red]FAIL[/red]"
        table.add_row(c.name, mark, c.detail)
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
    repo_name: str = typer.Option(..., "--repo"),
    src: Path = typer.Option(..., "--src"),
    root: Path = typer.Option(None, "--root", help="Workspace root (default: nearest .agentmind above cwd)."),
) -> None:
    """Structural change between the stored graph and the tree as it is now.

    This is what catches a report claiming one small edit when the structure
    moved far more than that.
    """
    db, repo = _open(root)
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

    target = Path(root) if root else (find_store().parent.parent if find_store() else Path.cwd())
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

    console.print()
    console.print(f"[green]ready[/green]  corpus=[bold]{corpus}[/bold]")
    console.print("  am hot                        where agent attention has gone")
    console.print(f"  am why <file> --src {source}")
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
