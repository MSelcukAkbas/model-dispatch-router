from pathlib import Path
import pytest

from agentmind.store import Database, Repository, resolve_db_path
from agentmind.sync import _prune_snapshots, sync


def test_prune_snapshots_retains_latest_n(tmp_path):
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()

    dirs = ["2026-09-01-010000", "2026-09-01-020000", "2026-09-01-030000",
            "2026-09-01-040000", "2026-09-01-050000"]
    for name in dirs:
        (snapshots / name).mkdir()
        (snapshots / name / "SOURCE.txt").write_text("dummy", encoding="utf-8")

    assert len(list(snapshots.iterdir())) == 5

    _prune_snapshots(snapshots, keep=3)

    remaining = sorted(d.name for d in snapshots.iterdir())
    assert remaining == ["2026-09-01-030000", "2026-09-01-040000", "2026-09-01-050000"]


def test_prune_snapshots_noop_when_fewer_than_keep(tmp_path):
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    (snapshots / "s1").mkdir()

    _prune_snapshots(snapshots, keep=3)
    assert [d.name for d in snapshots.iterdir()] == ["s1"]


def test_sync_places_snapshots_in_agentmind_dir_and_prunes(tmp_path):
    src = tmp_path / "live"
    logs = src / ".agent-logs"
    logs.mkdir(parents=True)
    (logs / "TASK-1.meta").write_text("role=backend\n", encoding="utf-8")

    ws = tmp_path / "ws"
    ws.mkdir()
    db = Database(resolve_db_path(ws))
    db.init_db()
    repo = Repository(db)

    # Run sync 5 times
    for _ in range(5):
        sync(repo, src, ws, corpus="live")

    # The root workspace must NEVER have a snapshots directory
    assert not (ws / "snapshots").exists()

    # Snapshots must live under .agentmind/snapshots
    snap_dir = ws / ".agentmind" / "snapshots"
    assert snap_dir.is_dir()

    # Must be pruned to at most 3
    retained = list(snap_dir.iterdir())
    assert len(retained) <= 3

    db.close()
