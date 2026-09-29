"""docs.synthesize — technical vs guide markdown from maps."""

from __future__ import annotations

from pathlib import Path

from extractkit_cli.common import load_json


def _surfaces(ctx: object) -> list[dict]:
    path: Path = ctx.rel("map/project-map.json")  # type: ignore[attr-defined]
    if not path.is_file():
        return []
    payload = load_json(path, "map/project-map.json")
    return [s for s in (payload.get("surfaces") or []) if isinstance(s, dict)]


def _contexts(ctx: object) -> list[dict]:
    path: Path = ctx.rel("map/bounded-contexts.json")  # type: ignore[attr-defined]
    if not path.is_file():
        return []
    payload = load_json(path, "map/bounded-contexts.json")
    return [c for c in (payload.get("contexts") or []) if isinstance(c, dict)]


class SynthesizeStep:
    id = "docs.synthesize"
    requires = ("map/project-map.json",)
    produces = ("docs/technical/overview.md", "docs/guide/overview.md")
    required = True

    def plan(self, _ctx: object) -> list[str]:
        return [
            "write docs/technical/overview.md from maps",
            "write docs/guide/overview.md for operators",
        ]

    def run(self, ctx: object) -> None:
        surfaces = _surfaces(ctx)
        contexts = _contexts(ctx)
        tech = [
            "# Technical overview (as-is)",
            "",
            "Rendered from `map/*.json`. Not a port plan.",
            "",
            "## Surfaces",
            "",
        ]
        for surface in surfaces:
            ident = surface.get("id") or ""
            kind = surface.get("kind") or ""
            status = surface.get("status") or ""
            entry = surface.get("entry") or ""
            tech.append(f"- `{ident}` ({kind}, `{status}`) `{entry}`")
        tech.append("")
        tech.append("## Bounded contexts")
        tech.append("")
        if not contexts:
            tech.append("Run `maps.merge` to emit `map/bounded-contexts.json`.")
        else:
            for context in contexts:
                tech.append(
                    f"- `{context.get('id')}` — {context.get('title')} "
                    f"({len(context.get('surfaces') or [])} surfaces)"
                )
        tech.append("")
        guide = [
            "# Operator guide",
            "",
            "How to read this extract.",
            "",
            "1. `map/project-map.json` is the stack-agnostic surface list.",
            "2. `inventory/merge-report.md` explains live vs dead vs unverified.",
            "3. `integrations/openapi.yaml` is metadata; do not Try-it-out against production.",
            (
                "4. `spec-kit/` describes the product as-is. `promote` copies constitution "
                "to `.specify/memory/constitution.md`."
            ),
            "",
        ]
        ctx.write_text("docs/technical/overview.md", "\n".join(tech))  # type: ignore[attr-defined]
        ctx.write_text("docs/guide/overview.md", "\n".join(guide))  # type: ignore[attr-defined]

    def check(self, _ctx: object) -> list[str]:
        return []
