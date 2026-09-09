"""Prompt construction: the graph body plus the claim overlay, under budget."""

import json

import pytest

from agentmind.context import (
    CHARS_PER_TOKEN,
    STATUS_RANK,
    _claim_lines,
    _collect_claims,
    build_context,
    build_file_context,
    estimate_tokens,
    is_safe_context_path,
    load_graph,
    pick_seeds,
)
from agentmind.resolver import normalise_nodes, resolve_claims
from agentmind.store import Database, Repository, resolve_db_path

pytest.importorskip("graphify", reason="needs the `graph` extra")


def _repo(tmp_path):
    db = Database(resolve_db_path(tmp_path))
    db.init_db()
    return db, Repository(db)


NODES = [
    {"id": "gate_mod", "label": "gate.py", "source_file": "app/gate.py",
     "source_location": "L1"},
    {"id": "gate_check", "label": "checkScore()", "source_file": "app/gate.py",
     "source_location": "L10"},
    {"id": "util_mod", "label": "util.py", "source_file": "app/util.py",
     "source_location": "L1"},
]
EDGES = [{"source": "gate_check", "target": "util_mod", "relation": "calls",
          "confidence": "EXTRACTED", "source_location": "L12"}]


def _seed_graph(repo):
    from agentmind.resolver import normalise_edges

    repo.replace_graph("t", normalise_nodes(NODES), normalise_edges(EDGES))


def _add_claim(repo, claim_id, status, file="app/gate.py", line=12, topic=None):
    repo.upsert_claim({
        "id": claim_id,
        "topic": topic or f"topic-{claim_id}",
        "category": "behavior",
        "claim": f"claim body {claim_id}",
        "status": status,
        "source_task": f"T-{claim_id}",
        "commit_sha": None,
        "created_at": "2026-09-01T00:00:00+00:00",
        "evidence_json": json.dumps([{"file": file, "line": line}]),
        "corpus": "t",
    })


# ------------------------------------------------------------------ basics
def test_estimate_tokens_uses_the_same_ratio_as_graphify():
    assert estimate_tokens("x" * (CHARS_PER_TOKEN * 10)) == 10
    assert estimate_tokens("") == 1        # never zero, so ratios stay safe


def test_load_graph_restores_the_L_prefixed_location(tmp_path):
    """The renderer reads source_location; storing an int and forgetting to
    render it back would silently drop every line anchor."""
    db, repo = _repo(tmp_path)
    _seed_graph(repo)

    graph = load_graph(repo, "t")

    assert graph.nodes["gate_check"]["source_location"] == "L10"
    assert graph.nodes["gate_mod"]["source_file"] == "app/gate.py"
    assert graph.has_edge("gate_check", "util_mod")
    db.close()


def test_pick_seeds_finds_the_queried_symbol(tmp_path):
    db, repo = _repo(tmp_path)
    _seed_graph(repo)
    graph = load_graph(repo, "t")

    assert "gate_check" in pick_seeds(graph, "checkScore")
    assert pick_seeds(graph, "") == []
    db.close()


def test_no_match_returns_empty_rather_than_a_useless_prompt(tmp_path):
    db, repo = _repo(tmp_path)
    _seed_graph(repo)

    result = build_context(repo, "t", "zzzz-nothing-matches-this")

    assert result.text == ""
    assert result.tokens == 0
    db.close()


def test_sensitive_paths_never_enter_generated_context(tmp_path):
    db, repo = _repo(tmp_path)
    from agentmind.resolver import normalise_edges

    nodes = NODES + [
        {"id": "claude", "label": "CLAUDE.md", "source_file": "CLAUDE.md", "source_location": "L1"},
        {"id": "env", "label": ".env", "source_file": "config/.env.production", "source_location": "L1"},
    ]
    repo.replace_graph("t", normalise_nodes(nodes), normalise_edges([]))

    result = build_context(repo, "t", "CLAUDE env", budget=200)

    assert not is_safe_context_path("CLAUDE.md")
    assert not is_safe_context_path("config/.env.production")
    assert is_safe_context_path("app/gate.py")
    assert "CLAUDE.md" not in result.text
    assert ".env.production" not in result.text
    db.close()


