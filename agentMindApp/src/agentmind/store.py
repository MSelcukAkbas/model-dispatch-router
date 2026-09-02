"""SQLite store for the AgentMind kernel.

Mirrors the split agentic-ssh-mcp uses in app/db/: `Database` owns the
connection, the PRAGMAs and executing schema.sql; `Repository` owns every
query. Sync (sqlite3) rather than async (aiosqlite) because the CLI has no
event loop — async would buy nothing here and cost a wrapper on every call.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

DEFAULT_DB_RELPATH = Path(".agentmind") / "am.db"

# SQLite applies a column DEFAULT only when the column is omitted from the
# INSERT — passing an explicit NULL bypasses it and trips the NOT NULL
# constraint. The upserts below always name every column (so a re-import
# overwrites cleanly), so the defaults have to be applied here instead.
TASK_DEFAULTS: dict[str, Any] = {
    "started_at_exact": 0,
    "source": "import",
}
CLAIM_DEFAULTS: dict[str, Any] = {
    "evidence_json": "[]",
    "scope": "task",
    "status": "candidate",
    "verification_count": 0,
    "supporting_tasks_json": "[]",
    "origin": "import",
}


def _with_defaults(row: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    merged = dict(row)
    for key, value in defaults.items():
        if merged.get(key) is None:
            merged[key] = value
    return merged


def utcnow() -> str:
    """ISO-8601 UTC, second precision — the timestamp format every table uses."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def find_store(start: Path | str | None = None) -> Path | None:
    """Nearest existing am.db, searching upward like git looks for .git.

    Without this, running `am` one directory away from the store silently
    opened a brand-new empty database and reported zero of everything, which
    reads as data loss rather than as a wrong working directory.
    """
    current = Path(start or Path.cwd()).expanduser().resolve()
    for candidate in [current, *current.parents]:
        db = candidate / DEFAULT_DB_RELPATH
        if db.is_file():
            return db
    return None


def nearby_stores(start: Path | str | None = None, limit: int = 5) -> list[Path]:
    """Stores in immediate subdirectories, for the "wrong side of it" case.

    find_store only walks up, so standing one level *above* a workspace finds
    nothing - which is the easiest mistake to make and the least obvious to
    diagnose. One shallow look down turns a dead end into a suggestion.
    """
    base = Path(start or Path.cwd()).expanduser().resolve()
    found: list[Path] = []
    try:
        children = sorted(p for p in base.iterdir() if p.is_dir())
    except OSError:
        return found
    for child in children:
        if child.name.startswith("."):
            continue
        if (child / DEFAULT_DB_RELPATH).is_file():
            found.append(child)
            if len(found) >= limit:
                break
    return found


def resolve_db_path(root: Path | str | None = None) -> Path:
    """Where am.db lives.

    An explicit `root` always wins - scripts and tests must be able to name a
    location. Otherwise use the nearest store above the working directory, and
    fall back to creating one here when there is none.
    """
    if root is not None:
        return Path(root) / DEFAULT_DB_RELPATH
    found = find_store()
    return found if found is not None else Path.cwd() / DEFAULT_DB_RELPATH


