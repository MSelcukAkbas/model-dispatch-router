"""Platform-neutral lifecycle adapter for Codex and Claude Code hooks."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .lifecycle import _corpus, _open_runtime, session_start
from .gate import evaluate_task, run_command
from .sync import sync as run_sync

# `am` fixes this in cli.py, but a console script is its own entry point and
# inherits none of that. The text this hook forwards is graphify's and the
# claim store's, which carries em-dashes and arrows; on a console using a
# legacy code page they arrive at the coding host as mojibake, inside the very
# context block the host is about to read.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):  # not a real stream
        pass


_START_HANDLER = {
    "type": "command",
    "command": "agentmind-hook start",
    "timeout": 60,
    "statusMessage": "Loading repository memory",
}
_END_HANDLER = {
    "type": "command",
    "command": "agentmind-hook end",
    "timeout": 3,
}


def _payload() -> dict[str, Any]:
    try:
        value = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def _repository(cwd: str | None) -> Path:
    start = Path(cwd or Path.cwd()).expanduser().resolve()
    try:
        result = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        return Path(result.stdout.strip()).resolve()
    except (OSError, subprocess.SubprocessError):
        return start


def _start(data: dict[str, Any]) -> None:
    source = _repository(data.get("cwd"))
    session_id = str(data.get("session_id") or "interactive-session")
    result = session_start(
        session_id,
        "orchestrator",
        "Relevant repository history, verified claims, and code context.",
        source,
    )
    if result["context"]:
        sys.stdout.write(str(result["context"]))
    _finalize_pending(source)


def _git_value(source: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(source), *args], check=True,
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _finalize_pending(source: Path) -> None:
    """Promote queued claims only after a clean commit and project check."""
    pending_dir = source / ".agent-logs"
    markers = sorted(pending_dir.glob("*.gate-pending")) if pending_dir.is_dir() else []
    if not markers or _git_value(source, "status", "--porcelain"):
        return
    config_path = source / ".model-dispatch-router.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return
    command = config.get("verifyCommand") if isinstance(config, dict) else None
    if not isinstance(command, str) or not command.strip():
        return
    head = _git_value(source, "rev-parse", "HEAD")
    if not head:
        return

    workspace, db, repo = _open_runtime(source, create=True)
    try:
        corpus = _corpus(repo, None, source)
        for marker in markers:
            task_id = marker.name.removesuffix(".gate-pending")
            check = run_command(command, source)
            if not check.ok:
                repo.add_event(
                    "gate.deferred", task_id=task_id, actor="editor-hook",
                    payload={"reason": "verification_failed", "detail": check.detail},
                )
                continue
            repo.anchor_candidate_claims(task_id, head)
            run_sync(repo, source, workspace, corpus=corpus)
            result = evaluate_task(repo, task_id, source, command=command, promote=True)
            if result.passed:
                marker.unlink(missing_ok=True)
    finally:
        db.close()


def _end(data: dict[str, Any]) -> None:
    """Record closure without a snapshot so strict end-hook deadlines are met."""
    source = _repository(data.get("cwd"))
    workspace, db, repo = _open_runtime(source, create=True)
    try:
        corpus = _corpus(repo, None, source)
        repo.add_event(
            "session.ended",
            task_id=str(data.get("session_id") or "interactive-session"),
            actor=str(data.get("platform") or "editor-hook"),
            payload={
                "corpus": corpus,
                "reason": data.get("reason") or data.get("source") or "other",
                "workspace": str(workspace),
            },
        )
    finally:
        db.close()


_AGY_MARKETPLACE: dict[str, Any] = {
    "name": "personal",
    "interface": {"displayName": "Personal"},
    "plugins": [
        {
            "name": "agentmind-model-dispatch-router",
            "source": {"source": "local", "path": "./plugins/agentmind-model-dispatch-router"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Productivity",
        }
    ],
}


def install_hooks(repository: Path | str, platform: str = "all") -> list[Path]:
    """Merge AgentMind hooks into a repository without replacing other hooks."""
    root = Path(repository).expanduser().resolve()
    targets = []
    if platform in {"all", "codex"}:
        targets.append((root / ".codex" / "hooks.json", True))
    if platform in {"all", "claude"}:
        targets.append((root / ".claude" / "settings.json", False))
    install_agy = platform in {"all", "agy"}
    if not targets and not install_agy:
        raise ValueError("platform must be all, codex, claude, or agy")

    written: list[Path] = []
    for path, is_codex in targets:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            document = {}
        if not isinstance(document, dict):
            raise ValueError(f"expected a JSON object in {path}")
        hooks = document.setdefault("hooks", {})
        if not isinstance(hooks, dict):
            raise ValueError(f"expected an object at hooks in {path}")

        start_handler = dict(_START_HANDLER)
        if is_codex:
            start_handler["additionalContextLimit"] = 4000
        additions = {
            "SessionStart": {
                "matcher": "startup|resume|clear|compact",
                "hooks": [start_handler],
            },
            "SessionEnd": {"hooks": [dict(_END_HANDLER)]},
        }
        for event, group in additions.items():
            groups = hooks.setdefault(event, [])
            if not isinstance(groups, list):
                raise ValueError(f"expected a list at hooks.{event} in {path}")
            commands = {
                handler.get("command")
                for existing in groups
                if isinstance(existing, dict)
                for handler in existing.get("hooks", [])
                if isinstance(handler, dict)
            }
            command = group["hooks"][0]["command"]
            if command not in commands:
                groups.append(group)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        written.append(path)

    # Antigravity (.agents) marketplace manifest
    if install_agy:
        agy_path = root / ".agents" / "plugins" / "marketplace.json"
        agy_path.parent.mkdir(parents=True, exist_ok=True)
        agy_path.write_text(
            json.dumps(_AGY_MARKETPLACE, indent=2) + "\n", encoding="utf-8"
        )
        written.append(agy_path)

    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentMind lifecycle hook")
    parser.add_argument("event", choices=("start", "end"))
    args = parser.parse_args()
    try:
        data = _payload()
        (_start if args.event == "start" else _end)(data)
    except Exception as exc:  # hooks must never block the host application
        print(f"AgentMind hook warning: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
