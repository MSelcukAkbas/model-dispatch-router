import sqlite3

from agentmind.snapshot import take_snapshot


def _fake_repo(tmp_path):
    """A minimal stand-in for a live model-dispatch repo."""
    src = tmp_path / "live"
    logs = src / ".agent-logs"
    logs.mkdir(parents=True)
    (logs / "TASK-1.meta").write_text("role=backend\naccount=\n", encoding="utf-8")
    (logs / "TASK-1.attempt").write_text("1\n", encoding="utf-8")
    (logs / "TASK-1.diffstat").write_text("10\n", encoding="utf-8")
    (logs / "TASK-1.json").write_text('{"type":"run"}\n', encoding="utf-8")

    kdir = src / ".claude" / "knowledge"
    kdir.mkdir(parents=True)
    conn = sqlite3.connect(kdir / "knowledge.db")
    conn.execute("CREATE TABLE knowledge (id INTEGER PRIMARY KEY, topic TEXT)")
    conn.execute("INSERT INTO knowledge VALUES (1,'t')")
    conn.commit()
    conn.close()
    return src


def _tree(path):
    return {
        p.relative_to(path).as_posix(): p.stat().st_mtime_ns
        for p in sorted(path.rglob("*"))
        if p.is_file()
    }


def test_snapshot_copies_meta_sidecars_and_knowledge(tmp_path):
    src = _fake_repo(tmp_path)
    result = take_snapshot(src, tmp_path / "snapshots", label="s1")

    assert result.knowledge_db is True
    assert result.agent_log_files == 3  # meta + attempt + diffstat, no *.json
    assert (result.dest / "agent-logs" / "TASK-1.meta").is_file()
    assert not (result.dest / "agent-logs" / "TASK-1.json").exists()
    assert (result.dest / "knowledge" / "knowledge.db").is_file()
    assert "source:" in (result.dest / "SOURCE.txt").read_text(encoding="utf-8")


def test_with_logs_also_copies_run_logs(tmp_path):
    src = _fake_repo(tmp_path)
    result = take_snapshot(src, tmp_path / "snapshots", with_logs=True, label="s2")
    assert result.agent_log_files == 4
    assert (result.dest / "agent-logs" / "TASK-1.json").is_file()


def test_snapshot_never_writes_to_the_source(tmp_path):
    """The isolation guarantee Phase 0 rests on, asserted mechanically."""
    src = _fake_repo(tmp_path)
    before = _tree(src)

    take_snapshot(src, tmp_path / "snapshots", label="s3")

    assert _tree(src) == before


def test_copied_knowledge_db_is_readable_and_complete(tmp_path):
    src = _fake_repo(tmp_path)
    result = take_snapshot(src, tmp_path / "snapshots", label="s4")

    conn = sqlite3.connect(result.dest / "knowledge" / "knowledge.db")
    assert conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0] == 1
    conn.close()


def test_missing_directories_are_notes_not_errors(tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()
    result = take_snapshot(bare, tmp_path / "snapshots", label="s5")

    assert result.agent_log_files == 0
    assert result.knowledge_db is False
    assert len(result.notes) == 2


def test_unlabelled_snapshots_are_unique(tmp_path):
    src = _fake_repo(tmp_path)
    first = take_snapshot(src, tmp_path / "snapshots")
    second = take_snapshot(src, tmp_path / "snapshots")

    assert first.dest != second.dest
    assert first.dest.is_dir()
    assert second.dest.is_dir()
