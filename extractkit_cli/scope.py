"""Which source paths a run reads: built-in skip dirs plus operator excludes.

An exclude is a source-relative folder or file (`prototype`, `apps/old`). It
comes from the profile's `exclude:` list, from `--exclude`, and from the
MANIFEST of the sidecar being continued, so a resumed run reads the same tree.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path, PurePosixPath

from .errors import ExtractkitError

SKIP_DIRS = frozenset({
    "node_modules", "vendor", "dist", "build", "target", ".extract", ".git", "graft",
    "graphify-out", ".serena", "__pycache__", ".gradle",
})


def normalize(raw: Iterable[object]) -> list[str]:
    """Sorted, deduplicated POSIX paths relative to the source root."""
    found: set[str] = set()
    for item in raw:
        text = str(item).strip().replace("\\", "/")
        path = PurePosixPath(text)
        if not text or path.is_absolute() or ".." in path.parts:
            raise ExtractkitError(
                f"exclude {item!r} is not a path relative to the source",
                "name a folder or file under --source, for example `--exclude prototype`",
            )
        value = path.as_posix()
        if value != ".":
            found.add(value)
    return sorted(found)


def is_excluded(rel: str, exclude: Iterable[str]) -> bool:
    """True when `rel` is an exclude or sits under one."""
    return any(rel == item or rel.startswith(f"{item}/") for item in exclude)


def iter_files(source: Path, exclude: Iterable[str] = ()) -> Iterator[Path]:
    """Files under `source` in a stable order, without symlinks, skip dirs or excludes."""
    excluded = tuple(exclude)
    stack = [source]
    while stack:
        directory = stack.pop()
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            if excluded and is_excluded(entry.relative_to(source).as_posix(), excluded):
                continue
            if entry.is_dir():
                if entry.name not in SKIP_DIRS:
                    stack.append(entry)
            elif entry.is_file():
                yield entry


def kept(source: Path, paths: Iterable[Path], exclude: Iterable[str]) -> list[Path]:
    """`paths` without the ones under an exclude, for globs that do not walk."""
    excluded = tuple(exclude)
    return [p for p in paths if not is_excluded(p.relative_to(source).as_posix(), excluded)]


def of(ctx: object) -> list[str]:
    """The run's excludes; empty for a context built before excludes existed."""
    return list(getattr(ctx, "exclude", None) or [])
