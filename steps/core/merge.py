"""maps.merge — runtime beats static; round 2 beats round 1; split contexts."""

from __future__ import annotations

from pathlib import Path

from extractkit_cli.common import load_json
from extractkit_cli.schema import validate
from steps.core.normalize import (
    COMPONENT_KINDS,
    MODEL_KINDS,
    ROUTE_KINDS,
    NormalizeStep,
)

OBSERVABLE_KINDS = COMPONENT_KINDS
CONTEXT_BUCKETS = (
    ("presentation", "Presentation", COMPONENT_KINDS),
    ("content", "Content model", MODEL_KINDS),
    ("routing", "Routing and jobs", ROUTE_KINDS | {"mapping"}),
)


def _descriptor_key(surface: dict) -> str:
    stack = (surface.get("stackRef") or {}).get("enonic") or {}
    app = stack.get("app") or ""
    name = (surface.get("id") or "").rsplit(":", 1)[-1]
    if app and name:
        return f"{app}:{name}"
    ident = surface.get("id") or ""
    parts = ident.split(":")
    if len(parts) >= 3:
        return f"{parts[0]}:{parts[-1]}"
    return ident


def _load_runtime(ctx: object) -> dict | None:
    path: Path = ctx.rel("inventory/runtime.json")  # type: ignore[attr-defined]
    if not path.is_file():
        return None
    return load_json(path, "inventory/runtime.json")


def _ensure_maps(ctx: object) -> dict:
    path: Path = ctx.rel("map/project-map.json")  # type: ignore[attr-defined]
    if not path.is_file():
        NormalizeStep().run(ctx)
    return load_json(path, "map/project-map.json") if path.is_file() else {
        "schema": "99x.extract.project-map/v1",
        "surfaces": [],
    }


def _round_seen(pages: list[dict]) -> dict[str, int]:
    """Highest round that observed each app:name descriptor."""
    seen: dict[str, int] = {}
    for page in pages:
        if not isinstance(page, dict):
            continue
        if page.get("error"):
            continue
        round_no = int(page.get("round") or 1)
        for item in page.get("templateOrder") or []:
            if not isinstance(item, str) or not item:
                continue
            prev = seen.get(item, 0)
            if round_no >= prev:
                seen[item] = round_no
    return seen


def _round_sets(pages: list[dict]) -> tuple[set[str], set[str]]:
    round1: set[str] = set()
    round2: set[str] = set()
    for page in pages:
        if not isinstance(page, dict) or page.get("error"):
            continue
        dest = round2 if int(page.get("round") or 1) >= 2 else round1
        for item in page.get("templateOrder") or []:
            if isinstance(item, str) and item:
                dest.add(item)
    return round1, round2


def _composition_for(descriptor: str, pages: list[dict]) -> list[str]:
    """Prefer the highest-round page that lists this descriptor first (the page)."""
    best: tuple[int, list[str]] | None = None
    for page in pages:
        if not isinstance(page, dict) or page.get("error"):
            continue
        order = [x for x in (page.get("templateOrder") or []) if isinstance(x, str)]
        if descriptor not in order:
            continue
        round_no = int(page.get("round") or 1)
        if best is None or round_no >= best[0]:
            best = (round_no, order)
    return list(best[1]) if best else []


def merge_surfaces(
    surfaces: list[dict],
    runtime: dict | None,
) -> tuple[list[dict], list[dict]]:
    """Return (updated surfaces, contradictions). Runtime beats static."""
    if runtime is None:
        updated = []
        for surface in surfaces:
            row = dict(surface)
            row.setdefault("status", "unverified-live")
            updated.append(row)
        return updated, []

    pages = [p for p in (runtime.get("pages") or []) if isinstance(p, dict)]
    seen = _round_seen(pages)
    round1, round2 = _round_sets(pages)
    contradictions: list[dict] = []
    updated: list[dict] = []

    for surface in surfaces:
        row = dict(surface)
        kind = row.get("kind") or ""
        key = _descriptor_key(row)
        evidence = list(row.get("evidence") or [])
        if key in seen:
            evidence.append(f"runtime:{key}:r{seen[key]}")
        row["evidence"] = evidence

        if kind not in OBSERVABLE_KINDS:
            row["status"] = "unverified-live"
            updated.append(row)
            continue

        in1 = key in round1
        in2 = key in round2
        if in1 and round2 and not in2:
            row["status"] = "conditional"
            contradictions.append({
                "id": row.get("id"),
                "descriptor": key,
                "detail": "present in round 1, absent in round 2",
            })
        elif key in seen:
            row["status"] = "live"
            row["composition"] = _composition_for(key, pages)
        else:
            row["status"] = "dead"
        updated.append(row)
    return updated, contradictions


