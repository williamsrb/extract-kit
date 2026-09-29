"""Git metadata for the source checkout. Never writes into it."""

from __future__ import annotations

import subprocess
from pathlib import Path


def git_state(source: Path) -> tuple[str | None, bool]:
    """Return (sha or None, dirty). Missing git or no commits → (None, False)."""
    source = source.resolve()
    try:
        sha = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None, False
    try:
        porcelain = subprocess.check_output(
            ["git", "-C", str(source), "status", "--porcelain"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return sha, False
    return sha, bool(porcelain.strip())
