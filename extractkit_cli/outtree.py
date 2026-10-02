"""Sidecar layout, MANIFEST.yaml writer, and the `.extract/.gitignore` contract."""

from __future__ import annotations

import platform
import sys
from pathlib import Path

from . import __version__
from .common import dump_yaml, timestamp, write_text
from .errors import ExtractkitError
from .sourceinfo import git_state

EXTRACT_DIRNAME = ".extract"
GITIGNORE_BODY = "*\n"


def default_out(source: Path, run_id: str | None = None) -> Path:
    return source.resolve() / EXTRACT_DIRNAME / (run_id or timestamp())


def latest_run(source: Path) -> Path | None:
    extract = source.resolve() / EXTRACT_DIRNAME
    if not extract.is_dir():
        return None
    runs = [p for p in extract.iterdir() if p.is_dir()]
    if not runs:
        return None
    return max(runs, key=lambda p: p.name)


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
        )
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise ExtractkitError(
            f"source {path} is not a directory",
            "pass --source pointing at an existing checkout",
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
        "skips": skips,
    }


def manifest_text(payload: dict) -> str:
    return dump_yaml(payload)
