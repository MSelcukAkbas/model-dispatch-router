import sqlite3

from agentmind.importer import import_snapshot, parse_meta
from agentmind.store import Database, Repository, resolve_db_path

META = """role=backend
timeout_min=25
effort=high
session_id=7b1e0f3a-0000-4000-8000-000000000001
no_worktree=0
account=akb34
config_dir=C:\\Users\\akbas\\.claude-akb34
max_budget_usd=1.50
attempt=2
"""


def _repo(tmp_path):
    db = Database(resolve_db_path(tmp_path))
    db.init_db()
    return db, Repository(db)


def test_parse_meta_keeps_windows_path_with_equals_and_backslashes():
    meta = parse_meta(META)
    assert meta["role"] == "backend"
    assert meta["config_dir"] == "C:\\Users\\akbas\\.claude-akb34"
    assert meta["max_budget_usd"] == "1.50"


def test_parse_meta_ignores_blank_and_malformed_lines():
    meta = parse_meta("role=ops\n\nnot-a-pair\n\neffort=high\n")
    assert meta == {"role": "ops", "effort": "high"}


def _make_snapshot(tmp_path):
    snap = tmp_path / "snapshots" / "s1"
    logs = snap / "agent-logs"
    logs.mkdir(parents=True)
    (logs / "KYC-64.meta").write_text(META, encoding="utf-8")
    (logs / "KYC-64.diffstat").write_text("42\n", encoding="utf-8")
    (logs / "FE-1.meta").write_text("role=research\naccount=\neffort=low\n", encoding="utf-8")

    kdir = snap / "knowledge"
    kdir.mkdir(parents=True)
    conn = sqlite3.connect(kdir / "knowledge.db")
    conn.execute(
        "CREATE TABLE knowledge (id INTEGER PRIMARY KEY, topic TEXT, category TEXT,"
        " claim TEXT, evidence TEXT, scope TEXT, commit_sha TEXT, source_task TEXT,"
        " source_role TEXT, status TEXT, verification_count INTEGER,"
        " supporting_tasks TEXT, superseded_by INTEGER, created_at TEXT,"
        " last_verified_commit TEXT, last_verified_at TEXT)"
    )
    conn.execute(
        "INSERT INTO knowledge VALUES (7,'auth-threshold','constraint','gate is 85',"
        " '[{\"file\":\"app/gate.py\",\"line\":12,\"dirty\":false}]','task','abc123',"
        " 'KYC-64','backend','candidate',0,'[\"KYC-64\"]',NULL,"
        " '2026-08-30T10:00:00+00:00',NULL,NULL)"
    )
    conn.commit()
    conn.close()
    return snap


def test_import_loads_tasks_claims_and_events(tmp_path):
    db, repo = _repo(tmp_path)
    snap = _make_snapshot(tmp_path)

    result = import_snapshot(repo, snap)

    assert result.tasks == 2
    assert result.claims == 1
    assert repo.count_tasks() == 2

    by_id = {r["task_id"]: r for r in repo.list_tasks()}
    kyc = by_id["KYC-64"]
    assert kyc["role"] == "backend"
    assert kyc["model"] == "sonnet"      # derived from ROLE_MODEL, not in .meta
    assert kyc["account"] == "akb34"
    assert kyc["budget_usd"] == 1.5
    assert kyc["attempt"] == 2
    assert kyc["diffstat"] == 42         # read from the sidecar file
    assert kyc["started_at_exact"] == 0  # mtime-derived, flagged inexact

    assert by_id["FE-1"]["model"] == "haiku"
    assert by_id["FE-1"]["account"] == ""

    claim = repo.list_claims()[0]
    assert claim["id"] == 7
    assert claim["status"] == "candidate"
    assert claim["source_task"] == "KYC-64"
    assert "app/gate.py" in claim["evidence_json"]

    assert len(repo.list_events(kind="task.imported")) == 2
    assert len(repo.list_events(kind="snapshot.imported")) == 1
    db.close()


def test_reimport_is_idempotent(tmp_path):
    db, repo = _repo(tmp_path)
    snap = _make_snapshot(tmp_path)

    import_snapshot(repo, snap)
    import_snapshot(repo, snap)

    assert repo.count_tasks() == 2
    assert repo.count_claims() == 1
    db.close()


def test_missing_pieces_are_reported_not_raised(tmp_path):
    db, repo = _repo(tmp_path)
    empty = tmp_path / "snapshots" / "empty"
    empty.mkdir(parents=True)

    result = import_snapshot(repo, empty)

    assert result.tasks == 0
    assert result.claims == 0
    assert len(result.notes) == 2
    db.close()


AGY_META = """role=judge
model=gemini-3.1-pro-high
timeout_min=5
engine=agy
"""


def test_agy_meta_keeps_its_own_model_and_engine(tmp_path):
    """dispatch-agy.sh names the real model; the ROLE_MODEL derivation must
    not overwrite it with the Claude-side default for that role."""
    db, repo = _repo(tmp_path)
    snap = tmp_path / "snapshots" / "agy"
    logs = snap / "agent-logs"
    logs.mkdir(parents=True)
    (logs / "evd-judge.agy.meta").write_text(AGY_META, encoding="utf-8")

    import_snapshot(repo, snap)

    row = repo.list_tasks()[0]
    assert row["role"] == "judge"
    assert row["model"] == "gemini-3.1-pro-high"   # not "opus"
    assert row["engine"] == "agy"
    db.close()


def test_claude_meta_defaults_to_claude_engine(tmp_path):
    db, repo = _repo(tmp_path)
    snap = _make_snapshot(tmp_path)
    import_snapshot(repo, snap)
    assert {r["engine"] for r in repo.list_tasks()} == {"claude"}
    db.close()
