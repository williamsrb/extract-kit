"""product.impeccable — as-is PRODUCT.md + DESIGN.md from maps.

PRODUCT.md takes its users, jobs and capabilities from `business/BUSINESS.md`
once the `business` agent task wrote it; that task re-runs this step.

Impeccable init/document is an agent skill. This step writes the required
extract artifacts from maps so the pipeline is deterministic. `extractkit next`
still names the impeccable skill when an operator wants a richer rewrite.
"""

from __future__ import annotations

import re
from pathlib import Path

from extractkit_cli.common import load_json
from steps.core.normalize import COMPONENT_KINDS

BUSINESS = "business/BUSINESS.md"


def _load_surfaces(ctx: object) -> list[dict]:
    path: Path = ctx.rel("map/project-map.json")  # type: ignore[attr-defined]
    if not path.is_file():
        return []
    payload = load_json(path, "map/project-map.json")
    return [s for s in (payload.get("surfaces") or []) if isinstance(s, dict)]


def _product_md(ctx: object, surfaces: list[dict]) -> str:
    profile = (getattr(ctx, "profile", {}) or {}).get("name") or "unknown"
    source = getattr(ctx, "source", Path("."))
    business = _business_sections(ctx)
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
    ]
    if business:
        for title in ("Purpose and audience", "Actors"):
            lines += [f"### {title}", "", business.get(title, "").strip() or "Not stated.", ""]
        lines += ["## Capabilities", "", "From `business/BUSINESS.md`, where each one cites its evidence.", ""]
        lines += _capability_outline(business.get("Capabilities", "")) or ["None listed."]
        lines.append("")
    else:
        lines += [
            (
                "Not known yet. The `business` agent task writes `business/BUSINESS.md`; "
                "re-run `product.impeccable` afterwards to fill this section and the capabilities."
            ),
            "",
        ]
    lines += ["## Surfaces (from maps)", ""]
    if not surfaces:
        lines.append("No surfaces in `map/project-map.json`.")
    else:
        kinds: dict[str, dict[str, int]] = {}
        for surface in surfaces:
            per = kinds.setdefault(str(surface.get("kind") or "surface"), {})
            status = str(surface.get("status") or "unverified-live")
            per[status] = per.get(status, 0) + 1
        lines += ["| kind | count | status |", "|---|---|---|"]
        for kind, per in sorted(kinds.items(), key=lambda item: (-sum(item[1].values()), item[0])):
            status = ", ".join(f"{n} {s}" for s, n in sorted(per.items()))
            lines.append(f"| {kind} | {sum(per.values())} | {status} |")
        lines += ["", "Every surface, with its id and evidence, is in `map/project-map.json`."]
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


def _business_sections(ctx: object) -> dict[str, str]:
    """H2 title to body of `business/BUSINESS.md`, or {} before the `business` task ran."""
    path: Path = ctx.rel(BUSINESS)  # type: ignore[attr-defined]
    if not path.is_file():
        return {}
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            current = sections.setdefault(match.group(1), [])
        elif current is not None:
            current.append(line)
    return {title: "\n".join(body) for title, body in sections.items()}


def _capability_outline(section: str) -> list[str]:
    """The `###`/`####` headings of the Capabilities section as a nested list."""
    outline: list[str] = []
    for line in section.splitlines():
        match = re.match(r"^(#{3,6})\s+(.+?)\s*$", line)
        if match:
            outline.append(f"{'  ' * (len(match.group(1)) - 3)}- {match.group(2)}")
    return outline


def _engine_label(template: dict) -> str:
    """`thymeleaf`, or `static HTML via thymeleaf` for a file the controller renders with no engine syntax."""
    if template.get("syntax") == "none":
        return f"static HTML via {template['engine']}"
    return str(template["engine"])


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
                lines.append(f"- Template: `{template['file']}` ({_engine_label(template)})")
                for other in (surface.get("templates") or [])[1:]:
                    lines.append(f"- Template: `{other['file']}` ({_engine_label(other)})")
                if template["inputs"]:
                    lines.append("- Inputs: " + ", ".join(f"`{i['name']}`" for i in template["inputs"]))
                kids = [c["surface"] or f"{c['ref']} (unresolved)" for c in template["children"]]
                if kids:
                    lines.append("- Children: " + ", ".join(f"`{k}`" for k in kids))
            lines.append("")
    return "\n".join(lines)


def _design_json(surfaces: list[dict]) -> dict:
    return {
        "schema": "extractkit.design-sidecar/v1",
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
