"""enonic.docs — harvest existing source docs into the extract tree."""

from __future__ import annotations

import os
from pathlib import Path

SKIP_DIR_NAMES = {
    ".git",
    ".extract",
    "node_modules",
    "graft",
    "graphify-out",
    "__pycache__",
    ".gradle",
    "build",
}


def _iter_source_docs(source: Path) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(source, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
        root = Path(dirpath)
        rel_root = root.relative_to(source)
        for name in filenames:
            path = root / name
            lowered = name.lower()
            if lowered in {"readme.md", "readme", "product.md", "design.md"}:
                found.append(path)
                continue
            if (
                rel_root.parts
                and rel_root.parts[0] in {"docs", "documentation"}
                and path.suffix.lower() in {".md", ".txt", ".adoc"}
            ):
                found.append(path)
    return sorted(found)


class EnonicDocsStep:
    id = "enonic.docs"
    requires: tuple[str, ...] = ()
    produces = ("docs/harvest/INDEX.md",)
    required = True

    def plan(self, ctx: object) -> list[str]:
        source: Path = ctx.source  # type: ignore[attr-defined]
        n = len(_iter_source_docs(source))
        return [f"harvest {n} source doc file(s) into docs/harvest/"]

    def run(self, ctx: object) -> None:
        source: Path = ctx.source  # type: ignore[attr-defined]
        files = _iter_source_docs(source)
        index_lines = [
            "# Harvested source docs",
            "",
            "Copied as input for PRODUCT/DESIGN and docs.synthesize. As-is.",
            "",
        ]
        if not files:
            index_lines.append("No README or docs/ files found in the source checkout.")
            ctx.record_skip(  # type: ignore[attr-defined]
                self.id,
                f"no harvestable docs under {source}",
                "add a README.md or docs/ in the source, or continue; synthesize uses maps",
            )
        else:
            for path in files:
                rel = path.relative_to(source).as_posix()
                body = path.read_text(encoding="utf-8", errors="replace")
                ctx.write_text(f"docs/harvest/{rel}", body)  # type: ignore[attr-defined]
                index_lines.append(f"- `{rel}`")
        index_lines.append("")
        ctx.write_text("docs/harvest/INDEX.md", "\n".join(index_lines))  # type: ignore[attr-defined]

    def check(self, _ctx: object) -> list[str]:
        return []