# ------------------------------------------------------------------ claims
def test_claims_are_ranked_by_status_then_freshness(tmp_path):
    db, repo = _repo(tmp_path)
    _seed_graph(repo)
    _add_claim(repo, 1, "superseded")
    _add_claim(repo, 2, "verified")
    _add_claim(repo, 3, "candidate")
    resolve_claims(repo, "t")

    ordered = _collect_claims(repo, {"gate_check"}, None)

    assert [c["status"] for c in ordered] == ["verified", "candidate", "superseded"]
    assert STATUS_RANK["verified"] < STATUS_RANK["candidate"] < STATUS_RANK["superseded"]
    db.close()


def test_claim_section_respects_the_budget(tmp_path):
    """An unbounded claim list used to dwarf the graph body it was appended to,
    which made --budget a promise the output did not keep."""
    db, repo = _repo(tmp_path)
    _seed_graph(repo)
    for i in range(1, 40):
        _add_claim(repo, i, "candidate")
    resolve_claims(repo, "t")

    lines, shown, total = _claim_lines(repo, {"gate_check"}, None, budget=40)

    assert total == 39
    assert shown < total                       # actually truncated
    assert sum(len(x) + 1 for x in lines) <= 40 * CHARS_PER_TOKEN
    db.close()


def test_at_least_one_claim_survives_a_tiny_budget(tmp_path):
    db, repo = _repo(tmp_path)
    _seed_graph(repo)
    _add_claim(repo, 1, "verified")
    resolve_claims(repo, "t")

    _, shown, total = _claim_lines(repo, {"gate_check"}, None, budget=1)

    assert (shown, total) == (1, 1)
    db.close()


def test_context_says_when_claims_were_cut(tmp_path):
    db, repo = _repo(tmp_path)
    _seed_graph(repo)
    for i in range(1, 30):
        _add_claim(repo, i, "candidate")
    resolve_claims(repo, "t")

    result = build_context(repo, "t", "checkScore", budget=60)

    assert "top " in result.text and " of 29)" in result.text
    assert result.claims < 29
    db.close()


def test_context_marks_claims_as_unverified_leads(tmp_path):
    """The prompt must not present a candidate claim as established fact."""
    db, repo = _repo(tmp_path)
    _seed_graph(repo)
    _add_claim(repo, 1, "candidate")
    resolve_claims(repo, "t")

    result = build_context(repo, "t", "checkScore")

    assert "passed no verification gate" in result.text
    assert "[candidate" in result.text
    db.close()


# ---------------------------------------------------------------- baseline
def test_file_mode_reads_the_same_files_the_graph_cites(tmp_path):
    db, repo = _repo(tmp_path)
    _seed_graph(repo)
    src = tmp_path / "src"
    (src / "app").mkdir(parents=True)
    (src / "app" / "gate.py").write_text("# gate\n" * 200, encoding="utf-8")
    (src / "app" / "util.py").write_text("# util\n" * 200, encoding="utf-8")

    baseline = build_file_context(repo, "t", "checkScore", src)
    graph_ctx = build_context(repo, "t", "checkScore", budget=200)

    assert set(baseline.files) == set(graph_ctx.files)   # same scope
    assert baseline.tokens > graph_ctx.tokens            # different volume
    assert "# gate" in baseline.text
    db.close()


def test_file_mode_skips_paths_that_no_longer_exist(tmp_path):
    db, repo = _repo(tmp_path)
    _seed_graph(repo)
    src = tmp_path / "src"
    (src / "app").mkdir(parents=True)
    (src / "app" / "gate.py").write_text("# gate\n", encoding="utf-8")
    # util.py deliberately absent

    baseline = build_file_context(repo, "t", "checkScore", src)

    assert "# gate" in baseline.text
    assert "### app/util.py" not in baseline.text
    db.close()
