"""Sidecar layout, MANIFEST.yaml writer, and the `.extract/.gitignore` contract.

Interactive runs write `<source>/.extract/<run-id>/`, self-ignored. Headless
runs write `<source>/extract/<run-id>/`: a visible folder with no `.gitignore`,
so a pipeline can publish it as an artifact as is.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path

from . import __version__
from .common import dump_yaml, timestamp, write_text
from .errors import ExtractkitError
from .sourceinfo import git_state

EXTRACT_DIRNAME = ".extract"
HEADLESS_DIRNAME = "extract"
GITIGNORE_BODY = "*\n"


def assert_output_root(root: Path) -> None:
    """Refuse an output folder that is a symlink: the sidecar would land outside the source tree."""
    if root.is_symlink():
        raise ExtractkitError(
            f"{root} is a symlink, so the sidecar would be written to {root.resolve()}, outside the source",
            "remove the link, or pass --out with a folder you mean to write to",
            code="unsafe_output",
        )


def default_out(source: Path, run_id: str | None = None, dirname: str = EXTRACT_DIRNAME) -> Path:
    root = source.resolve() / dirname
    assert_output_root(root)
    return root / (run_id or timestamp())


def _runs(source: Path, dirname: str) -> list[Path]:
    """Run folders under `<source>/<dirname>/`. A visible `extract/` only counts runs with a MANIFEST."""
    extract = source.resolve() / dirname
    if not extract.is_dir():
        return []
    runs = [p for p in extract.iterdir() if p.is_dir()]
    if dirname == HEADLESS_DIRNAME:
        runs = [p for p in runs if (p / "MANIFEST.yaml").is_file()]
    return runs


def latest_run(source: Path, dirname: str | None = None) -> Path | None:
    """The newest run by run id, under one folder or under both `.extract/` and `extract/`."""
    names = (dirname,) if dirname else (EXTRACT_DIRNAME, HEADLESS_DIRNAME)
    runs = [run for name in names for run in _runs(source, name)]
    return max(runs, key=lambda p: p.name) if runs else None


def is_headless_root(path: Path, source: Path) -> bool:
    """True for `<source>/extract/` when it holds headless runs, so scans skip it."""
    return (
        path.name == HEADLESS_DIRNAME
        and path.parent.resolve() == source.resolve()
        and bool(_runs(source, HEADLESS_DIRNAME))
    )


def out_inside_source(source: Path, out: Path) -> bool:
    """True when the sidecar sits under `<source>/.extract/` and so needs the self-ignore."""
    return out.resolve().is_relative_to(source.resolve() / EXTRACT_DIRNAME)


def ensure_self_ignore(source: Path, plan_record) -> Path:
    """Write `<source>/.extract/.gitignore` with `*`. Never touches source `.gitignore`."""
    ignore = source.resolve() / EXTRACT_DIRNAME / ".gitignore"
    if ignore.is_file() and ignore.read_text(encoding="utf-8") == GITIGNORE_BODY:
        return ignore
    plan_record(f"write {ignore} (*)")
    return ignore


def write_self_ignore(source: Path) -> Path:
    ignore = source.resolve() / EXTRACT_DIRNAME / ".gitignore"
    write_text(ignore, GITIGNORE_BODY)
    return ignore


def resolve_source(raw: str | None) -> Path:
    if not raw:
        raise ExtractkitError(
            "no --source given",
            "pass --source pointing at the legacy checkout",
            code="no_source",
        )
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise ExtractkitError(
            f"source {path} is not a directory",
            "pass --source pointing at an existing checkout",
            code="no_source",
        )
    return path


def resolve_out(source: Path, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    return default_out(source)


def tool_versions() -> dict:
    return {
        "extractkit": __version__,
        "python": platform.python_version(),
        "executable": sys.executable,
    }


def build_manifest(
    *,
    source: Path,
    profile: dict,
    skips: list[dict],
    run_id: str,
    maps: dict | None = None,
    exclude: list[str] | None = None,
) -> dict:
    sha, dirty = git_state(source)
    return {
        "schema": "99x.extract.manifest/v1",
        "run_id": run_id,
        "source": {
            "path": str(source.resolve()),
            "sha": sha,
            "dirty": dirty,
            "profile": profile.get("name"),
            "lineage": list(profile.get("lineage") or []),
            "tools": tool_versions(),
        },
        "maps": maps or {},
        "exclude": list(exclude or []),
        "context": {"layers": list(profile.get("overlays") or [])},
        "skips": skips,
    }


def manifest_text(payload: dict) -> str:
    return dump_yaml(payload)
