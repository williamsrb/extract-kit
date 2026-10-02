"""enonic.descriptors — static XP7 inventory from disk. No XP runtime."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from pathlib import Path

from extractkit_cli import scope
from steps.enonic.forms import parse_form, parse_regions

# FR-10 coverage kinds. Sibling folders (services/, tasks/, admin/) sit beside site/,
# not under it. Filters, processors, errors, webapp, id providers and i18n bundles
# are not XML-folder descriptors; `_collect_extra` reads them.
SITE_KINDS: tuple[tuple[str, str], ...] = (
    ("site/content-types", "content-type"),
    ("site/mixins", "mixin"),
    ("site/x-data", "x-data"),
    ("site/pages", "page"),
    ("site/layouts", "layout"),
    ("site/parts", "part"),
    ("site/macros", "macro"),
)
SIBLING_KINDS: tuple[tuple[str, str], ...] = (
    ("services", "service"),
    ("tasks", "task"),
    ("admin/tools", "admin-tool"),
    ("admin/widgets", "admin-widget"),
)
SCRIPT_SUFFIXES = (".js", ".ts", ".es6")


def iter_resources_roots(source: Path, exclude: Iterable[str] = ()) -> list[Path]:
    found = [p for p in sorted(source.rglob("src/main/resources")) if p.is_dir()]
    return scope.kept(source, found, exclude)


def _parse_properties(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw = stripped.split("=", 1)
        values[key.strip()] = raw.strip()
    return values


def app_name_for(resources: Path, source: Path) -> str:
    source = source.resolve()
    for parent in [resources, *resources.parents]:
        try:
            parent.relative_to(source)
        except ValueError:
            break
        props = parent / "gradle.properties"
        if not props.is_file():
            continue
        values = _parse_properties(props)
        if values.get("appName"):
            return values["appName"]
        group = values.get("group", "")
        project = values.get("projectName") or values.get("project", "")
        if group and project:
            return f"{group}.{project}"
    return "unknown"


def _xml_files_in(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    files: list[Path] = []
    for child in sorted(folder.iterdir()):
        if child.is_dir():
            named = child / f"{child.name}.xml"
            if named.is_file():
                files.append(named)
            else:
                files.extend(sorted(p for p in child.glob("*.xml") if p.is_file()))
        elif child.suffix == ".xml":
            files.append(child)
    return files


FORM_KINDS = frozenset({
    "content-type", "mixin", "x-data", "page", "layout", "part", "macro", "task",
})
REGION_KINDS = frozenset({"page", "layout"})


def _parse_root(path: Path) -> ET.Element | None:
    try:
        return ET.parse(path).getroot()
    except ET.ParseError:
        return None


def _display_name(path: Path, root: ET.Element | None) -> str:
    if root is None:
        return path.stem
    text = root.findtext("display-name")
    if text and text.strip():
        return text.strip()
    description = root.findtext("description")
    if description and description.strip():
        return description.strip()
    return path.stem


def _rel(source: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(source.resolve()).as_posix()
    except ValueError:
        return str(path)


def collect_xdata_applicability(root: ET.Element) -> list[dict]:
    """`site.xml` `<x-data name allowContentTypes>` entries."""
    return [
        {"name": node.get("name") or "", "allowContentTypes": node.get("allowContentTypes") or ""}
        for node in root.iter("x-data")
        if node.get("name")
    ]


def collect_resources(source: Path, exclude: Iterable[str] = ()) -> list[dict]:
    resources: list[dict] = []
    for root in iter_resources_roots(source, exclude):
        app = app_name_for(root, source)
        site_xml = root / "site" / "site.xml"
        if site_xml.is_file():
            site_root = _parse_root(site_xml)
            site_row = {
                "kind": "site",
                "name": "site",
                "displayName": _display_name(site_xml, site_root),
                "path": _rel(source, site_xml),
                "app": app,
            }
            if site_root is not None:
                site_row["xData"] = collect_xdata_applicability(site_root)
            resources.append(site_row)
        for rel, kind in (*SITE_KINDS, *SIBLING_KINDS):
            for xml_path in _xml_files_in(root / rel):
                xml_root = _parse_root(xml_path)
                row = {
                    "kind": kind,
                    "name": xml_path.parent.name if xml_path.parent != root / rel else xml_path.stem,
                    "displayName": _display_name(xml_path, xml_root),
                    "path": _rel(source, xml_path),
                    "app": app,
                }
                if xml_root is not None:
                    if kind in FORM_KINDS:
                        row["form"] = parse_form(xml_root)
                    if kind in REGION_KINDS:
                        row["regions"] = parse_regions(xml_root)
                resources.append(row)
        resources.extend(_script_only(root, source, app))
        resources.extend(_collect_extra(root, source, app))
    return resources


def _script_only(root: Path, source: Path, app: str) -> list[dict]:
    """Services and tasks may omit their XML descriptor; the controller alone defines them."""
    rows: list[dict] = []
    for rel, kind in (("services", "service"), ("tasks", "task")):
        base = root / rel
        if not base.is_dir():
            continue
        for folder in sorted(p for p in base.iterdir() if p.is_dir()):
            if (folder / f"{folder.name}.xml").is_file() or any(folder.glob("*.xml")):
                continue
            script = _script(folder / folder.name)
            if script:
                rows.append(_extra(kind, folder.name, script, source, app))
    return rows


def _script(base: Path) -> Path | None:
    return next((base.with_suffix(s) for s in SCRIPT_SUFFIXES if base.with_suffix(s).is_file()), None)


def _extra(kind: str, name: str, path: Path, source: Path, app: str, **more: object) -> dict:
    return {
        "kind": kind, "name": name, "displayName": name,
        "path": _rel(source, path), "app": app, **more,
    }


def _site_mapping_filters(root: Path, source: Path, app: str, site_xml: ET.Element, site_path: Path) -> list[dict]:
    rows: list[dict] = []
    for node in site_xml.iter("mapping"):
        ref = node.get("filter")
        if not ref:
            continue
        target = root / ref.lstrip("/")
        found = target if target.is_file() else _script(target.with_suffix(""))
        rows.append(_extra(
            "filter", Path(ref).stem, found or site_path, source, app,
            mapping={"filter": ref, "order": node.get("order") or ""},
        ))
    return rows


def _site_processors(root: Path, source: Path, app: str, site_xml: ET.Element, site_path: Path) -> list[dict]:
    rows: list[dict] = []
    for node in site_xml.iter("response-processor"):
        name = node.get("name")
        if name:
            found = _script(root / "site" / "processors" / name)
            rows.append(_extra(
                "response-processor", name, found or site_path, source, app,
                order=node.get("order") or "",
            ))
    return rows


def _i18n_keys(path: Path) -> list[str]:
    keys: list[str] = []
    continued = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if continued:
            continued = stripped.endswith("\\")
            continue
        if not stripped or stripped[0] in "#!":
            continue
        continued = stripped.endswith("\\")
        keys.append(re.split(r"[=:\s]", stripped, maxsplit=1)[0])
    return keys


def _i18n_bundles(root: Path, source: Path, app: str) -> list[dict]:
    rows: list[dict] = []
    for location, prefix in (("i18n", ""), ("site/i18n", "site.")):
        folder = root / location
        files = sorted(folder.glob("phrases*.properties")) if folder.is_dir() else []
        keys = {f: _i18n_keys(f) for f in files}
        union = sorted(set().union(*keys.values())) if keys else []
        for file in files:
            locale = file.stem.partition("_")[2] or "default"
            own = set(keys[file])
            rows.append(_extra(
                "i18n-bundle", prefix + file.stem, file, source, app, location=location,
                locale=locale, keyCount=len(own), missingKeys=[k for k in union if k not in own],
            ))
    return rows


def _collect_extra(root: Path, source: Path, app: str) -> list[dict]:
    rows: list[dict] = []
    site_path = root / "site" / "site.xml"
    parsed = _parse_root(site_path) if site_path.is_file() else None
    mapped: set[str] = set()
    if parsed is not None:
        rows += _site_mapping_filters(root, source, app, parsed, site_path)
        rows += _site_processors(root, source, app, parsed, site_path)
        mapped = {r["path"] for r in rows if r["kind"] == "filter"}
    filters = root / "site" / "filters"
    if filters.is_dir():
        for file in sorted(f for f in filters.rglob("*") if f.suffix in SCRIPT_SUFFIXES):
            if _rel(source, file) not in mapped:
                rows.append(_extra("filter", file.stem, file, source, app))
    for base, name in (
        (root / "site" / "error" / "error", "site-error"),
        (root / "error" / "error", "error"),
        (root / "webapp" / "webapp", "webapp"),
    ):
        found = _script(base)
        if found:
            kind = "webapp" if name == "webapp" else "error"
            rows.append(_extra(kind, name, found, source, app))
    provider = root / "idprovider" / "idprovider"
    descriptor = provider.with_suffix(".xml")
    found = descriptor if descriptor.is_file() else _script(provider)
    if found:
        rows.append(_extra("id-provider", "idprovider", found, source, app))
    rows += _i18n_bundles(root, source, app)
    return rows


def mapping_controllers(root: Path) -> list[Path]:
    """Files named by `site.xml` `<mapping controller="/site/…">` under one resources root."""
    site_xml = root / "site" / "site.xml"
    parsed = _parse_root(site_xml) if site_xml.is_file() else None
    if parsed is None:
        return []
    paths = {
        root / node.get("controller", "").lstrip("/")
        for node in parsed.iter("mapping")
        if node.get("controller")
    }
    return sorted(paths)


def collect_site_mappings(source: Path, exclude: Iterable[str] = ()) -> list[dict]:
    mappings: list[dict] = []
    for root in iter_resources_roots(source, exclude):
        site_xml = root / "site" / "site.xml"
        if not site_xml.is_file():
            continue
        try:
            tree = ET.parse(site_xml)
        except ET.ParseError:
            continue
        app = app_name_for(root, source)
        for mapping in tree.findall(".//mapping"):
            controller = mapping.get("controller") or ""
            match = ""
            match_el = mapping.find("match")
            if match_el is not None and match_el.text:
                match = match_el.text.strip()
            pattern_el = mapping.find("pattern")
            pattern = (pattern_el.text or "").strip() if pattern_el is not None else ""
            mappings.append({
                "app": app,
                "controller": controller,
                "filter": mapping.get("filter") or "",
                "match": match,
                "pattern": pattern,
                "path": _rel(source, site_xml),
            })
    return mappings


class EnonicDescriptorsStep:
    id = "enonic.descriptors"
    requires: tuple[str, ...] = ()
    produces = ("inventory/static.json",)
    required = True

    def plan(self, _ctx: object) -> list[str]:
        return []

    def run(self, ctx: object) -> None:
        resources = collect_resources(ctx.source, scope.of(ctx))  # type: ignore[attr-defined]
        payload = {
            "schema": "99x.extract.inventory/v1",
            "resources": resources,
        }
        ctx.write_json("inventory/static.json", payload)  # type: ignore[attr-defined]

    def check(self, _ctx: object) -> list[str]:
        return []
