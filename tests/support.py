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


def build_sidecar(parent: Path) -> tuple[Path, Path]:
    """Fixture checkout plus a sidecar run through spec.kit (no CMS)."""
    source = copy_fixture(parent)
    for args in (
        ("--until", "inventory.integrations"),
        ("--from", "maps.merge", "--until", "spec.kit"),
    ):
        extra = ("--out", str(sidecar_run_dir(source))) if "--from" in args else ()
        result = run("run", "--profile", "enonic", "--source", str(source), *extra, *args)
        if result.returncode != 0:
            raise AssertionError(result.stderr + result.stdout)
    return source, sidecar_run_dir(source)


BUSINESS_SECTIONS = (
    "Purpose and audience", "Actors", "Capabilities", "Business flow",
    "Business rules by capability", "Glossary", "Integrations", "Open questions",
)


def valid_business() -> str:
    """A BUSINESS.md that passes `check` on the fixture sidecar."""
    return """# Business flow

## Purpose and audience

The mini site serves articles to visitors.

## Actors

- Visitor: reads pages.
- Editor: writes articles _(inferred)_.

Evidence: `com.example.mini:content-type:mini-article`

## Capabilities

### Article publishing

Editors maintain articles with titles and related links.

Evidence: `com.example.mini:content-type:mini-article`, `content`

### Page rendering

Pages are assembled from parts and layouts.

Evidence: `com.example.mini:part:mini-part`

## Business flow

A visitor opens a page (`presentation`), which renders parts _(inferred)_.

Evidence: `xp/src/main/resources/site/site.xml:1`

## Business rules by capability

No named business rules were extracted.

## Glossary

- Article: the mini-article content type.

## Integrations

None found.

## Open questions

- Which editors publish articles? _(inferred)_

Evidence: `com.example.mini:site:site`
"""
