"""Thin wrapper over graphify's extraction pipeline.

Exists for two reasons, both learned from running it for real on Windows:

1. ``extract()`` parallelises with a process pool that re-imports the caller's
   ``__main__``. Under ``python -c``, a REPL, pytest or any embedded call that
   has no importable ``__main__``, the pool dies with BrokenProcessPool and
   graphify falls back to sequential after printing a warning. We are always
   an embedded caller, so the pool is never worth attempting.
2. It pins the shape Phase 1's resolver depends on in one place, so a change
   in graphify's output has exactly one place to break.

graphify is an optional dependency (the ``graph`` extra); importing this
module without it raises a clear error rather than an ImportError traceback.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# "L42" — graphify's source_location format. Some nodes (a bare file node with
# no symbol) carry an empty string instead, which is not an error.
LOCATION_RE = re.compile(r"^L(\d+)$")


def _require_graphify():
    try:
        from graphify.extract import collect_files, extract  # noqa: WPS433
    except ImportError as exc:  # pragma: no cover - depends on install extras
        raise RuntimeError(
            "graphify is not installed — run `uv sync --extra graph`"
        ) from exc
    return collect_files, extract


def extract_repo(root: Path | str) -> dict[str, Any]:
    """Extract nodes/edges for a directory. Sequential by design (see above)."""
    collect_files, extract = _require_graphify()
    root_path = Path(root).resolve()
    files = collect_files(root_path)
    return extract(files, root=root_path, parallel=False)


def location_line(source_location: str | None) -> int | None:
    """'L42' -> 42. Anything else (including '') -> None."""
    match = LOCATION_RE.match(str(source_location or ""))
    return int(match.group(1)) if match else None
