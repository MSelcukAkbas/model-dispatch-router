"""Locks the graphify output shape Phase 1's join depends on.

The whole overlay-graph design rests on one claim: knowledge.db's
``evidence[{file, line}]`` and a graphify node's ``{source_file,
source_location}`` are the same coordinate space. That is an assumption about
someone else's pinned dependency, so it is asserted here rather than trusted —
if an upgrade changes the shape, this fails instead of the resolver quietly
emitting dangling refs.
"""

import pytest

from agentmind.codegraph import location_line

graphify = pytest.importorskip("graphify", reason="needs the `graph` extra")

from agentmind.codegraph import extract_repo  # noqa: E402

FIXTURE = '''\
class Gate:
    """A tiny module with one class and one function."""

    def check(self, score):
        return score > 85


def run(gate, score):
    return gate.check(score)
'''


@pytest.fixture(scope="module")
def extraction(tmp_path_factory):
    root = tmp_path_factory.mktemp("repo")
    (root / "app").mkdir()
    (root / "app" / "gate.py").write_text(FIXTURE, encoding="utf-8")
    return extract_repo(root)


def test_extraction_has_nodes_and_edges(extraction):
    assert extraction["nodes"], "no nodes extracted from the fixture"
    assert "edges" in extraction


def test_every_node_carries_the_join_keys(extraction):
    for node in extraction["nodes"]:
        assert "id" in node and node["id"]
        assert "source_file" in node
        assert "source_location" in node


def test_source_file_is_repo_relative_with_forward_slashes(extraction):
    """The resolver compares these against evidence[].file verbatim."""
    for node in extraction["nodes"]:
        path = node["source_file"]
        assert not path.startswith("/"), path
        assert "\\" not in path, path
        assert ":" not in path, path          # no drive letter leaked in
    assert any(n["source_file"] == "app/gate.py" for n in extraction["nodes"])


def test_source_location_is_L_prefixed_or_empty(extraction):
    for node in extraction["nodes"]:
        loc = node["source_location"]
        assert loc == "" or location_line(loc) is not None, loc
    # at least one real line anchor, otherwise the join has nothing to bind to
    assert any(location_line(n["source_location"]) for n in extraction["nodes"])


def test_edges_carry_a_known_confidence_label(extraction):
    """These five labels are the provenance vocabulary the kernel extends."""
    allowed = {"EXTRACTED", "INFERRED", "AMBIGUOUS"}
    for edge in extraction["edges"]:
        assert edge["confidence"] in allowed, edge["confidence"]


def test_location_line_parsing():
    assert location_line("L42") == 42
    assert location_line("L1") == 1
    assert location_line("") is None
    assert location_line(None) is None
    assert location_line("42") is None
    assert location_line("L42-L50") is None
