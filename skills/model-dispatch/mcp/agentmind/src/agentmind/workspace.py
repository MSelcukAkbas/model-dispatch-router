"""Finding the right store from wherever the user happens to be standing.

Upward search alone was not enough in practice. The two directories someone
actually works in are the workspace itself and the repo being watched, and the
second is not an ancestor of the first — so `am sync` from inside the watched
repo found nothing, which is a confusing way for a tool to behave when it
already knows about both directories.

A small user-level registry closes that. It lists workspace roots, one per
line; each workspace's own `corpora` table says which repos it watches. From
any directory the lookup is: an explicit --root, then a store above here, then
the workspace that watches this directory, then the only workspace there is.
"""

from __future__ import annotations

from pathlib import Path

from .store import DEFAULT_DB_RELPATH, find_store

REGISTRY = Path.home() / ".agentmind" / "workspaces"


def _read_registry() -> list[Path]:
    try:
        lines = REGISTRY.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    seen: list[Path] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        path = Path(line)
        # A workspace can be deleted or moved without telling us; skip rather
        # than fail, so a stale line never breaks an unrelated command.
        if (path / DEFAULT_DB_RELPATH).is_file() and path not in seen:
            seen.append(path)
    return seen


def register(workspace: Path | str) -> None:
    """Record a workspace so later commands can find it from anywhere."""
    path = Path(workspace).expanduser().resolve()
    existing = _read_registry()
    if path in existing:
        return
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    with REGISTRY.open("a", encoding="utf-8") as handle:
        handle.write(str(path) + "\n")


def _watches(workspace: Path, directory: Path) -> bool:
    import sqlite3

    db = workspace / DEFAULT_DB_RELPATH
    try:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        rows = conn.execute("SELECT source_path FROM corpora").fetchall()
        conn.close()
    except sqlite3.Error:
        return False
    for (source,) in rows:
        try:
            source_path = Path(source).resolve()
        except OSError:
            continue
        if directory == source_path or source_path in directory.parents:
            return True
    return False


def locate_store(start: Path | str | None = None) -> tuple[Path | None, str]:
    """Return (workspace root, how it was found). Root is None when nothing fits."""
    here = Path(start or Path.cwd()).expanduser().resolve()

    above = find_store(here)
    if above is not None:
        return above.parent.parent, "above the working directory"

    registered = _read_registry()
    for workspace in registered:
        if _watches(workspace, here):
            return workspace, "the workspace watching this repo"

    if len(registered) == 1:
        return registered[0], "the only registered workspace"

    return None, "not found"


def registered_workspaces() -> list[Path]:
    return _read_registry()