class Database:
    def __init__(self, db_path: Path | str) -> None:
        self._path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    def init_db(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
        self._conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database not initialised — call init_db() first")
        return self._conn

    @property
    def path(self) -> Path:
        return self._path

    def __enter__(self) -> "Database":
        self.init_db()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class Repository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ---------------------------------------------------------------- events
    def add_event(
        self,
        kind: str,
        *,
        task_id: str | None = None,
        run_id: str | None = None,
        actor: str | None = None,
        payload: dict[str, Any] | None = None,
        ts: str | None = None,
    ) -> int:
        cur = self._db.conn.execute(
            "INSERT INTO events (ts, kind, task_id, run_id, actor, payload_json)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                ts or utcnow(),
                kind,
                task_id,
                run_id,
                actor,
                json.dumps(payload or {}, ensure_ascii=False),
            ),
        )
        self._db.conn.commit()
        return int(cur.lastrowid)

    def list_events(
        self,
        *,
        kind: str | None = None,
        task_id: str | None = None,
        limit: int = 50,
    ) -> list[sqlite3.Row]:
        sql = "SELECT * FROM events"
        where: list[str] = []
        params: list[Any] = []
        if kind:
            where.append("kind = ?")
            params.append(kind)
        if task_id:
            where.append("task_id = ?")
            params.append(task_id)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return list(self._db.conn.execute(sql, params))

    def count_events(self) -> int:
        return int(self._db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    # ----------------------------------------------------------------- tasks
    def upsert_task(self, task: dict[str, Any]) -> None:
        cols = (
            "task_id", "role", "model", "engine", "account", "effort", "budget_usd",
            "attempt", "diffstat", "session_id", "no_worktree", "config_dir",
            "status", "started_at", "started_at_exact", "finished_at", "source",
        )
        row = _with_defaults(task, TASK_DEFAULTS)
        values = [row.get(c) for c in cols]
        placeholders = ", ".join("?" for _ in cols)
        # Every non-key column is overwritten on conflict: a re-import of a
        # newer snapshot should win, not silently keep the older row.
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "task_id")
        self._db.conn.execute(
            f"INSERT INTO tasks ({', '.join(cols)}) VALUES ({placeholders})"
            f" ON CONFLICT(task_id) DO UPDATE SET {updates}",
            values,
        )
        self._db.conn.commit()

    def list_tasks(
        self,
        *,
        role: str | None = None,
        account: str | None = None,
        limit: int = 100,
    ) -> list[sqlite3.Row]:
        sql = "SELECT * FROM tasks"
        where: list[str] = []
        params: list[Any] = []
        if role:
            where.append("role = ?")
            params.append(role)
        # `is not None`, not a truthiness test: "" is the ambient account — a
        # real value to filter on, not the absence of a filter.
        if account is not None:
            where.append("IFNULL(account, '') = ?")
            params.append(account)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY started_at DESC, task_id DESC LIMIT ?"
        params.append(limit)
        return list(self._db.conn.execute(sql, params))

    def count_tasks(self) -> int:
        return int(self._db.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0])

    def task_stats(self) -> list[sqlite3.Row]:
        return list(
            self._db.conn.execute(
                # Grouped by engine as well as account: an agy .meta carries no
                # account field, so without the engine column its rows read as
                # "ambient Claude" and silently inflate the Claude-side numbers.
                "SELECT role, IFNULL(engine, '?') AS engine,"
                "       CASE WHEN IFNULL(engine,'') = 'agy' THEN 'n/a'"
                "            WHEN IFNULL(account,'') = '' THEN 'ambient'"
                "            ELSE account END AS account,"
                "       COUNT(*) AS n,"
                "       SUM(attempt > 1) AS retried,"
                "       ROUND(AVG(budget_usd), 2) AS avg_budget"
                " FROM tasks GROUP BY role, engine, account"
                " ORDER BY n DESC"
            )
        )

    # ---------------------------------------------------------------- claims
    def upsert_claim(self, claim: dict[str, Any]) -> None:
        cols = (
            "id", "topic", "category", "claim", "evidence_json", "scope",
            "commit_sha", "source_task", "source_role", "status",
            "verification_count", "supporting_tasks_json", "superseded_by",
            "created_at", "last_verified_commit", "last_verified_at", "origin",
        )
        row = _with_defaults(claim, CLAIM_DEFAULTS)
        values = [row.get(c) for c in cols]
        placeholders = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "id")
        self._db.conn.execute(
            f"INSERT INTO claims ({', '.join(cols)}) VALUES ({placeholders})"
            f" ON CONFLICT(id) DO UPDATE SET {updates}",
            values,
        )
        self._db.conn.commit()

    def list_claims(
        self,
        *,
        status: str | None = None,
        topic: str | None = None,
        limit: int = 50,
    ) -> list[sqlite3.Row]:
        sql = "SELECT * FROM claims"
        where: list[str] = []
        params: list[Any] = []
        if status:
            where.append("status = ?")
            params.append(status)
        if topic:
            where.append("topic LIKE ?")
            params.append(f"%{topic}%")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return list(self._db.conn.execute(sql, params))

    def count_claims(self) -> int:
        return int(self._db.conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0])

    def claim_status_counts(self) -> list[sqlite3.Row]:
        return list(
            self._db.conn.execute(
                "SELECT status, COUNT(*) AS n FROM claims"
                " GROUP BY status ORDER BY n DESC"
            )
        )

    # ----------------------------------------------------------- code graph
    def replace_graph(
        self, repo_name: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
    ) -> tuple[int, int]:
        """Swap in a freshly extracted graph for one corpus.

        Delete-then-insert scoped to `repo_name`: a rebuild must not leave
        nodes behind for code that was removed, or the resolver would keep
        binding claims to symbols that no longer exist.
        """
        conn = self._db.conn
        conn.execute("DELETE FROM graph_nodes WHERE repo = ?", (repo_name,))
        conn.execute("DELETE FROM graph_edges WHERE repo = ?", (repo_name,))
        built = utcnow()
        conn.executemany(
            "INSERT INTO graph_nodes"
            " (node_id, repo, label, source_file, source_line, node_kind, file_type, built_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (n["node_id"], repo_name, n.get("label"), n.get("source_file"),
                 n.get("source_line"), n.get("node_kind"), n.get("file_type"), built)
                for n in nodes
            ],
        )
        conn.executemany(
            "INSERT OR IGNORE INTO graph_edges"
            " (repo, source, target, relation, confidence, source_file, source_line)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (repo_name, e["source"], e["target"], e.get("relation"),
                 e.get("confidence"), e.get("source_file"), e.get("source_line"))
                for e in edges
            ],
        )
        conn.commit()
        return len(nodes), len(edges)

    def nodes_for_file(self, repo_name: str, source_file: str) -> list[sqlite3.Row]:
        return list(
            self._db.conn.execute(
                "SELECT * FROM graph_nodes WHERE repo = ? AND source_file = ?"
                " ORDER BY source_line",
                (repo_name, source_file),
            )
        )

    def count_graph(self, repo_name: str | None = None) -> tuple[int, int]:
        if repo_name is None:
            n = self._db.conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0]
            e = self._db.conn.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]
        else:
            n = self._db.conn.execute(
                "SELECT COUNT(*) FROM graph_nodes WHERE repo = ?", (repo_name,)
            ).fetchone()[0]
            e = self._db.conn.execute(
                "SELECT COUNT(*) FROM graph_edges WHERE repo = ?", (repo_name,)
            ).fetchone()[0]
        return int(n), int(e)

    def graph_repos(self) -> list[sqlite3.Row]:
        return list(
            self._db.conn.execute(
                "SELECT repo, COUNT(*) AS nodes, MAX(built_at) AS built_at"
                " FROM graph_nodes GROUP BY repo ORDER BY nodes DESC"
            )
        )

    def all_nodes(self, repo_name: str) -> list[sqlite3.Row]:
        return list(
            self._db.conn.execute(
                "SELECT node_id, label, source_file, source_line, node_kind"
                " FROM graph_nodes WHERE repo = ?",
                (repo_name,),
            )
        )

    def all_edges(self, repo_name: str) -> list[sqlite3.Row]:
        return list(
            self._db.conn.execute(
                "SELECT source, target, relation, confidence FROM graph_edges"
                " WHERE repo = ?",
                (repo_name,),
            )
        )

    # ------------------------------------------------------------- node_refs
    def replace_node_refs(self, rows: list[dict[str, Any]]) -> int:
        conn = self._db.conn
        conn.execute("DELETE FROM node_refs")
        conn.executemany(
            "INSERT INTO node_refs"
            " (claim_id, evidence_idx, file, line, graph_node_id, resolved_at,"
            "  dangling, reason)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (r["claim_id"], r["evidence_idx"], r["file"], r.get("line"),
                 r.get("graph_node_id"), r.get("resolved_at"),
                 int(r.get("dangling", 0)), r.get("reason", "resolved"))
                for r in rows
            ],
        )
        conn.commit()
        return len(rows)

    def resolution_summary(self) -> sqlite3.Row:
        return self._db.conn.execute(
            "SELECT COUNT(*) AS total,"
            "       SUM(dangling = 0) AS resolved,"
            "       SUM(dangling = 1) AS dangling,"
            "       COUNT(DISTINCT claim_id) AS claims"
            " FROM node_refs"
        ).fetchone()

    def claims_for_file(self, source_file: str) -> list[sqlite3.Row]:
        """Every claim whose evidence points at this file — the `am why` query."""
        return list(
            self._db.conn.execute(
                "SELECT DISTINCT c.id, c.topic, c.category, c.claim, c.status,"
                "       c.source_task, c.source_role, c.commit_sha, c.created_at,"
                "       r.line, r.graph_node_id, r.dangling"
                " FROM claims c JOIN node_refs r ON r.claim_id = c.id"
                " WHERE r.file = ?"
                " ORDER BY r.line, c.id",
                (source_file,),
            )
        )

    def claims_for_node(self, node_id: str) -> list[sqlite3.Row]:
        return list(
            self._db.conn.execute(
                "SELECT DISTINCT c.id, c.topic, c.claim, c.status, c.source_task,"
                "       c.commit_sha, r.file, r.line"
                " FROM claims c JOIN node_refs r ON r.claim_id = c.id"
                " WHERE r.graph_node_id = ? ORDER BY c.id",
                (node_id,),
            )
        )

    def dangling_refs(
        self, limit: int = 50, reason: str | None = None
    ) -> list[sqlite3.Row]:
        sql = (
            "SELECT r.file, r.line, r.reason, c.id AS claim_id, c.topic, c.status,"
            "       c.source_task"
            " FROM node_refs r JOIN claims c ON c.id = r.claim_id"
            " WHERE r.dangling = 1"
        )
        params: list[Any] = []
        if reason:
            sql += " AND r.reason = ?"
            params.append(reason)
        sql += " ORDER BY r.file, r.line LIMIT ?"
        params.append(limit)
        return list(self._db.conn.execute(sql, params))

    def dangling_by_file(
        self, limit: int = 50, reason: str | None = None
    ) -> list[sqlite3.Row]:
        """One row per unresolved file — the readable view.

        A single missing file usually accounts for many refs (one per cited
        line), so the flat ref list buries the signal under repetition.
        """
        sql = (
            "SELECT r.file, r.reason, COUNT(*) AS refs,"
            "       COUNT(DISTINCT r.claim_id) AS claims,"
            "       GROUP_CONCAT(DISTINCT c.source_task) AS tasks"
            " FROM node_refs r JOIN claims c ON c.id = r.claim_id"
            " WHERE r.dangling = 1"
        )
        params: list[Any] = []
        if reason:
            sql += " AND r.reason = ?"
            params.append(reason)
        sql += " GROUP BY r.file, r.reason ORDER BY claims DESC, refs DESC LIMIT ?"
        params.append(limit)
        return list(self._db.conn.execute(sql, params))

    def claims_for_task(self, task_id: str) -> list[sqlite3.Row]:
        return list(
            self._db.conn.execute(
                "SELECT * FROM claims WHERE source_task = ? ORDER BY id",
                (task_id,),
            )
        )

    def refs_for_task(self, task_id: str) -> list[sqlite3.Row]:
        return list(
            self._db.conn.execute(
                "SELECT r.* FROM node_refs r JOIN claims c ON c.id = r.claim_id"
                " WHERE c.source_task = ?",
                (task_id,),
            )
        )

    def promote_claim(self, claim_id: int, commit_sha: str | None = None) -> None:
        """candidate -> verified. Only the gate calls this.

        verification_count is incremented rather than set, so a claim confirmed
        by several independent gate runs is distinguishable from one that
        squeaked through once.
        """
        self._db.conn.execute(
            "UPDATE claims SET status = 'verified',"
            "       verification_count = verification_count + 1,"
            "       last_verified_commit = ?, last_verified_at = ?"
            " WHERE id = ? AND status = 'candidate'",
            (commit_sha, utcnow(), claim_id),
        )
        self._db.conn.commit()

    def drop_graph(self, repo_name: str) -> None:
        self._db.conn.execute("DELETE FROM graph_nodes WHERE repo = ?", (repo_name,))
        self._db.conn.execute("DELETE FROM graph_edges WHERE repo = ?", (repo_name,))
        self._db.conn.commit()

    def tasks_with_claims(self, limit: int = 50) -> list[sqlite3.Row]:
        return list(
            self._db.conn.execute(
                "SELECT source_task AS task_id, COUNT(*) AS claims,"
                "       SUM(status = 'candidate') AS candidates,"
                "       SUM(status = 'verified') AS verified"
                " FROM claims WHERE source_task IS NOT NULL"
                " GROUP BY source_task ORDER BY claims DESC LIMIT ?",
                (limit,),
            )
        )

    def reason_counts(self) -> list[sqlite3.Row]:
        return list(
            self._db.conn.execute(
                "SELECT reason, COUNT(*) AS n, COUNT(DISTINCT file) AS files"
                " FROM node_refs GROUP BY reason ORDER BY n DESC"
            )
        )

    def hot_files(self, limit: int = 15) -> list[sqlite3.Row]:
        """Files the most claims point at — where agent attention has gone."""
        return list(
            self._db.conn.execute(
                "SELECT file, COUNT(DISTINCT claim_id) AS claims,"
                "       SUM(dangling = 0) AS resolved"
                " FROM node_refs GROUP BY file ORDER BY claims DESC LIMIT ?",
                (limit,),
            )
        )

    # ------------------------------------------------------------- bulk load
    def bulk(self, statement: str, rows: Iterable[Sequence[Any]]) -> int:
        cur = self._db.conn.executemany(statement, rows)
        self._db.conn.commit()
        return cur.rowcount
