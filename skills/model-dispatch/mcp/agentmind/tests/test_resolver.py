"""The join: claim evidence (file, line) -> graph node."""

import json

import pytest

from agentmind.resolver import FileIndex, normalise_edges, normalise_nodes, resolve_claims
from agentmind.store import Database, Repository, resolve_db_path


class Row(dict):
    """Stand-in for sqlite3.Row — indexable by column name."""


def _rows(*triples):
    return [Row(node_id=n, source_line=line, source_file=f) for n, line, f in triples]


def _repo(tmp_path):
    db = Database(resolve_db_path(tmp_path))
    db.init_db()
    return db, Repository(db)


# ------------------------------------------------------------- FileIndex
def test_lookup_picks_the_symbol_the_line_sits_inside():
    index = FileIndex(_rows(("mod", None, "a.py"), ("f_a", 10, "a.py"), ("f_b", 40, "a.py")))
    assert index.lookup(10) == "f_a"
    assert index.lookup(25) == "f_a"     # inside f_a, before f_b
    assert index.lookup(40) == "f_b"
    assert index.lookup(999) == "f_b"    # past the last symbol


def test_lookup_above_the_first_symbol_falls_back_to_the_file_node():
    index = FileIndex(_rows(("mod", None, "a.py"), ("f_a", 10, "a.py")))
    assert index.lookup(3) == "mod"      # imports region, above any symbol
    assert index.lookup(None) == "mod"   # evidence with no line at all


def test_lookup_without_a_file_node_falls_back_to_the_first_symbol():
    index = FileIndex(_rows(("f_a", 10, "a.py"), ("f_b", 40, "a.py")))
    assert index.lookup(1) == "f_a"


def test_empty_index_is_falsy_and_resolves_to_nothing():
    index = FileIndex([])
    assert not index
    assert index.lookup(5) is None


# ------------------------------------------------------- normalisation
def test_normalise_parses_source_location_to_an_int():
    nodes = normalise_nodes([
        {"id": "a", "label": "A", "source_file": "a.py", "source_location": "L6"},
        {"id": "b", "label": "B", "source_file": "a.py", "source_location": ""},
    ])
    assert nodes[0]["source_line"] == 6
    assert nodes[1]["source_line"] is None


def test_normalise_edges_keeps_confidence():
    edges = normalise_edges([
        {"source": "a", "target": "b", "relation": "calls",
         "confidence": "EXTRACTED", "source_location": "L3"},
    ])
    assert edges[0]["confidence"] == "EXTRACTED"
    assert edges[0]["source_line"] == 3


# ---------------------------------------------------------- resolution
def _seed(repo, evidence, claim_id=1):
    repo.upsert_claim({
        "id": claim_id, "topic": "t", "category": "behavior", "claim": "c",
        "created_at": "2026-09-01T00:00:00+00:00",
        "evidence_json": json.dumps(evidence),
    })


def test_resolve_binds_evidence_to_the_enclosing_symbol(tmp_path):
    db, repo = _repo(tmp_path)
    repo.replace_graph("r", normalise_nodes([
        {"id": "mod", "source_file": "app/gate.py", "source_location": ""},
        {"id": "check", "source_file": "app/gate.py", "source_location": "L10"},
    ]), [])
    _seed(repo, [{"file": "app/gate.py", "line": 14}])

    result = resolve_claims(repo, "r")

    assert result.resolved == 1 and result.dangling == 0
    assert repo.claims_for_file("app/gate.py")[0]["graph_node_id"] == "check"
    db.close()


def test_missing_file_and_unparsed_file_are_told_apart(tmp_path):
    """The distinction the reason column exists for: code drift vs tooling gap."""
    db, repo = _repo(tmp_path)
    src = tmp_path / "src"
    (src / "app").mkdir(parents=True)
    (src / "app" / "config.yaml").write_text("a: 1", encoding="utf-8")

    repo.replace_graph("r", [], [])          # nothing extracted at all
    _seed(repo, [{"file": "app/config.yaml", "line": 2}], claim_id=1)
    _seed(repo, [{"file": "app/deleted.js", "line": 5}], claim_id=2)

    result = resolve_claims(repo, "r", source_root=src)

    assert result.by_reason == {"not_extracted": 1, "file_missing": 1}
    assert {r["file"] for r in repo.dangling_refs(reason="file_missing")} == {"app/deleted.js"}
    db.close()


def test_without_a_source_root_misses_are_merely_unresolved(tmp_path):
    db, repo = _repo(tmp_path)
    repo.replace_graph("r", [], [])
    _seed(repo, [{"file": "app/whatever.js", "line": 1}])

    result = resolve_claims(repo, "r")

    assert result.by_reason == {"unresolved": 1}
    db.close()


def test_claims_without_evidence_are_counted_not_dropped(tmp_path):
    db, repo = _repo(tmp_path)
    repo.replace_graph("r", [], [])
    _seed(repo, [], claim_id=1)
    _seed(repo, [{"file": "a.py", "line": 1}], claim_id=2)

    result = resolve_claims(repo, "r")

    assert result.claims_without_evidence == 1
    assert result.refs == 1
    db.close()


def test_resolve_is_idempotent(tmp_path):
    db, repo = _repo(tmp_path)
    repo.replace_graph("r", normalise_nodes([
        {"id": "mod", "source_file": "a.py", "source_location": "L1"},
    ]), [])
    _seed(repo, [{"file": "a.py", "line": 5}])

    resolve_claims(repo, "r")
    resolve_claims(repo, "r")

    assert repo.resolution_summary()["total"] == 1
    db.close()


def test_rebuilding_a_graph_drops_the_old_nodes(tmp_path):
    """A rebuild must not leave nodes for code that no longer exists."""
    db, repo = _repo(tmp_path)
    repo.replace_graph("r", normalise_nodes([
        {"id": "old", "source_file": "gone.py", "source_location": "L1"},
    ]), [])
    repo.replace_graph("r", normalise_nodes([
        {"id": "new", "source_file": "here.py", "source_location": "L1"},
    ]), [])

    assert repo.nodes_for_file("r", "gone.py") == []
    assert repo.count_graph("r")[0] == 1
    db.close()


def test_graphs_of_different_repos_do_not_collide(tmp_path):
    db, repo = _repo(tmp_path)
    repo.replace_graph("a", normalise_nodes([
        {"id": "x", "source_file": "same.py", "source_location": "L1"}]), [])
    repo.replace_graph("b", normalise_nodes([
        {"id": "y", "source_file": "same.py", "source_location": "L1"}]), [])

    assert repo.nodes_for_file("a", "same.py")[0]["node_id"] == "x"
    assert repo.nodes_for_file("b", "same.py")[0]["node_id"] == "y"
    db.close()
