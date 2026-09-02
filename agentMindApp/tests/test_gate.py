"""The verification gate — the only path from candidate to verified."""

import json
import subprocess

import pytest

from agentmind.gate import Check, GateResult, evaluate_task, run_command
from agentmind.resolver import normalise_nodes, resolve_claims
from agentmind.store import Database, Repository, resolve_db_path


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True,
                   capture_output=True, text=True)


def _head(cwd):
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(cwd),
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


@pytest.fixture
def world(tmp_path):
    """A git tree with one file, a graph over it, and a claim citing it."""
    src = tmp_path / "src"
    (src / "app").mkdir(parents=True)
    (src / "app" / "gate.py").write_text("def check():\n    return 1\n", encoding="utf-8")
    _git(src, "init", "-q")
    _git(src, "config", "user.email", "t@example.com")
    _git(src, "config", "user.name", "t")
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "first")

    db = Database(resolve_db_path(tmp_path))
    db.init_db()
    repo = Repository(db)
    repo.replace_graph("t", normalise_nodes([
        {"id": "gate_mod", "label": "gate.py", "source_file": "app/gate.py",
         "source_location": "L1"},
        {"id": "gate_check", "label": "check()", "source_file": "app/gate.py",
         "source_location": "L1"},
    ]), [])
    repo.upsert_claim({
        "id": 1, "topic": "gate.behaviour", "category": "behavior",
        "claim": "check() returns 1", "status": "candidate",
        "source_task": "T-1", "commit_sha": _head(src),
        "created_at": "2026-09-01T00:00:00+00:00",
        "evidence_json": json.dumps([{"file": "app/gate.py", "line": 1}]),
    })
    resolve_claims(repo, "t", source_root=src)
    yield repo, src
    db.close()


# ------------------------------------------------------------------ passing
def test_clean_fresh_evidence_passes_and_promotes(world):
    repo, src = world

    result = evaluate_task(repo, "T-1", src, promote=True)

    assert result.passed
    assert result.promoted == 1
    claim = repo.list_claims()[0]
    assert claim["status"] == "verified"
    assert claim["verification_count"] == 1
    assert claim["last_verified_at"]


def test_without_promote_nothing_is_written_to_the_claim(world):
    """Inspecting the gate must not change state."""
    repo, src = world

    result = evaluate_task(repo, "T-1", src, promote=False)

    assert result.passed
    assert result.promoted == 0
    assert repo.list_claims()[0]["status"] == "candidate"


def test_a_gate_run_is_recorded_either_way(world):
    repo, src = world
    evaluate_task(repo, "T-1", src)
    assert len(repo.list_events(kind="gate.passed")) == 1


# ------------------------------------------------------------------ failing
def test_uncommitted_changes_fail_the_gate(world):
    """Evidence must describe committed code, not a dirty working tree."""
    repo, src = world
    (src / "app" / "gate.py").write_text("def check():\n    return 2\n", encoding="utf-8")

    result = evaluate_task(repo, "T-1", src, promote=True)

    assert not result.passed
    assert result.promoted == 0
    assert repo.list_claims()[0]["status"] == "candidate"
    assert not next(c for c in result.checks if c.name == "evidence_clean").ok


def test_commits_since_the_claim_fail_the_gate(world):
    repo, src = world
    (src / "app" / "gate.py").write_text("def check():\n    return 3\n", encoding="utf-8")
    _git(src, "commit", "-qam", "changed")

    result = evaluate_task(repo, "T-1", src)

    assert not result.passed
    assert not next(c for c in result.checks if c.name == "evidence_fresh").ok


def test_deleted_evidence_file_fails_present_and_resolves(world):
    repo, src = world
    (src / "app" / "gate.py").unlink()
    _git(src, "commit", "-qam", "removed")
    repo.replace_graph("t", [], [])
    resolve_claims(repo, "t", source_root=src)

    result = evaluate_task(repo, "T-1", src)

    by_name = {c.name: c for c in result.checks}
    assert not by_name["evidence_present"].ok
    assert not by_name["evidence_resolves"].ok


def test_unknown_freshness_is_not_a_pass(world):
    """'Cannot tell' must never be recorded as verified."""
    repo, src = world
    repo.upsert_claim({
        "id": 2, "topic": "t", "category": "behavior", "claim": "c",
        "status": "candidate", "source_task": "T-2", "commit_sha": None,
        "created_at": "2026-09-01T00:00:00+00:00",
        "evidence_json": json.dumps([{"file": "app/gate.py", "line": 1}]),
    })
    resolve_claims(repo, "t", source_root=src)

    result = evaluate_task(repo, "T-2", src)

    assert not result.passed
    fresh = next(c for c in result.checks if c.name == "evidence_fresh")
    assert "unanswerable" in fresh.detail


def test_a_task_with_no_claims_does_not_pass_vacuously(world):
    repo, src = world
    result = evaluate_task(repo, "T-nonexistent", src)
    assert not result.passed
    assert result.claims == 0


# ----------------------------------------------------------------- command
def test_command_exit_zero_passes(tmp_path):
    check = run_command("exit 0", tmp_path)
    assert check.ok


def test_command_nonzero_fails_and_keeps_the_tail(tmp_path):
    check = run_command("echo boom && exit 3", tmp_path)
    assert not check.ok
    assert "boom" in check.detail


def test_failing_command_blocks_promotion(world):
    repo, src = world

    result = evaluate_task(repo, "T-1", src, command="exit 1", promote=True)

    assert not result.passed
    assert result.promoted == 0
    assert repo.list_claims()[0]["status"] == "candidate"


def test_passing_command_is_included_in_the_verdict(world):
    repo, src = world
    result = evaluate_task(repo, "T-1", src, command="exit 0", promote=True)
    assert result.passed
    assert any(c.name == "command" for c in result.checks)
    assert result.promoted == 1


# -------------------------------------------------------------- properties
def test_gate_result_needs_at_least_one_check_to_pass():
    assert not GateResult(task_id="x").passed
    assert GateResult(task_id="x", checks=[Check("a", True)]).passed
    assert not GateResult(task_id="x", checks=[Check("a", True), Check("b", False)]).passed


def test_promotion_only_touches_candidates(world):
    repo, src = world
    repo.promote_claim(1)                     # already verified
    before = repo.list_claims()[0]["verification_count"]
    repo.promote_claim(1)                     # must be a no-op now
    assert repo.list_claims()[0]["verification_count"] == before
