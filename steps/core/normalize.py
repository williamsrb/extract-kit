"""maps.normalize — static-only merge into stack-agnostic map/*.json."""

from __future__ import annotations

from pathlib import Path

from extractkit_cli import scope
from extractkit_cli.common import load_json
from steps.core.behavior import walk_fields
from steps.core.viewscan import components as view_components
from steps.enonic.descriptors import collect_site_mappings

COMPONENT_KINDS = {"page", "layout", "part", "macro", "component", "partial"}
MODEL_KINDS = {"content-type", "mixin", "x-data", "i18n-bundle"}
ROUTE_KINDS = {
    "service", "task", "site", "filter", "response-processor", "error", "webapp",
    "id-provider", "route",
}
ADMIN_KINDS = {"admin-tool", "admin-widget"}


def _mixin_index(resources: list[dict]) -> dict[str, list[dict]]:
    return {
        f"{r.get('app') or 'unknown'}:{r.get('name')}": r.get("form") or []
        for r in resources
        if isinstance(r, dict) and r.get("kind") == "mixin"
    }


def _expand_field(field: dict, app: str, mixins: dict[str, list[dict]], trail: tuple[str, ...]) -> list[dict]:
    ref = field.get("mixin")
    if ref and "name" not in field:
        key = ref if ":" in ref else f"{app}:{ref}"
        if key not in mixins or key in trail:
            return [field]
        owner = key.split(":", 1)[0]
        out: list[dict] = []
        for child in mixins[key]:
            for item in _expand_field(child, owner, mixins, (*trail, key)):
                tagged = dict(item)
                tagged.setdefault("fromMixin", key)
                out.append(tagged)
        return out
    row = dict(field)
    if "items" in row:
        row["items"] = _expand_all(row["items"], app, mixins, trail)
    if "options" in row:
        row["options"] = [
            {**option, "items": _expand_all(option.get("items") or [], app, mixins, trail)}
            for option in row["options"]
        ]
    return [row]


def _expand_all(fields: list[dict], app: str, mixins: dict[str, list[dict]], trail: tuple[str, ...] = ()) -> list[dict]:
    out: list[dict] = []
    for field in fields:
        out.extend(_expand_field(field, app, mixins, trail))
    return out


def _surface(resource: dict, mixins: dict[str, list[dict]] | None = None) -> dict:
    kind = resource.get("kind") or "unknown"
    name = resource.get("name") or "unnamed"
    app = resource.get("app") or "unknown"
    path = resource.get("path") or ""
    surface = _surface_base(kind, name, app, path)
    if "form" in resource:
        form = _expand_all(resource["form"], app, mixins or {})
        surface["fields" if kind in MODEL_KINDS else "config"] = form
    if "regions" in resource:
        surface["regions"] = list(resource["regions"])
    return surface


def _surface_base(kind: str, name: str, app: str, path: str) -> dict:
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


SELECTOR_TYPES = {"ContentSelector", "ImageSelector", "MediaSelector"}


def build_references(types: list[dict]) -> list[dict]:
    """Static reference graph: selector fields and the content types they allow."""
    rows: list[dict] = []
    for surface in types:
        for path, field in walk_fields(surface.get("fields") or []):
            if field.get("type") in SELECTOR_TYPES:
                allowed = (field.get("config") or {}).get("allowContentType") or []
                rows.append({"from": surface["id"], "field": path, "to": sorted(set(allowed))})
    return sorted(rows, key=lambda r: (r["from"], r["field"]))


BEHAVIOR_KEYS = (
    "file", "imports", "calls", "queries", "methods", "views", "i18n", "configKeys", "listeners",
)


def _load_controller_rows(ctx: object) -> list[dict]:
    path: Path = ctx.rel("inventory/controllers.json")  # type: ignore[attr-defined]
    if not path.is_file():
        return []
    payload = load_json(path, "inventory/controllers.json")
    return [r for r in payload.get("controllers") or [] if isinstance(r, dict)]


def _controllers_by_folder(rows: list[dict]) -> dict[str, dict]:
    """Behavior records keyed by descriptor folder; the file named after the folder wins."""
    by_folder: dict[str, dict] = {}
    for row in rows:
        folder = row.get("folder") or ""
        own = Path(str(row.get("file") or "")).stem == Path(folder).name
        if folder not in by_folder or own:
            by_folder[folder] = row
    return by_folder


def _app_signals(rows: list[dict], app: str, field: str, name: str) -> list[str]:
    return sorted({
        item[name] for row in rows if row.get("app") == app for item in row.get(field) or []
    })


def _behavior(row: dict) -> dict:
    return {key: row[key] for key in BEHAVIOR_KEYS if key in row}


def _load_templates(ctx: object) -> dict:
    path: Path = ctx.rel("inventory/templates.json")  # type: ignore[attr-defined]
    return load_json(path, "inventory/templates.json") if path.is_file() else {}


def _load_resources(ctx: object) -> list[dict]:
    path: Path = ctx.rel("inventory/static.json")  # type: ignore[attr-defined]
    if path.is_file():
        payload = load_json(path, "inventory/static.json")
        return list(payload.get("resources") or [])
    # `step maps.normalize` on a sidecar without inventory: re-scan source.
    from steps.enonic.descriptors import collect_resources

    return collect_resources(ctx.source, scope.of(ctx))  # type: ignore[attr-defined]


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
        mixins = _mixin_index(resources)
        rows = _load_controller_rows(ctx)
        by_folder = _controllers_by_folder(rows)
        by_file = {r.get("file"): r for r in rows}
        surfaces = [_surface(r, mixins) for r in resources if isinstance(r, dict)]
        for surface in surfaces:
            folder = Path(surface["entry"]).parent.as_posix()
            match = by_file.get(surface["entry"]) or by_folder.get(folder)
            if match:
                surface["behavior"] = _behavior(match)
            if surface["kind"] == "site":
                app = surface["stackRef"]["enonic"]["app"]
                surface["configKeys"] = _app_signals(rows, app, "configKeys", "key")
                surface["listeners"] = _app_signals(rows, app, "listeners", "type")
        template_components, template_routes = view_components.apply(_load_templates(ctx), surfaces)
        surfaces += template_components + template_routes
        components = [s for s in surfaces if s["kind"] in COMPONENT_KINDS]
        types = [s for s in surfaces if s["kind"] in MODEL_KINDS]
        routes = [s for s in surfaces if s["kind"] in ROUTE_KINDS | ADMIN_KINDS]
        for mapping in collect_site_mappings(ctx.source, scope.of(ctx)):  # type: ignore[attr-defined]
            controller = mapping.get("controller") or mapping.get("filter") or "mapping"
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
                        "filter": mapping.get("filter") or None,
                        "match": mapping.get("match"),
                        "pattern": mapping.get("pattern"),
                    }
                },
            })
        ctx.write_json("map/project-map.json", {  # type: ignore[attr-defined]
            "schema": "extractkit.project-map/v1",
            "surfaces": surfaces,
        })
        ctx.write_json("map/component-map.json", {  # type: ignore[attr-defined]
            "schema": "extractkit.component-map/v1",
            "components": components,
        })
        ctx.write_json("map/content-model.json", {  # type: ignore[attr-defined]
            "schema": "extractkit.content-model/v1",
            "types": types,
            "references": build_references(types),
        })
        ctx.write_json("map/route-map.json", {  # type: ignore[attr-defined]
            "schema": "extractkit.route-map/v1",
            "routes": routes,
        })

    def check(self, _ctx: object) -> list[str]:
        return []
