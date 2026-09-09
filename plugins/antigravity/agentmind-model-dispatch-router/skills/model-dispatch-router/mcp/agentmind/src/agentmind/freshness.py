"""Deterministic staleness checks for claim evidence.

A direct port of the two functions knowledge-store.js already relies on
(commitsSinceEvidence at knowledge-store.js:185, isDirty at :104). Both are
model-free git queries, and both are computed here rather than read from what
an agent reported — that distrust is the original design's deliberate choice
and is preserved: an agent claiming its evidence is clean proves nothing.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Freshness:
    commits_since: int | None   # 0 = still fresh, None = unknown
    dirty: bool
    reason: str = ""

    @property
    def label(self) -> str:
        if self.dirty:
            return "dirty"
        if self.commits_since is None:
            return "unknown"
        return "fresh" if self.commits_since == 0 else f"stale({self.commits_since})"


def _git(cwd: Path, *args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return proc.returncode, proc.stdout
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


def is_dirty(cwd: Path | str, file: str) -> bool:
    """Does the working tree hold uncommitted changes for this path?

    Empty porcelain output means the file matches HEAD, so evidence pointing at
    it really belongs to that commit. Any git failure returns True — refusing to
    be optimistic is the same call knowledge-store.js:109 makes.
    """
    code, out = _git(Path(cwd), "status", "--porcelain", "--", file)
    if code != 0:
        return True
    return bool(out.strip())


def commits_since_evidence(
    cwd: Path | str, commit_sha: str | None, files: list[str]
) -> int | None:
    """How many commits touched these files since the claim was recorded.

    0 means nothing has changed them — the claim is still anchored to the code
    it was made about. None means unanswerable (no sha, no files, or the sha is
    gone after a rebase/squash), which is not the same as fresh.
    """
    if not commit_sha or not files:
        return None
    code, out = _git(
        Path(cwd), "log", "--oneline", f"{commit_sha}..HEAD", "--", *files
    )
    if code != 0:
        return None
    return len([line for line in out.splitlines() if line.strip()])


def evaluate(
    cwd: Path | str, commit_sha: str | None, files: list[str]
) -> Freshness:
    """Combined verdict for one claim's evidence set."""
    root = Path(cwd)
    if not (root / ".git").exists():
        return Freshness(None, False, reason="not a git working tree")
    dirty = any(is_dirty(root, f) for f in files) if files else False
    return Freshness(commits_since_evidence(root, commit_sha, files), dirty)
