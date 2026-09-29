"""enonic.descriptors — static XP7 inventory from disk. No XP runtime."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

# FR-10 coverage kinds. Sibling services/ and tasks/ sit beside site/, not under it.
# Other folders (admin/, site/filters/, site/processors/, site/error/) are out of
# coverage scope in v1.
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
)


def iter_resources_roots(source: Path) -> list[Path]:
    roots: list[Path] = []
    for path in sorted(source.rglob("src/main/resources")):
        if path.is_dir():
            roots.append(path)
    return roots


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


def _display_name(path: Path) -> str:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
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


def collect_resources(source: Path) -> list[dict]:
    resources: list[dict] = []
    for root in iter_resources_roots(source):
        app = app_name_for(root, source)
        site_xml = root / "site" / "site.xml"
        if site_xml.is_file():
            resources.append({
                "kind": "site",
                "name": "site",
                "displayName": _display_name(site_xml),
                "path": _rel(source, site_xml),
                "app": app,
            })
        for rel, kind in (*SITE_KINDS, *SIBLING_KINDS):
            for xml_path in _xml_files_in(root / rel):
                resources.append({
                    "kind": kind,
                    "name": xml_path.parent.name if xml_path.parent != root / rel else xml_path.stem,
                    "displayName": _display_name(xml_path),
                    "path": _rel(source, xml_path),
                    "app": app,
                })
    return resources


def collect_site_mappings(source: Path) -> list[dict]:
    mappings: list[dict] = []
    for root in iter_resources_roots(source):
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
        resources = collect_resources(ctx.source)  # type: ignore[attr-defined]
        payload = {
            "schema": "99x.extract.inventory/v1",
            "resources": resources,
        }
        ctx.write_json("inventory/static.json", payload)  # type: ignore[attr-defined]

    def check(self, _ctx: object) -> list[str]:
        return []
