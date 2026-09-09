"""Finding the store, and never creating one where it does not belong."""

import json

import pytest
from typer.testing import CliRunner

from agentmind import workspace
from agentmind.cli import app
from agentmind.store import DEFAULT_DB_RELPATH, Database, Repository, resolve_db_path

runner = CliRunner()


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """Point the user-level registry at a throwaway file."""
    path = tmp_path / "registry"
    monkeypatch.setattr(workspace, "REGISTRY", path)
    return path


def _workspace(tmp_path, name="ws", watching=None):
    root = tmp_path / name
    db = Database(resolve_db_path(root))
    db.init_db()
    repo = Repository(db)
    if watching is not None:
        repo.remember_corpus("c", watching)
    db.close()
    return root


# ------------------------------------------------------------------ registry
def test_register_is_idempotent(tmp_path, registry):
    root = _workspace(tmp_path)

    workspace.register(root)
    workspace.register(root)

    assert workspace.registered_workspaces() == [root.resolve()]


def test_a_registered_workspace_that_vanished_is_skipped(tmp_path, registry):
    root = _workspace(tmp_path)
    workspace.register(root)
    (root / DEFAULT_DB_RELPATH).unlink()

    assert workspace.registered_workspaces() == []


# -------------------------------------------------------------------- lookup
def test_a_store_above_wins(tmp_path, registry):
    root = _workspace(tmp_path)
    deep = root / "a" / "b"
    deep.mkdir(parents=True)

    found, how = workspace.locate_store(deep)

    assert found == root.resolve()
    assert "above" in how


def test_the_workspace_watching_this_repo_is_found_from_inside_it(tmp_path, registry):
    """The watched repo is not an ancestor of the workspace, so upward search
    alone left `am sync` blind in the one directory you actually work in."""
    watched = tmp_path / "their-project"
    watched.mkdir()
    root = _workspace(tmp_path, watching=watched)
    workspace.register(root)

    found, how = workspace.locate_store(watched)

    assert found == root.resolve()
    assert "watching" in how


def test_a_subdirectory_of_a_watched_repo_also_resolves(tmp_path, registry):
    watched = tmp_path / "their-project"
    (watched / "src" / "deep").mkdir(parents=True)
    root = _workspace(tmp_path, watching=watched)
    workspace.register(root)

    found, _ = workspace.locate_store(watched / "src" / "deep")

    assert found == root.resolve()


def test_a_lone_unrelated_workspace_is_not_guessed(tmp_path, registry):
    root = _workspace(tmp_path)
    workspace.register(root)
    elsewhere = tmp_path / "unrelated"
    elsewhere.mkdir()

    found, how = workspace.locate_store(elsewhere)

    assert found is None
    assert how == "not found"


def test_two_workspaces_and_no_match_is_not_a_guess(tmp_path, registry):
    workspace.register(_workspace(tmp_path, "one"))
    workspace.register(_workspace(tmp_path, "two"))
    elsewhere = tmp_path / "unrelated"
    elsewhere.mkdir()

    found, _ = workspace.locate_store(elsewhere)

    assert found is None


# ----------------------------------------------------- never create by accident
def test_a_read_command_never_creates_a_store(tmp_path, registry):
    """This is not hypothetical. `am sync` fell back to the current directory
    and created .agentmind inside the repo it is only ever meant to read."""
    target = tmp_path / "someone-elses-repo"
    target.mkdir()

    result = runner.invoke(app, ["status", "--root", str(target)])

    assert result.exit_code == 2
    assert not (target / DEFAULT_DB_RELPATH).exists()
    assert not (target / ".agentmind").exists()


def test_sync_without_a_store_creates_nothing(tmp_path, registry):
    target = tmp_path / "someone-elses-repo"
    target.mkdir()

    result = runner.invoke(app, ["sync", "--root", str(target)])

    assert result.exit_code == 2
    assert not (target / ".agentmind").exists()


def test_setup_is_allowed_to_create(tmp_path, registry):
    target = tmp_path / "fresh"

    result = runner.invoke(app, ["init", "--root", str(target)])

    assert result.exit_code == 0
    assert (target / DEFAULT_DB_RELPATH).is_file()


# ------------------------------------------------------------------- corpora
def test_a_remembered_corpus_supplies_the_path_later(tmp_path, registry):
    root = tmp_path / "ws"
    db = Database(resolve_db_path(root))
    db.init_db()
    repo = Repository(db)
    repo.remember_corpus("project", tmp_path / "their-project")

    row = repo.corpus("project")
    assert row["source_path"] == str((tmp_path / "their-project").resolve())
    assert repo.only_corpus()["name"] == "project"

    repo.remember_corpus("second", tmp_path)
    assert repo.only_corpus() is None      # ambiguous, so no silent pick
    db.close()
