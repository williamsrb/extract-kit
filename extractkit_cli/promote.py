"""`extractkit promote` — copy chosen extract files into the source tree."""

from __future__ import annotations

import shutil
import subprocess
from argparse import Namespace
from pathlib import Path

from . import agent_tasks, guide
from . import result as _result
from .common import Plan, write_text
from .errors import ExtractkitError
from .outtree import resolve_source
from .progress import resolve_out_dir

# Extract-relative -> source-relative. Constitution path is what Spec Kit reads.
PROMOTIONS: tuple[tuple[str, str], ...] = (
    ("spec-kit/constitution.md", ".specify/memory/constitution.md"),
    ("product/PRODUCT.md", "PRODUCT.md"),
    ("design/DESIGN.md", "DESIGN.md"),
    ("design/design.json", ".impeccable/design.json"),
)
NOT_IN_GIT = "not in a git work tree"


def _spec_promotions(out: Path) -> list[tuple[Path, Path]]:
    specs = out / "spec-kit" / "specs"
    rows: list[tuple[Path, Path]] = []
    if not specs.is_dir():
        return rows
    for spec in specs.glob("*/spec.md"):
        rel = spec.relative_to(out / "spec-kit" / "specs")
        rows.append((spec, Path("specs") / rel))
    return rows


def cmd_promote(args: Namespace) -> int:
    source = resolve_source(getattr(args, "source", None))
    out = resolve_out_dir(args, source)
    plan = Plan()
    copies: list[tuple[Path, Path]] = []
    for src_rel, dest_rel in PROMOTIONS:
        src = out / src_rel
        if src.is_file():
            copies.append((src, source / dest_rel))
    copies.extend((src, source / dest) for src, dest in _spec_promotions(out))
    copies.extend((src, source / dest) for src, dest in agent_tasks.promotions(out))
    if not copies:
        raise ExtractkitError(
            f"nothing to promote from {out}",
            "run extractkit through spec.kit, then promote that sidecar",
        )
    through = [dest.relative_to(source).as_posix() for _src, dest in copies if _through_symlink(source, dest)]
    if through:
        raise ExtractkitError(
            f"promote would write through a symlink: {', '.join(through)}",
            "replace the link with a real file or folder; --force does not allow this",
            code="promote_refused",
        )
    if not getattr(args, "force", False):
        blocked = _blocked(source, [dest for _src, dest in copies])
        if blocked:
            lines = [
                f"  {dest.relative_to(source).as_posix()}  ({reason})"
                for dest, reason in blocked
            ]
            raise ExtractkitError(
                f"promote would overwrite {len(blocked)} file(s) git cannot restore:\n"
                + "\n".join(lines),
                "commit or stash them, or pass --force to overwrite",
                fix_args={"--force": None},
                code="promote_refused",
            )
    for src, dest in copies:
        plan.record(f"promote {src} -> {dest}")
        write_text(dest, src.read_text(encoding="utf-8"))
    style = guide.style_for()
    body = guide.render_promote(
        [guide.Action(step, text) for step, text in plan.entries],
        source,
        verbose=bool(getattr(args, "verbose", False)),
        style=style,
    )
    suggestion = guide.next_for("promote", "done", args, source=source)
    _result.note_run(source=source, sidecar=out, wrote=plan.entries)
    guide.emit(body, guide.render_next(suggestion, style))
    return 0


def _through_symlink(source: Path, dest: Path) -> bool:
    """True when `dest`, or a folder above it inside the source, is a symlink."""
    here = source
    for part in dest.relative_to(source).parts:
        here = here / part
        if here.is_symlink():
            return True
    return False


def _blocked(source: Path, dests: list[Path]) -> list[tuple[Path, str]]:
    """Existing destinations git cannot restore, with the reason for each."""
    existing = [dest for dest in dests if dest.exists()]
    if not existing:
        return []
    git = shutil.which("git")
    top = _toplevel(git, source) if git else None
    if git is None or top is None:
        return [(dest, NOT_IN_GIT) for dest in existing]
    rels = [dest.resolve().relative_to(top).as_posix() for dest in existing]
    result = subprocess.run(
        [git, "-C", str(top), "status", "--porcelain=v1", "-z",
         "--ignored=matching", "--untracked-files=all", "--", *rels],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return [(dest, NOT_IN_GIT) for dest in existing]
    codes = _porcelain_codes(result.stdout)
    blocked: list[tuple[Path, str]] = []
    for dest, rel in zip(existing, rels):
        code = codes.get(rel) or next(
            (c for path, c in codes.items() if path.endswith("/") and rel.startswith(path)),
            None,
        )
        if code is None:
            continue
        reason = {"??": "untracked", "!!": "ignored"}.get(code, "modified")
        blocked.append((dest, reason))
    return blocked


def _toplevel(git: str, source: Path) -> Path | None:
    result = subprocess.run(
        [git, "-C", str(source), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip()).resolve()


def _porcelain_codes(raw: str) -> dict[str, str]:
    codes: dict[str, str] = {}
    entries = raw.split("\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        codes[path] = code
        if code[0] in "RC":
            # Renames and copies carry the original path as the next entry.
            index += 1
    return codes
