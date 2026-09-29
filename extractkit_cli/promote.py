"""`extractkit promote` — copy chosen extract files into the source tree."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

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
    apply = bool(getattr(args, "apply", False))
    plan = Plan(apply)
    copies: list[tuple[Path, Path]] = []
    for src_rel, dest_rel in PROMOTIONS:
        src = out / src_rel
        if src.is_file():
            copies.append((src, source / dest_rel))
    copies.extend((src, source / dest) for src, dest in _spec_promotions(out))
    if not copies:
        raise ExtractkitError(
            f"nothing to promote from {out}",
            "run extractkit through spec.kit --apply, then promote that sidecar",
        )
    for src, dest in copies:
        plan.record(f"promote {src} -> {dest}")
        if apply:
            write_text(dest, src.read_text(encoding="utf-8"))
    return plan.report(f"promote -> {source}")
