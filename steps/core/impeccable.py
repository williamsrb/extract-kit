"""product.impeccable — as-is PRODUCT.md + DESIGN.md from maps.

Impeccable init/document is an agent skill. This step writes the required
extract artifacts from maps so the pipeline is deterministic. `extractkit next`
still names the impeccable skill when an operator wants a richer rewrite.
"""

from __future__ import annotations

from pathlib import Path

from extractkit_cli.common import load_json
from steps.core.normalize import COMPONENT_KINDS


def _load_surfaces(ctx: object) -> list[dict]:
    path: Path = ctx.rel("map/project-map.json")  # type: ignore[attr-defined]
    if not path.is_file():
        return []
    payload = load_json(path, "map/project-map.json")
    return [s for s in (payload.get("surfaces") or []) if isinstance(s, dict)]


def _product_md(ctx: object, surfaces: list[dict]) -> str:
    profile = (getattr(ctx, "profile", {}) or {}).get("name") or "unknown"
    source = getattr(ctx, "source", Path("."))
    lines = [
        "# PRODUCT (as-is)",
        "",
        "Extracted from the legacy checkout. This is not an XP8 or React4XP port.",
        "",
        f"- Profile: `{profile}`",
        f"- Source: `{source}`",
        "",
        "## Users and jobs",
        "",
        (
            "Not interviewed. Surfaces below are inferred from static inventory "
            "and optional runtime survey."
        ),
        "",
        "## Capabilities (from maps)",
        "",
    ]
    if not surfaces:
        lines.append("No surfaces in `map/project-map.json`.")
    else:
        for surface in surfaces:
            ident = surface.get("id") or ""
            kind = surface.get("kind") or ""
            status = surface.get("status") or "unverified-live"
            lines.append(f"- `{ident}` ({kind}) — status `{status}`")
    lines.append("")
    lines.append("## Platform")
    lines.append("")
    lines.append("web")
    lines.append("")
    harvest = ctx.rel("docs/harvest/INDEX.md")  # type: ignore[attr-defined]
    if harvest.is_file():
        lines.append("## Source docs harvested")
        lines.append("")
        lines.append("See `docs/harvest/INDEX.md`.")
        lines.append("")
    return "\n".join(lines)


def _design_md(surfaces: list[dict]) -> str:
    components = [
        s for s in surfaces
        if s.get("kind") in COMPONENT_KINDS
    ]
    lines = [
        "# DESIGN (as-is)",
        "",
        "Incumbent structure from the extract maps. No replacement visual world.",
        "",
        "## Components",
        "",
    ]
    if not components:
        lines.append("No page, layout, part, macro or template component surfaces.")
    else:
        for surface in components:
            ident = surface.get("id") or ""
            entry = surface.get("entry") or ""
            composition = surface.get("composition") or []
            lines.append(f"### `{ident}`")
            lines.append("")
            lines.append(f"- Entry: `{entry}`")
            if composition:
                lines.append("- Template order: " + ", ".join(f"`{c}`" for c in composition))
            template = surface.get("template")
            if template:
                lines.append(f"- Template: `{template['file']}` ({template['engine']})")
                if template["inputs"]:
                    lines.append("- Inputs: " + ", ".join(f"`{i['name']}`" for i in template["inputs"]))
                kids = [c["surface"] or f"{c['ref']} (unresolved)" for c in template["children"]]
                if kids:
                    lines.append("- Children: " + ", ".join(f"`{k}`" for k in kids))
            lines.append("")
    return "\n".join(lines)


def _design_json(surfaces: list[dict]) -> dict:
    return {
        "schema": "99x.extract.design-sidecar/v1",
        "mode": "as-is",
        "components": [
            {
                "id": s.get("id"),
                "kind": s.get("kind"),
                "entry": s.get("entry"),
                "status": s.get("status"),
            }
            for s in surfaces
            if s.get("kind") in COMPONENT_KINDS
        ],
    }


class ImpeccableStep:
    id = "product.impeccable"
    requires = ("map/project-map.json",)
    produces = ("product/PRODUCT.md", "design/DESIGN.md", "design/design.json")
    required = True

    def plan(self, _ctx: object) -> list[str]:
        return [
            "write product/PRODUCT.md from maps (as-is; impeccable init is optional)",
            "write design/DESIGN.md + design/design.json from component map",
        ]

    def run(self, ctx: object) -> None:
        surfaces = _load_surfaces(ctx)
        ctx.write_text("product/PRODUCT.md", _product_md(ctx, surfaces))  # type: ignore[attr-defined]
        ctx.write_text("design/DESIGN.md", _design_md(surfaces))  # type: ignore[attr-defined]
        ctx.write_json("design/design.json", _design_json(surfaces))  # type: ignore[attr-defined]

    def check(self, _ctx: object) -> list[str]:
        return []
