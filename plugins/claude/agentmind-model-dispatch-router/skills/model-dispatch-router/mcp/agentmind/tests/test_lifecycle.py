import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from typer.testing import CliRunner

from agentmind.cli import app
from agentmind.context import ContextResult
from agentmind.lifecycle import session_finish, session_start
from agentmind.server.main import mcp
from agentmind.store import Database, Repository, resolve_db_path
from agentmind.sync import SyncResult


def _workspace(tmp_path):
    src = tmp_path / "source"
    src.mkdir()
    root = tmp_path / "workspace"
    root.mkdir()
    db = Database(resolve_db_path(root))
    db.init_db()
    repo = Repository(db)
    repo.remember_corpus("source", src)
    db.close()
    return root, src


def test_session_start_syncs_builds_context_and_records_event(tmp_path, monkeypatch):
    root, src = _workspace(tmp_path)
    monkeypatch.setattr(
        "agentmind.lifecycle.run_sync",
        lambda *args, **kwargs: SyncResult(corpus="source", new_tasks=1),
    )
    monkeypatch.setattr(
        "agentmind.lifecycle.build_context",
        lambda *args, **kwargs: ContextResult(
            text="selected memory", tokens=5, nodes=2, edges=1,
            claims=1, files=["app.py"]
        ),
    )

    result = session_start(
        "T-1", "backend", "fix the gate", src, root=root
    )

    assert result["ok"] is True
    assert result["context"] == "selected memory"
    db = Database(resolve_db_path(root))
    db.init_db()
    event = Repository(db).list_events(task_id="T-1", limit=1)[0]
    assert event["kind"] == "dispatch.context_prepared"
    db.close()


def test_session_finish_records_event_when_sync_fails(tmp_path, monkeypatch):
    root, src = _workspace(tmp_path)

    def fail_sync(*args, **kwargs):
        raise RuntimeError("snapshot unavailable")

    monkeypatch.setattr("agentmind.lifecycle.run_sync", fail_sync)
    result = session_finish(
        "T-2", "research", src, root=root, exit_code=124, status="timeout"
    )

    assert result["ok"] is False
    assert result["status"] == "timeout"
    db = Database(resolve_db_path(root))
    db.init_db()
    event = Repository(db).list_events(task_id="T-2", limit=1)[0]
    assert event["kind"] == "dispatch.finished"
    assert "snapshot unavailable" in event["payload_json"]
    db.close()


def test_session_start_cli_bootstraps_a_repository_store(tmp_path):
    out = tmp_path / "context.md"
    result = CliRunner().invoke(
        app,
        [
            "session-start", "T-3", "--role", "backend", "--src", str(tmp_path),
            "--query", "fix", "--out", str(out), "--root", str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert out.read_text(encoding="utf-8") == ""
    assert (tmp_path / ".agentmind" / "am.db").is_file()
    db = Database(resolve_db_path(tmp_path))
    db.init_db()
    corpus = Repository(db).corpus_for_source(tmp_path)
    assert corpus is not None
    assert corpus["name"] == tmp_path.name
    db.close()


def test_mcp_registers_memory_and_lifecycle_tools():
    names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert names == {
        "memory_status_tool",
        "memory_context",
        "memory_for_file",
    }


def test_mcp_stdio_server_completes_handshake():
    async def exercise_server():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "agentmind.server.main"],
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.list_tools()
                return {tool.name for tool in result.tools}

    names = asyncio.run(exercise_server())
    assert names == {"memory_status_tool", "memory_context", "memory_for_file"}
