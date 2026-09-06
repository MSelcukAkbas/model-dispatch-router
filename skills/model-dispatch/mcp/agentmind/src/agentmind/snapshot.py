"""Take a read-only snapshot of a live model-dispatch repo.

Strictly one-way: this module opens the source repo for reading and writes
only inside this project's snapshots/ directory. Nothing here creates,
modifies or deletes a file under the source path — that is the whole point of
the isolation decision behind Phase 0.
"""

from __future__ import annotations

import shutil
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# dispatch.sh sidecars we need to reconstruct a dispatch. The stream-json run
# logs (<task>.json) are deliberately not copied by default — there are
# hundreds of them and Phase 0 needs none of their content.
META_GLOBS = ("*.meta", "*.attempt", "*.diffstat")
LOG_GLOBS = ("*.json",)


@dataclass
class SnapshotResult:
    dest: Path
    agent_log_files: int = 0
    knowledge_db: bool = False
    notes: list[str] = field(default_factory=list)


def _copy_sqlite_readonly(src: Path, dest: Path, notes: list[str]) -> bool:
    """Copy a SQLite file without writing to the source.

    Preferred path is the backup API over a read-only URI connection, which
    yields a consistent single file even when the source is in WAL mode with
    uncheckpointed pages. If SQLite refuses the read-only open (a WAL database
    that would need recovery cannot be opened ro), fall back to copying the
    db plus its -wal/-shm siblings so the copy is still complete.
    """
    try:
        src_conn = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
        try:
            dest_conn = sqlite3.connect(dest)
            try:
                src_conn.backup(dest_conn)
            finally:
                dest_conn.close()
        finally:
            src_conn.close()
        return True
    except sqlite3.Error as exc:
        notes.append(f"read-only backup failed ({exc}); copied db+wal+shm instead")
        copied = False
        for suffix in ("", "-wal", "-shm"):
            sibling = Path(str(src) + suffix)
            if sibling.exists():
                shutil.copy2(sibling, Path(str(dest) + suffix))
                copied = True
        return copied


def take_snapshot(
    source: Path | str,
    snapshots_root: Path | str,
    *,
    with_logs: bool = False,
    label: str | None = None,
) -> SnapshotResult:
    src = Path(source).expanduser().resolve()
    if not src.is_dir():
        raise FileNotFoundError(f"source repo not found: {src}")

    stamp = label or (
        datetime.now().strftime("%Y-%m-%d-%H%M%S-%f")
        + f"-{uuid.uuid4().hex[:8]}"
    )
    dest = Path(snapshots_root).expanduser().resolve() / stamp
    result = SnapshotResult(dest=dest)
    # Created up front: a source repo with neither .agent-logs nor a
    # knowledge.db still produces a valid (empty) snapshot with SOURCE.txt.
    dest.mkdir(parents=True, exist_ok=True)

    agent_logs = src / ".agent-logs"
    if agent_logs.is_dir():
        out = dest / "agent-logs"
        out.mkdir(parents=True, exist_ok=True)
        globs = META_GLOBS + (LOG_GLOBS if with_logs else ())
        for pattern in globs:
            for path in agent_logs.glob(pattern):
                if path.is_file():
                    shutil.copy2(path, out / path.name)
                    result.agent_log_files += 1
    else:
        result.notes.append(f"no .agent-logs directory under {src}")

    knowledge = src / ".claude" / "knowledge" / "knowledge.db"
    if knowledge.is_file():
        out = dest / "knowledge"
        out.mkdir(parents=True, exist_ok=True)
        result.knowledge_db = _copy_sqlite_readonly(
            knowledge, out / "knowledge.db", result.notes
        )
    else:
        result.notes.append(f"no knowledge.db under {src / '.claude' / 'knowledge'}")

    (dest / "SOURCE.txt").write_text(
        f"source: {src}\ntaken_at: {datetime.now().isoformat(timespec='seconds')}\n"
        f"with_logs: {with_logs}\n",
        encoding="utf-8",
    )
    return result