def split_contexts(surfaces: list[dict], runtime: dict | None) -> list[dict]:
    contexts: list[dict] = []
    for ctx_id, title, kinds in CONTEXT_BUCKETS:
        ids = [
            s["id"] for s in surfaces
            if s.get("kind") in kinds and s.get("id")
        ]
        if ids:
            contexts.append({
                "id": ctx_id,
                "title": title,
                "kinds": sorted(kinds),
                "surfaces": ids,
                "journeys": [],
            })
    if runtime:
        seen_ctx: dict[str, list[str]] = {}
        for page in runtime.get("pages") or []:
            if not isinstance(page, dict) or page.get("error"):
                continue
            name = str(page.get("context") or "runtime")
            slug = f"runtime-{name}"
            for item in page.get("templateOrder") or []:
                if not isinstance(item, str):
                    continue
                for surface in surfaces:
                    if _descriptor_key(surface) == item and surface.get("id"):
                        seen_ctx.setdefault(slug, [])
                        ident = surface["id"]
                        if ident not in seen_ctx[slug]:
                            seen_ctx[slug].append(ident)
        for slug, ids in seen_ctx.items():
            title = slug.replace("runtime-", "Runtime: ", 1)
            contexts.append({
                "id": slug,
                "title": title,
                "kinds": [],
                "surfaces": ids,
                "journeys": [
                    {
                        "id": f"{slug}-open",
                        "title": f"Open {title}",
                        "surfaces": ids,
                    }
                ],
            })
    return contexts


def _rewrite_maps(ctx: object, surfaces: list[dict]) -> None:
    components = [s for s in surfaces if s.get("kind") in COMPONENT_KINDS]
    types = [s for s in surfaces if s.get("kind") in MODEL_KINDS]
    routes = [
        s for s in surfaces
        if s.get("kind") in ROUTE_KINDS or s.get("kind") == "mapping"
    ]
    ctx.write_json("map/project-map.json", {  # type: ignore[attr-defined]
        "schema": "99x.extract.project-map/v1",
        "surfaces": surfaces,
    })
    ctx.write_json("map/component-map.json", {  # type: ignore[attr-defined]
        "schema": "99x.extract.component-map/v1",
        "components": components,
    })
    ctx.write_json("map/content-model.json", {  # type: ignore[attr-defined]
        "schema": "99x.extract.content-model/v1",
        "types": types,
    })
    ctx.write_json("map/route-map.json", {  # type: ignore[attr-defined]
        "schema": "99x.extract.route-map/v1",
        "routes": routes,
    })


def _merge_report(
    runtime: dict | None,
    surfaces: list[dict],
    contradictions: list[dict],
) -> str:
    lines = [
        "# Merge report (runtime vs static)",
        "",
        "Runtime beats static. Round 2 beats round 1. Contradictions stay listed.",
        "",
    ]
    if runtime is None:
        lines.append(
            "No `inventory/runtime.json`. Every surface stays `unverified-live`."
        )
        lines.append("")
        return "\n".join(lines)
    counts: dict[str, int] = {}
    for surface in surfaces:
        status = str(surface.get("status") or "unverified-live")
        counts[status] = counts.get(status, 0) + 1
    lines.append("## Status counts")
    lines.append("")
    for status in ("live", "dead", "conditional", "unverified-live"):
        lines.append(f"- `{status}`: {counts.get(status, 0)}")
    lines.append("")
    lines.append("## Surfaces")
    lines.append("")
    lines.append("| id | kind | status |")
    lines.append("|---|---|---|")
    for surface in surfaces:
        ident = surface.get("id") or ""
        kind = surface.get("kind") or ""
        status = surface.get("status") or ""
        lines.append(f"| `{ident}` | {kind} | {status} |")
    lines.append("")
    lines.append("## Contradictions")
    lines.append("")
    if not contradictions:
        lines.append("None.")
    else:
        for row in contradictions:
            lines.append(
                f"- `{row.get('id')}` ({row.get('descriptor')}): {row.get('detail')}"
            )
    lines.append("")
    return "\n".join(lines)


class MergeStep:
    id = "maps.merge"
    requires = ("map/project-map.json",)
    produces = (
        "map/project-map.json",
        "map/bounded-contexts.json",
        "inventory/merge-report.md",
    )
    required = True

    def plan(self, ctx: object) -> list[str]:
        runtime = "present" if _load_runtime(ctx) else "absent"
        return [
            f"merge static maps with runtime ({runtime})",
            "write map/bounded-contexts.json",
            "write inventory/merge-report.md",
        ]

    def run(self, ctx: object) -> None:
        project = _ensure_maps(ctx)
        surfaces = [
            dict(s) for s in (project.get("surfaces") or []) if isinstance(s, dict)
        ]
        runtime = _load_runtime(ctx)
        merged, contradictions = merge_surfaces(surfaces, runtime)
        contexts = split_contexts(merged, runtime)
        payload = {
            "schema": "99x.extract.bounded-contexts/v1",
            "contexts": contexts,
        }
        validate(payload, "bounded-contexts", what="map/bounded-contexts.json")
        _rewrite_maps(ctx, merged)
        ctx.write_json("map/bounded-contexts.json", payload)  # type: ignore[attr-defined]
        ctx.write_text(  # type: ignore[attr-defined]
            "inventory/merge-report.md",
            _merge_report(runtime, merged, contradictions),
        )

    def check(self, _ctx: object) -> list[str]:
        return []
