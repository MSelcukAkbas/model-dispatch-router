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
    repo.add_event("task.dispatched", task_id="TASK-1", payload={"role": "backend"})
    repo.add_event("task.result", task_id="TASK-1", payload={"status": "DONE"})
    repo.add_event("task.dispatched", task_id="TASK-2")

    assert repo.count_events() == 3
    assert len(repo.list_events(kind="task.dispatched")) == 2
    assert len(repo.list_events(task_id="TASK-1")) == 2
    assert repo.list_events(limit=1)[0]["kind"] == "task.dispatched"
    db.close()


def test_upsert_task_overwrites_on_reimport(tmp_path):
    db, repo = _repo(tmp_path)
    repo.upsert_task({"task_id": "TASK-9", "role": "backend", "attempt": 1})
    repo.upsert_task({"task_id": "TASK-9", "role": "backend", "attempt": 3})

    rows = repo.list_tasks()
    assert len(rows) == 1
    assert rows[0]["attempt"] == 3
    db.close()


def test_account_filter_matches_ambient_empty_string(tmp_path):
    db, repo = _repo(tmp_path)
    repo.upsert_task({"task_id": "A", "role": "backend", "account": ""})
    repo.upsert_task({"task_id": "B", "role": "backend", "account": "secondary"})

    assert {r["task_id"] for r in repo.list_tasks(account="")} == {"A"}
    assert {r["task_id"] for r in repo.list_tasks(account="secondary")} == {"B"}
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
    repo.upsert_task({"task_id": "C", "role": "research", "engine": "claude", "account": "secondary"})

    rows = {(r["engine"], r["account"]): r["n"] for r in repo.task_stats()}
    assert rows == {("agy", "n/a"): 1, ("claude", "ambient"): 1, ("claude", "secondary"): 1}
    db.close()


def test_find_store_walks_up_like_git_looks_for_dot_git(tmp_path):
    """Running one directory away from the store must find it, not miss it."""
    from agentmind.store import find_store

    workspace = tmp_path / "workspace"
    deep = workspace / "app" / "src" / "pkg"
    deep.mkdir(parents=True)
    Database(resolve_db_path(workspace)).init_db()

    assert find_store(deep) == workspace / ".agentmind" / "am.db"
    assert find_store(workspace) == workspace / ".agentmind" / "am.db"


def test_find_store_returns_none_when_there_is_none(tmp_path):
    from agentmind.store import find_store

    empty = tmp_path / "nothing" / "here"
    empty.mkdir(parents=True)
    assert find_store(empty) is None


def test_an_explicit_root_always_wins_over_the_search(tmp_path):
    from agentmind.store import find_store, resolve_db_path as rdp

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    Database(rdp(workspace)).init_db()
    other = tmp_path / "other"

    assert rdp(other) == other / ".agentmind" / "am.db"
    assert find_store(workspace) is not None


def test_nearby_stores_looks_one_level_down(tmp_path):
    """Standing just above a workspace is the easiest mistake to make and the
    least obvious to diagnose, so the failure path offers a way out."""
    from agentmind.store import find_store, nearby_stores

    workspace = tmp_path / "myproject"
    workspace.mkdir()
    Database(resolve_db_path(workspace)).init_db()
    (tmp_path / "unrelated").mkdir()

    assert find_store(tmp_path) is None          # upward search finds nothing
    assert nearby_stores(tmp_path) == [workspace]


def test_nearby_stores_skips_dotted_directories(tmp_path):
    from agentmind.store import nearby_stores

    hidden = tmp_path / ".cache"
    hidden.mkdir()
    Database(resolve_db_path(hidden)).init_db()

    assert nearby_stores(tmp_path) == []


def test_nearby_stores_is_empty_when_there_is_nothing(tmp_path):
    from agentmind.store import nearby_stores

    (tmp_path / "a").mkdir()
    assert nearby_stores(tmp_path) == []
