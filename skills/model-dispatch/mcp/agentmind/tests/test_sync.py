"""Catching up with a live repo, without writing to it.

Both regressions covered here were found by running `am sync` twice against
the real store, not by review.
"""

import json
import sqlite3
import subprocess

import pytest

from agentmind.importer import import_snapshot
from agentmind.resolver import normalise_nodes, resolve_claims
from agentmind.store import Database, Repository, resolve_db_path
from agentmind.sync import _demote_stale_verified, sync

pytest.importorskip("graphify", reason="needs the `graph` extra")


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True,
                   capture_output=True, text=True)


def _head(cwd):
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(cwd),
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def _knowledge_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE knowledge (id INTEGER PRIMARY KEY, topic TEXT, category TEXT,"
        " claim TEXT, evidence TEXT, scope TEXT, commit_sha TEXT, source_task TEXT,"
        " source_role TEXT, status TEXT, verification_count INTEGER,"
        " supporting_tasks TEXT, superseded_by INTEGER, created_at TEXT,"
        " last_verified_commit TEXT, last_verified_at TEXT)"
    )
    conn.executemany(
        "INSERT INTO knowledge VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    conn.close()


@pytest.fixture
def live(tmp_path):
    """A repo shaped like the real thing: .agent-logs plus a knowledge store."""
    src = tmp_path / "live"
    (src / "app").mkdir(parents=True)
    (src / "app" / "gate.py").write_text("def check():\n    return 1\n", encoding="utf-8")
    _git(src, "init", "-q")
    _git(src, "config", "user.email", "t@example.com")
    _git(src, "config", "user.name", "t")
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "first")
    sha = _head(src)

    logs = src / ".agent-logs"
    logs.mkdir()
    (logs / "T-1.meta").write_text("role=backend\naccount=akb34\n", encoding="utf-8")

    kdir = src / ".claude" / "knowledge"
    kdir.mkdir(parents=True)
    _knowledge_db(kdir / "knowledge.db", [(
        1, "gate.behaviour", "behavior", "check returns 1",
        json.dumps([{"file": "app/gate.py", "line": 1}]), "task", sha,
        "T-1", "backend", "candidate", 0, '["T-1"]', None,
        "2026-09-01T00:00:00+00:00", None, None,
    )])

    workspace = tmp_path / "ws"
    workspace.mkdir()
    db = Database(resolve_db_path(workspace))
    db.init_db()
    yield Repository(db), src, workspace, sha
    db.close()


def test_first_sync_picks_up_everything(live):
    repo, src, ws, _ = live

    result = sync(repo, src, ws, corpus="t")

    assert result.new_tasks == 1
    assert result.new_claims == 1
    assert result.graph_rebuilt
    assert result.resolved == 1
    assert result.changed


def test_second_sync_is_a_no_op(live):
    """Comparing newly-cited files against the graph made every unparseable
    file look new forever, so no sync was ever quiet."""
    repo, src, ws, _ = live
    sync(repo, src, ws, corpus="t")

    second = sync(repo, src, ws, corpus="t")

    assert second.new_tasks == 0
    assert second.new_claims == 0
    assert second.new_files == []
    assert not second.changed


def test_a_cited_file_that_cannot_be_extracted_is_not_new_forever(live):
    """A .yaml is cited and never lands in the graph; that must not read as
    change on every run."""
    repo, src, ws, sha = live
    (src / "app" / "conf.yaml").write_text("a: 1\n", encoding="utf-8")
    repo.upsert_claim({
        "id": 2, "topic": "conf", "category": "architecture", "claim": "c",
        "status": "candidate", "source_task": "T-1", "commit_sha": sha,
        "created_at": "2026-09-01T00:00:00+00:00",
        "evidence_json": json.dumps([{"file": "app/conf.yaml", "line": 1}]),
    })
    sync(repo, src, ws, corpus="t")

    second = sync(repo, src, ws, corpus="t")

    assert second.new_files == []
    assert not second.changed


def test_a_gate_verdict_survives_re_import(live):
    """The source knowledge store does not know this kernel exists. Letting its
    status win on conflict silently undid every verification on the next sync."""
    repo, src, ws, _ = live
    sync(repo, src, ws, corpus="t")
    repo.promote_claim(1)
    assert repo.list_claims()[0]["status"] == "verified"

    sync(repo, src, ws, corpus="t")

    claim = repo.list_claims()[0]
    assert claim["status"] == "verified"
    assert claim["source_status"] == "candidate"   # the origin's view, kept apart


def test_new_claims_arrive_on_a_later_sync(live):
    repo, src, ws, sha = live
    sync(repo, src, ws, corpus="t")

    kdb = src / ".claude" / "knowledge" / "knowledge.db"
    conn = sqlite3.connect(kdb)
    conn.execute(
        "INSERT INTO knowledge VALUES (2,'new.topic','bug','found a bug',?,"
        "'task',?, 'T-2','backend','candidate',0,'[\"T-2\"]',NULL,"
        "'2026-09-02T00:00:00+00:00',NULL,NULL)",
        (json.dumps([{"file": "app/gate.py", "line": 2}]), sha),
    )
    conn.commit()
    conn.close()

    result = sync(repo, src, ws, corpus="t")

    assert result.new_claims == 1
    assert result.changed


def test_verification_goes_stale_when_the_evidence_moves(live):
    """The gate says 'this held at that sha'. Once the file moves on, the
    sentence stops being about the code in the tree."""
    repo, src, ws, _ = live
    sync(repo, src, ws, corpus="t")
    repo.promote_claim(1, commit_sha=_head(src))

    (src / "app" / "gate.py").write_text("def check():\n    return 2\n", encoding="utf-8")
    _git(src, "commit", "-qam", "changed")

    demoted = _demote_stale_verified(repo, src)

    assert demoted == 1
    assert repo.list_claims()[0]["status"] == "stale"


def test_keeping_stale_is_opt_in(live):
    repo, src, ws, _ = live
    sync(repo, src, ws, corpus="t")
    repo.promote_claim(1, commit_sha=_head(src))
    (src / "app" / "gate.py").write_text("x = 3\n", encoding="utf-8")
    _git(src, "commit", "-qam", "changed")

    result = sync(repo, src, ws, corpus="t", mark_stale=False)

    assert result.promoted_stale == 0
    assert repo.list_claims()[0]["status"] == "verified"


def test_sync_never_writes_to_the_source(live):
    repo, src, ws, _ = live

    def tree():
        return {
            p.relative_to(src).as_posix(): p.stat().st_mtime_ns
            for p in sorted(src.rglob("*")) if p.is_file() and ".git/" not in p.as_posix()
        }

    before = tree()
    sync(repo, src, ws, corpus="t")
    assert tree() == before
