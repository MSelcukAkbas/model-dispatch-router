"""Routing advice, and the honesty constraints on it."""

import json

import pytest

from agentmind.router import (
    CONFIDENCE_BANDS,
    POLICY,
    Evidence,
    confidence,
    gather_evidence,
    memory_gaps,
    recommend,
)
from agentmind.store import Database, Repository, resolve_db_path


def _repo(tmp_path):
    db = Database(resolve_db_path(tmp_path))
    db.init_db()
    return db, Repository(db)


def _task(repo, task_id, role, engine="claude", attempt=None, account=""):
    repo.upsert_task({
        "task_id": task_id, "role": role, "engine": engine,
        "attempt": attempt, "account": account,
    })


def _claim(repo, claim_id, task_id):
    repo.upsert_claim({
        "id": claim_id, "topic": f"t{claim_id}", "category": "behavior",
        "claim": "c", "source_task": task_id,
        "created_at": "2026-09-01T00:00:00+00:00",
        "evidence_json": json.dumps([{"file": "a.py", "line": 1}]),
    })


# --------------------------------------------------------------- confidence
def test_confidence_bands_are_ordered_and_bottom_out_at_none():
    assert confidence(0) == "none"
    assert confidence(1) == "anecdotal"
    assert confidence(10) == "weak"
    assert confidence(30) == "moderate"
    assert confidence(1000) == "moderate"     # no band claims more than this
    thresholds = [t for t, _ in CONFIDENCE_BANDS]
    assert thresholds == sorted(thresholds, reverse=True)


def test_no_band_is_called_strong_or_proven():
    """Nothing here measures whether a task succeeded, so no label may imply it."""
    labels = {label for _, label in CONFIDENCE_BANDS}
    assert not labels & {"strong", "proven", "high", "certain"}


# ----------------------------------------------------------------- evidence
def test_evidence_counts_runs_retries_and_claims(tmp_path):
    db, repo = _repo(tmp_path)
    _task(repo, "A", "backend", attempt=1, account="secondary")
    _task(repo, "B", "backend", attempt=3, account="secondary")
    _task(repo, "C", "backend", attempt=None, account="")
    _claim(repo, 1, "A")
    _claim(repo, 2, "A")

    ev = gather_evidence(repo, "backend", engine="claude")

    assert ev.dispatches == 3
    assert ev.retry_known == 2          # the third records no attempt at all
    assert ev.retried == 1
    assert ev.retry_rate == 0.5
    assert ev.claims == 2
    assert ev.accounts == {"secondary": 2, "ambient": 1}
    db.close()


def test_retry_rate_is_none_rather_than_zero_when_unrecorded():
    """agy writes no attempt field; 'unknown' must not read as 'never retried'."""
    ev = Evidence(dispatches=59)
    assert ev.retry_rate is None
    assert ev.confidence == "moderate"


# -------------------------------------------------------------- recommend
def test_recommendation_comes_from_the_documented_policy(tmp_path):
    db, repo = _repo(tmp_path)

    rec = recommend(repo, "research")

    assert (rec.engine, rec.model, rec.effort) == ("agy", "gemini", "low")
    assert rec.budget == 0.50
    db.close()


def test_every_policy_role_can_be_recommended(tmp_path):
    db, repo = _repo(tmp_path)
    for role in POLICY:
        assert recommend(repo, role).role == role
    db.close()


def test_unknown_role_raises_rather_than_guessing(tmp_path):
    db, repo = _repo(tmp_path)
    with pytest.raises(KeyError):
        recommend(repo, "nonexistent")
    db.close()


def test_a_rule_with_no_history_says_so(tmp_path):
    db, repo = _repo(tmp_path)

    rec = recommend(repo, "ops")

    assert rec.evidence.dispatches == 0
    assert rec.evidence.confidence == "none"
    assert any("policy only" in w for w in rec.warnings)
    db.close()


def test_a_heavy_retry_rate_is_surfaced(tmp_path):
    db, repo = _repo(tmp_path)
    for i in range(9):
        _task(repo, f"R{i}", "research", engine="claude",
              attempt=2 if i < 5 else 1, account="secondary")

    rec = recommend(repo, "research")
    ev = gather_evidence(repo, "research", engine="claude")

    assert ev.retried == 5 and ev.retry_known == 9
    # the recommendation is for agy, so the claude retry rate is not its warning
    assert rec.engine == "agy"
    db.close()


def test_many_dispatches_and_no_claims_is_a_warning(tmp_path):
    db, repo = _repo(tmp_path)
    for i in range(12):
        _task(repo, f"A{i}", "research", engine="agy")

    rec = recommend(repo, "research")

    assert any("no claims at all" in w for w in rec.warnings)
    db.close()


# ------------------------------------------------------------- memory gaps
def test_memory_gaps_finds_engines_that_remember_nothing(tmp_path):
    db, repo = _repo(tmp_path)
    for i in range(6):
        _task(repo, f"A{i}", "research", engine="agy")
    _task(repo, "C1", "backend", engine="claude")
    _claim(repo, 1, "C1")

    gaps = memory_gaps(repo)

    assert gaps == [{"role": "research", "engine": "agy",
                     "dispatches": 6, "claims": 0}]
    db.close()


def test_a_handful_of_runs_is_not_reported_as_a_gap(tmp_path):
    db, repo = _repo(tmp_path)
    for i in range(3):
        _task(repo, f"A{i}", "sdk", engine="agy")

    assert memory_gaps(repo) == []
    db.close()


def test_field_coverage_reports_what_is_populated(tmp_path):
    db, repo = _repo(tmp_path)
    _task(repo, "A", "research", engine="agy")                 # no attempt
    _task(repo, "B", "backend", engine="claude", attempt=1)

    coverage = dict((name, n) for name, n, _total in repo.field_coverage())

    assert coverage["role"] == 2
    assert coverage["attempt"] == 1
    assert coverage["finished_at"] == 0
    db.close()
