"""Load a snapshot into the kernel store.

Two sources, both already produced by the existing system:

* ``.agent-logs/<task>.meta`` — the key=value block dispatch.sh writes at
  dispatch.sh:309-317 (role, timeout_min, effort, session_id, no_worktree,
  account, config_dir) and appends to at dispatch.sh:445-448
  (max_budget_usd, attempt). The ``.attempt``/``.diffstat`` sidecars carry the
  same counters dispatch.sh persists separately.
* ``knowledge.db`` — the `knowledge` table written by knowledge-store.js. Its
  status lifecycle is copied verbatim; `embedding` is skipped in Phase 0.

Two dispatch engines write two different .meta shapes. dispatch.sh omits the
model (it maps role to model in its ROLE_MODEL array and never persists the
result), so it is derived here. dispatch-agy.sh writes `model=` and `engine=agy`
explicitly — those are read, never overwritten by the derivation.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .store import Repository

# dispatch.sh:160-168 ROLE_MODEL. Kept here so an imported row records which
# model actually ran, which .meta alone does not say.
ROLE_MODEL = {
    "backend": "sonnet",
    "design": "sonnet",
    "sdk": "sonnet",
    "general": "sonnet",
    "ops": "sonnet",
    "research": "haiku",
    "judge": "opus",
}


@dataclass
class ImportResult:
    tasks: int = 0
    claims: int = 0
    events: int = 0
    skipped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def parse_meta(text: str) -> dict[str, str]:
    """Parse dispatch.sh's key=value meta block.

    Values may legitimately contain '=' (config_dir is a Windows path), so the
    split is on the first '=' only. Blank lines and anything without '=' are
    ignored rather than raising — a partially written .meta from a crashed
    dispatch should still import what it has.
    """
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def _to_int(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _to_float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _read_sidecar(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def import_agent_logs(repo: Repository, agent_logs: Path, result: ImportResult) -> None:
    if not agent_logs.is_dir():
        result.notes.append(f"no agent-logs directory in snapshot: {agent_logs}")
        return

    for meta_path in sorted(agent_logs.glob("*.meta")):
        task_id = meta_path.name[: -len(".meta")]
        try:
            meta = parse_meta(meta_path.read_text(encoding="utf-8"))
        except OSError as exc:
            result.skipped.append(f"{task_id}: {exc}")
            continue

        role = meta.get("role") or None
        # dispatch.sh does not stamp a dispatch time; the .meta file's mtime is
        # the closest real signal we have. Flagged as inexact so nothing later
        # treats it as a precise measurement.
        mtime = datetime.fromtimestamp(meta_path.stat().st_mtime, tz=timezone.utc)

        repo.upsert_task(
            {
                "task_id": task_id,
                "role": role,
                # dispatch-agy.sh writes the real model into .meta
                # (e.g. gemini-3.1-pro-high) and has no ROLE_MODEL mapping;
                # dispatch.sh writes no model at all and must be derived.
                # Trust an explicit value over the derivation, never the reverse.
                "model": meta.get("model") or ROLE_MODEL.get(role or "", None),
                "engine": meta.get("engine") or "claude",
                "account": meta.get("account", ""),
                "effort": meta.get("effort"),
                "budget_usd": _to_float(meta.get("max_budget_usd")),
                "attempt": _to_int(
                    meta.get("attempt") or _read_sidecar(agent_logs / f"{task_id}.attempt")
                ),
                "diffstat": _to_int(_read_sidecar(agent_logs / f"{task_id}.diffstat")),
                "session_id": meta.get("session_id"),
                "no_worktree": _to_int(meta.get("no_worktree")),
                "config_dir": meta.get("config_dir"),
                "status": "imported",
                "started_at": mtime.isoformat(timespec="seconds"),
                "started_at_exact": 0,
                "finished_at": None,
                "source": "import",
            }
        )
        result.tasks += 1
        repo.add_event(
            "task.imported",
            task_id=task_id,
            actor="am import",
            payload={"role": role, "account": meta.get("account", ""),
                     "effort": meta.get("effort"), "attempt": meta.get("attempt")},
            ts=mtime.isoformat(timespec="seconds"),
        )
        result.events += 1


KNOWLEDGE_COLUMNS = (
    "id", "topic", "category", "claim", "evidence", "scope", "commit_sha",
    "source_task", "source_role", "status", "verification_count",
    "supporting_tasks", "superseded_by", "created_at", "last_verified_commit",
    "last_verified_at",
)


def import_knowledge(
    repo: Repository, db_path: Path, result: ImportResult,
    corpus: str | None = None,
) -> None:
    if not db_path.is_file():
        result.notes.append(f"no knowledge.db in snapshot: {db_path}")
        return

    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cols = ", ".join(KNOWLEDGE_COLUMNS)
        rows = conn.execute(f"SELECT {cols} FROM knowledge").fetchall()
    except sqlite3.Error as exc:
        result.notes.append(f"knowledge.db unreadable: {exc}")
        conn.close()
        return

    for row in rows:
        data: dict[str, Any] = dict(row)
        repo.upsert_claim(
            {
                "id": data["id"],
                "topic": data["topic"],
                "category": data["category"],
                "claim": data["claim"],
                "evidence_json": data["evidence"] or "[]",
                "scope": data["scope"] or "task",
                "commit_sha": data["commit_sha"],
                "source_task": data["source_task"],
                "source_role": data["source_role"],
                # Our status on first insert; ignored on conflict so the gate's
                # verdict survives. source_status keeps the origin's own view.
                "status": data["status"] or "candidate",
                "source_status": data["status"],
                # Stamped now so the claim is only ever resolved against
                # the repository it actually describes.
                "corpus": corpus,
                "verification_count": data["verification_count"] or 0,
                "supporting_tasks_json": data["supporting_tasks"] or "[]",
                "superseded_by": data["superseded_by"],
                "created_at": data["created_at"],
                "last_verified_commit": data["last_verified_commit"],
                "last_verified_at": data["last_verified_at"],
                "origin": "import",
            }
        )
        result.claims += 1
    conn.close()


def import_snapshot(
    repo: Repository, snapshot_dir: Path | str, corpus: str | None = None,
) -> ImportResult:
    snap = Path(snapshot_dir).expanduser().resolve()
    if not snap.is_dir():
        raise FileNotFoundError(f"snapshot not found: {snap}")

    result = ImportResult()
    import_agent_logs(repo, snap / "agent-logs", result)
    import_knowledge(repo, snap / "knowledge" / "knowledge.db", result, corpus)

    repo.add_event(
        "snapshot.imported",
        actor="am import",
        payload={
            "snapshot": str(snap),
            "tasks": result.tasks,
            "claims": result.claims,
            "skipped": len(result.skipped),
        },
    )
    result.events += 1
    return result
