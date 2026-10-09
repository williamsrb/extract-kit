"""maps.normalize — static-only merge into stack-agnostic map/*.json."""

from __future__ import annotations

from pathlib import Path

from extractkit_cli import scope
from extractkit_cli.common import load_json
from steps.core.behavior import walk_fields
from steps.core.viewscan import components as view_components
from steps.enonic.descriptors import collect_site_mappings
from steps.enonic.integrations import collect_external_callers

COMPONENT_KINDS = {"page", "layout", "part", "macro", "component", "partial"}
MODEL_KINDS = {"content-type", "mixin", "x-data", "i18n-bundle"}
ROUTE_KINDS = {
    "service", "task", "site", "filter", "response-processor", "error", "webapp",
    "id-provider", "route", "cron", "init", "external-caller",
}
ADMIN_KINDS = {"admin-tool", "admin-widget"}
# Facts a `cron` or `init` resource carries beyond its descriptor: schedule, what it starts.
JOB_KEYS = ("schedule", "starts", "tasks", "actions")


def mixin_id(app: str, ref: str) -> str:
    """The one id form for a mixin: `<app>:mixin:<name>`. `ref` is `<name>` or `<app>:<name>`."""
    owner, _, name = ref.rpartition(":")
    return f"{owner or app}:mixin:{name}"


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
            return [{**field, "mixin": mixin_id(app, ref)}]
        owner = key.split(":", 1)[0]
        out: list[dict] = []
        for child in mixins[key]:
            for item in _expand_field(child, owner, mixins, (*trail, key)):
                tagged = dict(item)
                tagged.setdefault("fromMixin", mixin_id(owner, key.split(":", 1)[1]))
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
    for key in JOB_KEYS:
        if key in resource:
            surface[key] = resource[key]
    return surface


def _bind_xdata(surfaces: list[dict], resources: list[dict]) -> None:
    """Attach each x-data surface's `site.xml` binding: which content types it applies to."""
    bindings: dict[str, dict] = {}
    for resource in resources:
        if not isinstance(resource, dict) or resource.get("kind") != "site":
            continue
        app = resource.get("app") or "unknown"
        for item in resource.get("xData") or []:
            name = item.get("name") or ""
            key = name if ":" in name else f"{app}:{name}"
            bindings[key] = {
                "allowContentTypes": (item.get("allowContentTypes") or "").replace("${app}", app),
                "optional": bool(item.get("optional")),
                "source": resource.get("path") or "",
            }
    for surface in surfaces:
        if surface["kind"] != "x-data":
            continue
        app = surface["stackRef"]["enonic"]["app"]
        name = surface["id"].rsplit(":", 1)[-1]
        binding = bindings.get(f"{app}:{name}")
        surface["binding"] = binding if binding else {"unbound": True}


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
    "inputs", "responses", "auth",
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
        _bind_xdata(surfaces, resources)
        for surface in surfaces:
            folder = Path(surface["entry"]).parent.as_posix()
            match = by_file.get(surface["entry"]) or by_folder.get(folder)
            if match:
                surface["behavior"] = _behavior(match)
            if surface["kind"] == "site":
                app = surface["stackRef"]["enonic"]["app"]
                surface["configKeys"] = _app_signals(rows, app, "configKeys", "key")
                surface["listeners"] = _app_signals(rows, app, "listeners", "type")
                surface["listenerRefs"] = sorted(
                    ({"type": item["type"], "source": f"{row['file']}:{item['line']}"}
                     for row in rows if row.get("app") == app for item in row.get("listeners") or []),
                    key=lambda r: (r["type"], r["source"]),
                )
        for caller in collect_external_callers(ctx.source, scope.of(ctx)):  # type: ignore[attr-defined]
            surface = _surface_base("external-caller", caller["name"], caller["app"], caller["path"])
            surface["callers"] = caller["targets"]
            surface["schedules"] = caller["schedules"]
            if caller.get("includedBy"):
                surface["includedBy"] = caller["includedBy"]
            surfaces.append(surface)
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
