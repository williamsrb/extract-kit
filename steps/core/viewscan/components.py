"""Template files to component surfaces: ids, kinds, child resolution, descriptor join.

Pure functions over the rows of `inventory/templates.json`; `maps.normalize` calls
`apply` and owns the writing.
"""

from __future__ import annotations

import posixpath
import re

FAMILIES = {"handlebars": "mustache", "mustache": "mustache"}
MARKUP_SUFFIXES = (".html", ".htm", ".ftl", ".ftlh", ".mustache", ".hbs", ".handlebars", ".peb", ".pebble")
DESCRIPTOR_VIEW_KINDS = {"page", "layout", "part", "macro"}


def _family(engine: str) -> str:
    return FAMILIES.get(engine, engine)


def _stem(path: str) -> str:
    return posixpath.basename(path).split(".", 1)[0]


def _norm(name: str) -> str:
    return re.sub(r"[-_]", "", name).lower()


def surface_ids(files: list[dict]) -> dict[str, str]:
    """`path -> surface id`. Kind is `partial` for included files and script helpers."""
    included = included_paths(files)
    stems: dict[str, int] = {}
    for entry in files:
        base = entry["path"].rsplit(".", 1)[0]
        stems[base] = stems.get(base, 0) + 1
    ids: dict[str, str] = {}
    for entry in files:
        kind = "partial" if entry["path"] in included or entry["role"] == "script" else "component"
        base = entry["path"].rsplit(".", 1)[0]
        name = entry["path"] if stems[base] > 1 else base
        ids[entry["path"]] = f"{entry['engine']}:{kind}:{name}"
    return ids


def included_paths(files: list[dict]) -> set[str]:
    resolver = _Resolver(files)
    return {
        target["path"]
        for entry in files for child in entry["scan"]["children"]
        if (target := resolver.resolve(entry, child["ref"])) is not None
        and target["path"] != entry["path"]
    }


class _Resolver:
    def __init__(self, files: list[dict]) -> None:
        self.files = files
        self.by_path = {f["path"]: f for f in files}
        self.selectors = {
            f["scan"].get("meta", {}).get("selector"): f for f in files if f["scan"].get("meta", {}).get("selector")
        }
        self.macros = {
            slot["name"]: f for f in files if f["engine"] == "freemarker" for slot in f["scan"]["slots"]
        }
        self.by_stem: dict[str, list[dict]] = {}
        self.by_name: dict[tuple[str, str], list[dict]] = {}
        for f in files:
            self.by_stem.setdefault(_stem(f["path"]), []).append(f)
            for name in (_norm(_stem(f["path"])), _norm(f["scan"].get("meta", {}).get("name", ""))):
                if name:
                    self.by_name.setdefault((f["engine"], name), []).append(f)

    def resolve(self, source: dict, ref: str) -> dict | None:
        engine = source["engine"]
        if engine == "freemarker" and ref.startswith("@"):
            found = self.macros.get(ref[1:].split(".")[-1])
            return found if found and found is not source else None
        if engine == "angular":
            return self.selectors.get(ref)
        if engine in ("react", "vue"):
            return self._by_name(source, ref)
        return self._by_path(source, ref)

    def _by_name(self, source: dict, ref: str) -> dict | None:
        wanted = _norm(ref.split(".")[0])
        named = [f for f in self.by_name.get((source["engine"], wanted), []) if f is not source]
        declared = [f for f in named if _norm(f["scan"].get("meta", {}).get("name", "")) == wanted]
        return _nearest(source, declared or named)

    def _by_path(self, source: dict, ref: str) -> dict | None:
        target = re.sub(r"^~\{|\}$", "", ref.split("::")[0].strip()).strip("/")
        if not target:
            return None
        family = _family(source["engine"])
        here = posixpath.dirname(source["path"])
        suffix = posixpath.splitext(target)[1]
        matches = []
        for entry in self.by_stem.get(_stem(target), []):
            if entry is source or _family(entry["engine"]) != family:
                continue
            path = entry["path"]
            stem_path = path.rsplit(".", 1)[0]
            wanted = target.rsplit(".", 1)[0] if suffix and suffix == posixpath.splitext(path)[1] else target
            if stem_path in (posixpath.normpath(posixpath.join(here, wanted)), wanted) \
                    or stem_path.endswith("/" + wanted):
                matches.append(entry)
        return _nearest(source, matches)


def _nearest(source: dict, candidates: list[dict]) -> dict | None:
    """The candidate sharing the longest directory prefix with `source`, path order on ties."""
    if not candidates:
        return None
    here = posixpath.dirname(source["path"]).split("/")

    def shared(entry: dict) -> int:
        there = posixpath.dirname(entry["path"]).split("/")
        count = 0
        for a, b in zip(here, there, strict=False):
            if a != b:
                break
            count += 1
        return count

    return min(candidates, key=lambda e: (-shared(e), e["path"]))


