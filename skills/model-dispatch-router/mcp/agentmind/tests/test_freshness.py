"""Deterministic staleness checks, run against a real throwaway git repo."""

import subprocess

import pytest

from agentmind.freshness import commits_since_evidence, evaluate, is_dirty, Freshness


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True,
                   capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "gate.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "other.py").write_text("y = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "first")
    return tmp_path


def _head(cwd):
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(cwd),
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def test_label_wording():
    assert Freshness(0, False).label == "fresh"
    assert Freshness(4, False).label == "stale(4)"
    assert Freshness(0, True).label == "dirty"       # dirty outranks fresh
    assert Freshness(None, False).label == "unknown"


def test_clean_file_is_not_dirty(repo):
    assert is_dirty(repo, "gate.py") is False


def test_uncommitted_edit_is_dirty(repo):
    (repo / "gate.py").write_text("x = 2\n", encoding="utf-8")
    assert is_dirty(repo, "gate.py") is True
    assert is_dirty(repo, "other.py") is False       # scoped to the path


def test_untracked_file_is_dirty(repo):
    (repo / "new.py").write_text("z = 1\n", encoding="utf-8")
    assert is_dirty(repo, "new.py") is True


def test_no_commits_since_means_fresh(repo):
    sha = _head(repo)
    assert commits_since_evidence(repo, sha, ["gate.py"]) == 0


def test_commits_touching_the_file_are_counted(repo):
    sha = _head(repo)
    for i in (2, 3):
        (repo / "gate.py").write_text(f"x = {i}\n", encoding="utf-8")
        _git(repo, "commit", "-qam", f"edit {i}")

    assert commits_since_evidence(repo, sha, ["gate.py"]) == 2
    # a commit elsewhere must not age this claim
    assert commits_since_evidence(repo, sha, ["other.py"]) == 0


def test_unanswerable_cases_return_none_not_zero(repo):
    """None ('cannot tell') must never be confused with 0 ('still fresh')."""
    assert commits_since_evidence(repo, None, ["gate.py"]) is None
    assert commits_since_evidence(repo, _head(repo), []) is None
    assert commits_since_evidence(repo, "0" * 40, ["gate.py"]) is None  # sha gone


def test_evaluate_combines_both_signals(repo):
    sha = _head(repo)
    assert evaluate(repo, sha, ["gate.py"]).label == "fresh"

    (repo / "gate.py").write_text("x = 9\n", encoding="utf-8")
    assert evaluate(repo, sha, ["gate.py"]).label == "dirty"


def test_outside_a_git_tree_is_unknown_not_fresh(tmp_path):
    verdict = evaluate(tmp_path, "abc123", ["a.py"])
    assert verdict.label == "unknown"
    assert "not a git working tree" in verdict.reason
