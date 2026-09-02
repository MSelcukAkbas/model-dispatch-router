from agentmind.store import Database, Repository, resolve_db_path


def _repo(tmp_path):
    db = Database(resolve_db_path(tmp_path))
    db.init_db()
    return db, Repository(db)


def test_init_creates_db_and_tables(tmp_path):
    db, repo = _repo(tmp_path)
    names = {
        r[0]
        for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"events", "tasks", "claims", "node_refs"} <= names
    assert repo.count_events() == 0
    db.close()


def test_events_append_and_filter(tmp_path):
    db, repo = _repo(tmp_path)
    repo.add_event("task.dispatched", task_id="KYC-1", payload={"role": "backend"})
    repo.add_event("task.result", task_id="KYC-1", payload={"status": "DONE"})
    repo.add_event("task.dispatched", task_id="FE-2")

    assert repo.count_events() == 3
    assert len(repo.list_events(kind="task.dispatched")) == 2
    assert len(repo.list_events(task_id="KYC-1")) == 2
    assert repo.list_events(limit=1)[0]["kind"] == "task.dispatched"
    db.close()


def test_upsert_task_overwrites_on_reimport(tmp_path):
    db, repo = _repo(tmp_path)
    repo.upsert_task({"task_id": "KYC-9", "role": "backend", "attempt": 1})
    repo.upsert_task({"task_id": "KYC-9", "role": "backend", "attempt": 3})

    rows = repo.list_tasks()
    assert len(rows) == 1
    assert rows[0]["attempt"] == 3
    db.close()


def test_account_filter_matches_ambient_empty_string(tmp_path):
    db, repo = _repo(tmp_path)
    repo.upsert_task({"task_id": "A", "role": "backend", "account": ""})
    repo.upsert_task({"task_id": "B", "role": "backend", "account": "akb34"})

    assert {r["task_id"] for r in repo.list_tasks(account="")} == {"A"}
    assert {r["task_id"] for r in repo.list_tasks(account="akb34")} == {"B"}
    db.close()


def test_claim_status_lifecycle_values_round_trip(tmp_path):
    db, repo = _repo(tmp_path)
    for i, status in enumerate(
        ["candidate", "verified", "stale", "superseded", "promoted"], start=1
    ):
        repo.upsert_claim(
            {
                "id": i,
                "topic": f"t-{i}",
                "category": "behavior",
                "claim": "c",
                "created_at": "2026-09-01T00:00:00+00:00",
                "status": status,
            }
        )
    counts = {r["status"]: r["n"] for r in repo.claim_status_counts()}
    assert counts == {
        "candidate": 1, "verified": 1, "stale": 1, "superseded": 1, "promoted": 1
    }
    assert len(repo.list_claims(status="verified")) == 1
    db.close()


def test_task_stats_separates_agy_from_ambient_claude(tmp_path):
    """An agy .meta has no account field. Without the engine split its rows
    would group under 'ambient' and be counted as Claude dispatches."""
    db, repo = _repo(tmp_path)
    repo.upsert_task({"task_id": "A", "role": "research", "engine": "agy", "account": ""})
    repo.upsert_task({"task_id": "B", "role": "research", "engine": "claude", "account": ""})
    repo.upsert_task({"task_id": "C", "role": "research", "engine": "claude", "account": "akb34"})

    rows = {(r["engine"], r["account"]): r["n"] for r in repo.task_stats()}
    assert rows == {("agy", "n/a"): 1, ("claude", "ambient"): 1, ("claude", "akb34"): 1}
    db.close()