def template_block(entry: dict, file_ids: dict[str, str], resolver: _Resolver, data_source: str) -> dict:
    scan = entry["scan"]
    children = []
    for child in scan["children"]:
        target = resolver.resolve(entry, child["ref"])
        found = target is not None and target["path"] != entry["path"]
        children.append({
            "ref": child["ref"], "line": child["line"],
            "surface": file_ids[target["path"]] if found else None,
            "status": "resolved" if found else "unresolved",
        })
    return {
        "engine": entry["engine"],
        "framework": entry["framework"],
        "file": entry["path"],
        "inputs": scan["inputs"],
        "children": children,
        "slots": scan["slots"],
        "outputs": scan["outputs"],
        "logic": scan["logic"],
        "i18n": scan["i18n"],
        "assets": scan["assets"],
        "dom": scan["dom"],
        "dataSource": data_source,
        **({"syntax": entry["syntax"]} if entry.get("syntax") else {}),
    }


def _view_files(surface: dict, by_folder: dict[str, list[dict]], by_path: dict[str, dict]) -> list[dict]:
    """Template files a descriptor surface renders: controller refs first, then its folder."""
    behavior = surface.get("behavior") or {}
    folder = posixpath.dirname(str(behavior.get("file") or surface.get("entry") or ""))
    found: list[dict] = []
    for view in behavior.get("views") or []:
        ref = view.get("ref")
        if view.get("via") == "resolve" and ref:
            entry = by_path.get(posixpath.normpath(posixpath.join(folder, str(ref))))
            if entry:
                found.append(entry)
        elif view.get("via") == "React4xp" and ref:
            wanted = str(ref).rsplit("/", 1)[-1]
            found += [
                e for e in by_path.values()
                if e["engine"] == "react" and _stem(e["path"]) == wanted
            ]
    if not found:
        siblings = [e for e in by_folder.get(folder, []) if e["role"] == "template"]
        name = posixpath.basename(folder)
        found = [e for e in siblings if _stem(e["path"]) == name] or siblings[:1]
    return found


def apply(templates: dict, surfaces: list[dict]) -> tuple[list[dict], list[dict]]:
    """Attach `template` to descriptor surfaces and return (new component surfaces, route surfaces).

    `surfaces` is mutated: a descriptor surface and its view become one surface.
    """
    files = templates.get("files") or []
    if not files:
        return [], []
    by_path = {f["path"]: f for f in files}
    by_folder: dict[str, list[dict]] = {}
    for entry in files:
        by_folder.setdefault(posixpath.dirname(entry["path"]), []).append(entry)
    ids = surface_ids(files)
    resolver = _Resolver(files)
    joined: dict[str, str] = {}
    for surface in surfaces:
        if surface.get("kind") not in DESCRIPTOR_VIEW_KINDS:
            continue
        views = _view_files(surface, by_folder, by_path)
        if views:
            surface["templates"] = [_template_ref(e) for e in {e["path"]: e for e in views}.values()]
        for entry in views[:1]:
            if entry["path"] in joined:
                continue
            joined[entry["path"]] = surface["id"]
            surface["template"] = template_block(entry, ids, resolver, surface["id"])
            surface["stackRef"] = {**surface.get("stackRef", {}), "template": _stack_ref(entry)}
    # A resolved child that was joined points at the descriptor surface instead.
    for surface in surfaces:
        for child in (surface.get("template") or {}).get("children") or []:
            for path, ident in joined.items():
                if child["surface"] == ids.get(path):
                    child["surface"] = ident

    components: list[dict] = []
    routes: list[dict] = []
    for entry in files:
        if entry["path"] in joined:
            continue
        ident = ids[entry["path"]]
        data_source = "none"
        if entry.get("route"):
            data_source = f"next:route:{entry['route']}"
            routes.append(_route_surface(entry, ident))
        component = _base(ident, ident.split(":")[1], entry)
        component["template"] = template_block(entry, ids, resolver, data_source)
        for child in component["template"]["children"]:
            for path, owner in joined.items():
                if child["surface"] == ids.get(path):
                    child["surface"] = owner
        components.append(component)
    return components, routes


def _template_ref(entry: dict) -> dict:
    ref = {"file": entry["path"], "engine": entry["engine"]}
    if entry.get("syntax"):
        ref["syntax"] = entry["syntax"]
    return ref


def _stack_ref(entry: dict) -> dict:
    return {"engine": entry["engine"], "framework": entry["framework"], "file": entry["path"]}


def _base(ident: str, kind: str, entry: dict) -> dict:
    return {
        "id": ident,
        "kind": kind,
        "entry": entry["path"],
        "composition": [],
        "contentTypes": [],
        "states": [],
        "integrations": [],
        "evidence": [],
        "status": "unverified-live",
        "stackRef": {"template": _stack_ref(entry)},
    }


def _route_surface(entry: dict, component_id: str) -> dict:
    surface = _base(f"next:route:{entry['route']}", "route", entry)
    surface["composition"] = [component_id]
    return surface
