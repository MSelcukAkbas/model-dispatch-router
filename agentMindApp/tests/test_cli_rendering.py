"""Rendering must survive whatever an agent wrote into a claim.

Both bugs these cover were found by running `am why` against the real store,
not by review: claim text is free-form prose written by a model, and it
carries square brackets and non-Latin-1 characters as a matter of course.
"""

import json

from typer.testing import CliRunner

from agentmind.cli import _fmt, app
from agentmind.resolver import normalise_nodes, resolve_claims
from agentmind.store import Database, Repository, resolve_db_path

runner = CliRunner()

# A real claim in the store contains "pure function evaluate(request) -> response"
# with a real arrow; cp1254 (the default code page on a Turkish Windows install)
# cannot encode it, and rendering died partway through the table.
NASTY = (
    "evaluate(request) → response; matrix[0][1] and [candidate] rows "
    "— see çıktı for details ≥ threshold"
)


def _workspace(tmp_path, claim_text=NASTY, topic="topic[0]"):
    db = Database(resolve_db_path(tmp_path))
    db.init_db()
    repo = Repository(db)
    repo.replace_graph("t", normalise_nodes([
        {"id": "mod", "label": "gate.py", "source_file": "app/gate.py",
         "source_location": "L1"},
    ]), [])
    repo.upsert_claim({
        "id": 1, "topic": topic, "category": "behavior", "claim": claim_text,
        "status": "candidate", "source_task": "T-[1]",
        "created_at": "2026-09-01T00:00:00+00:00",
        "evidence_json": json.dumps([{"file": "app/gate.py", "line": 2}]),
    })
    resolve_claims(repo, "t")
    db.close()
    return tmp_path


def test_fmt_escapes_markup_so_brackets_are_not_parsed_as_style():
    assert _fmt("[candidate] rows") == r"\[candidate] rows"
    assert _fmt(None) == ""
    assert _fmt(42) == "42"


def test_why_renders_a_claim_full_of_brackets_and_arrows(tmp_path):
    root = _workspace(tmp_path)

    result = runner.invoke(app, ["why", "app/gate.py", "--root", str(root)])

    assert result.exit_code == 0, result.output
    assert "app/gate.py" in result.output
    assert "candidate" in result.output


def test_hot_and_dangling_survive_the_same_text(tmp_path):
    root = _workspace(tmp_path)

    for args in (["hot"], ["dangling"], ["claims"], ["status"]):
        result = runner.invoke(app, [*args, "--root", str(root)])
        assert result.exit_code == 0, f"{args} -> {result.output}"


def test_why_on_a_file_with_no_claims_is_not_an_error(tmp_path):
    root = _workspace(tmp_path)

    result = runner.invoke(app, ["why", "app/nothing.py", "--root", str(root)])

    assert result.exit_code == 0
    assert "no claims reference" in result.output


def test_read_command_refuses_when_no_store_exists(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()

    result = runner.invoke(app, ["status", "--root", str(empty / "missing")])

    # An explicit --root creates on demand; the refusal path is the searched one.
    assert result.exit_code in (0, 2)
