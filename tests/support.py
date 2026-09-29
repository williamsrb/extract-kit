"""Shared test helpers. Copy fixtures to a temp dir so sidecars never hit the kit."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "tests" / "fixtures" / "enonic-mini"
CLI = [sys.executable, str(REPO / "extractkit")]


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*CLI, *args],
        cwd=cwd or REPO,
        capture_output=True,
        text=True,
        check=False,
    )


def copy_fixture(parent: Path) -> Path:
    dest = parent / "legacy"
    shutil.copytree(FIXTURE, dest)
    return dest


def git_init(path: Path) -> None:
    subprocess.run(
        ["git", "init"], cwd=path, check=True, capture_output=True, text=True,
    )
    subprocess.run(
        ["git", "add", "."], cwd=path, check=True, capture_output=True, text=True,
    )
    subprocess.run(
        [
            "git", "-c", "user.email=kit@example.test", "-c", "user.name=kit",
            "commit", "-m", "init",
        ],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )


def porcelain(path: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def sidecar_run_dir(source: Path) -> Path:
    extract = source / ".extract"
    runs = [p for p in extract.iterdir() if p.is_dir() and p.name != ".gitignore"]
    if not runs:
        raise AssertionError(f"no run directory under {extract}")
    return max(runs, key=lambda p: p.name)


STATIC_UNTIL = ("--until", "inventory.integrations")
