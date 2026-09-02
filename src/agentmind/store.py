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


def resolve_db_path(root: Path | str | None = None) -> Path:
    """Where am.db lives for a given project root (default: cwd)."""
    return Path(root or Path.cwd()) / DEFAULT_DB_RELPATH


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

    # ------------------------------------------------------------- bulk load
    def bulk(self, statement: str, rows: Iterable[Sequence[Any]]) -> int:
        cur = self._db.conn.executemany(statement, rows)
        self._db.conn.commit()
        return cur.rowcount
