"""maps.normalize — static-only merge into stack-agnostic map/*.json."""

from __future__ import annotations

from pathlib import Path

from extractkit_cli.common import load_json
from steps.enonic.descriptors import collect_site_mappings

COMPONENT_KINDS = {"page", "layout", "part", "macro"}
MODEL_KINDS = {"content-type", "mixin", "x-data"}
ROUTE_KINDS = {"service", "task", "site"}


def _surface(resource: dict) -> dict:
    kind = resource.get("kind") or "unknown"
    name = resource.get("name") or "unnamed"
    app = resource.get("app") or "unknown"
    path = resource.get("path") or ""
    return {
        "id": f"{app}:{kind}:{name}",
        "kind": kind,
        "entry": path,
        "composition": [],
        "contentTypes": [],
        "states": [],
        "integrations": [],
        "evidence": [],
        "status": "unverified-live",
        "stackRef": {"enonic": {"descriptor": path, "app": app}},
    }


def _load_resources(ctx: object) -> list[dict]:
    path: Path = ctx.rel("inventory/static.json")  # type: ignore[attr-defined]
    if path.is_file():
        payload = load_json(path, "inventory/static.json")
        return list(payload.get("resources") or [])
    # `step maps.normalize` on a sidecar without inventory: re-scan source.
    from steps.enonic.descriptors import collect_resources

    return collect_resources(ctx.source)  # type: ignore[attr-defined]


class NormalizeStep:
    id = "maps.normalize"
    requires = ("inventory/static.json",)
    produces = (
        "map/project-map.json",
        "map/component-map.json",
        "map/content-model.json",
        "map/route-map.json",
    )
    required = True

    def plan(self, _ctx: object) -> list[str]:
        return []

    def run(self, ctx: object) -> None:
        resources = _load_resources(ctx)
        surfaces = [_surface(r) for r in resources if isinstance(r, dict)]
        components = [s for s in surfaces if s["kind"] in COMPONENT_KINDS]
        types = [s for s in surfaces if s["kind"] in MODEL_KINDS]
        routes = [s for s in surfaces if s["kind"] in ROUTE_KINDS]
        for mapping in collect_site_mappings(ctx.source):  # type: ignore[attr-defined]
            controller = mapping.get("controller") or "mapping"
            routes.append({
                "id": f"{mapping.get('app')}:mapping:{controller}",
                "kind": "mapping",
                "entry": mapping.get("path") or "",
                "composition": [],
                "contentTypes": [],
                "states": [],
                "integrations": [],
                "evidence": [],
                "status": "unverified-live",
                "stackRef": {
                    "enonic": {
                        "descriptor": mapping.get("path"),
                        "app": mapping.get("app"),
                        "controller": controller,
                        "match": mapping.get("match"),
                        "pattern": mapping.get("pattern"),
                    }
                },
            })
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

    def check(self, _ctx: object) -> list[str]:
        return []
