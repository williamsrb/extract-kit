"""`extractkit check` — schemas, FR-10 descriptor coverage, OpenAPI x-source."""

from __future__ import annotations

import re
from argparse import Namespace
from pathlib import Path

import yaml

from . import guide, schema
from .common import load_json, load_yaml
from .errors import ExtractkitError

MAP_FILES = (
    ("map/project-map.json", "project-map"),
    ("map/component-map.json", "component-map"),
    ("map/content-model.json", "content-model"),
    ("map/route-map.json", "route-map"),
)
HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
FR_HEADING = re.compile(r"^#{1,6}\s*FR-\d+\b", re.IGNORECASE)
BACKTICK = re.compile(r"`([^`]+)`")


def _out_dir(raw: str | None) -> Path:
    if not raw:
        raise ExtractkitError(
            "no --out given",
            "pass --out pointing at an extract tree (the sidecar run directory)",
        )
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise ExtractkitError(
            f"--out {path} is not a directory",
            "run extractkit run first, then pass that sidecar path",
        )
    return path


def _paths_in_maps(out: Path) -> set[str]:
    found: set[str] = set()
    for rel, _stem in MAP_FILES:
        path = out / rel
        if not path.is_file():
            continue
        payload = load_json(path, rel)
        for collection_key in ("surfaces", "components", "types", "routes"):
            items = payload.get(collection_key) or []
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                entry = item.get("entry")
                if isinstance(entry, str):
                    found.add(entry)
                stack = (item.get("stackRef") or {}).get("enonic") or {}
                descriptor = stack.get("descriptor")
                if isinstance(descriptor, str):
                    found.add(descriptor)
    return found


def _hygiene_text(out: Path) -> str:
    path = out / "hygiene" / "dead-code.md"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _descriptor_coverage(out: Path) -> list[str]:
    inventory_path = out / "inventory" / "static.json"
    if not inventory_path.is_file():
        raise ExtractkitError(
            f"missing {inventory_path}",
            "run extractkit run --profile enonic so inventory/static.json exists",
        )
    inventory = load_json(inventory_path, "inventory/static.json")
    schema.validate(inventory, "inventory", what="inventory/static.json")
    mapped = _paths_in_maps(out)
    hygiene = _hygiene_text(out)
    missing: list[str] = []
    for resource in inventory.get("resources") or []:
        path = resource.get("path")
        if not isinstance(path, str):
            continue
        name = str(resource.get("name") or "")
        if path in mapped:
            continue
        if path in hygiene or (name and name in hygiene):
            continue
        missing.append(path)
    return missing


def _operations(spec: dict) -> list[tuple[str, str, dict]]:
    found: list[tuple[str, str, dict]] = []
    paths = spec.get("paths") or {}
    if not isinstance(paths, dict):
        return found
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        for method in HTTP_METHODS:
            op = item.get(method)
            if isinstance(op, dict):
                found.append((str(path), method, op))
    return found


def _x_source_gaps(spec: dict) -> list[str]:
    gaps: list[str] = []
    for path, method, op in _operations(spec):
        sources = op.get("x-source")
        if isinstance(sources, str) and sources.strip():
            continue
        if isinstance(sources, list) and any(str(s).strip() for s in sources):
            continue
        gaps.append(f"{method.upper()} {path}")
    return gaps


def check_tree(out: Path) -> list[str]:
    problems: list[str] = []
    manifest_path = out / "MANIFEST.yaml"
    if not manifest_path.is_file():
        problems.append(f"missing {manifest_path}")
    else:
        try:
            schema.validate(
                load_yaml(manifest_path, "MANIFEST.yaml"),
                "manifest",
                what="MANIFEST.yaml",
            )
        except ExtractkitError as exc:
            problems.append(str(exc))

    for rel, stem in MAP_FILES:
        path = out / rel
        if not path.is_file():
            problems.append(f"missing {path}")
            continue
        try:
            schema.validate(load_json(path, rel), stem, what=rel)
        except ExtractkitError as exc:
            problems.append(str(exc))

    try:
        missing = _descriptor_coverage(out)
    except ExtractkitError as exc:
        problems.append(str(exc))
        missing = []
    for path in missing:
        problems.append(
            f"descriptor {path} is in inventory/static.json but not in maps or hygiene"
        )

    openapi_path = out / "integrations" / "openapi.yaml"
    if not openapi_path.is_file():
        problems.append(f"missing {openapi_path}")
    else:
        try:
            spec = yaml.safe_load(openapi_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            problems.append(f"integrations/openapi.yaml is not valid YAML: {exc}")
            spec = {}
        if isinstance(spec, dict):
            for gap in _x_source_gaps(spec):
                problems.append(f"OpenAPI operation {gap} has no x-source")

    runtime_path = out / "inventory" / "runtime.json"
    if runtime_path.is_file():
        try:
            schema.validate(
                load_json(runtime_path, "inventory/runtime.json"),
                "runtime-inventory",
                what="inventory/runtime.json",
            )
        except ExtractkitError as exc:
            problems.append(str(exc))

    for rel, stem in (
        ("inventory/content-survey.json", "content-survey"),
        ("inventory/content-survey-resolved.json", "content-survey-resolved"),
        ("inventory/page-templates.json", "page-templates"),
    ):
        extra = out / rel
        if extra.is_file():
            try:
                schema.validate(load_json(extra, rel), stem, what=rel)
            except ExtractkitError as exc:
                problems.append(str(exc))

    contexts_path = out / "map" / "bounded-contexts.json"
    if contexts_path.is_file():
        try:
            schema.validate(
                load_json(contexts_path, "map/bounded-contexts.json"),
                "bounded-contexts",
                what="map/bounded-contexts.json",
            )
        except ExtractkitError as exc:
            problems.append(str(exc))

    problems.extend(_spec_fr_gaps(out))

    return problems


def _map_ids(out: Path) -> set[str]:
    ids: set[str] = set()
    path = out / "map" / "project-map.json"
    if not path.is_file():
        return ids
    payload = load_json(path, "map/project-map.json")
    for surface in payload.get("surfaces") or []:
        if isinstance(surface, dict) and surface.get("id"):
            ids.add(str(surface["id"]))
    return ids


def _spec_fr_gaps(out: Path) -> list[str]:
    specs_root = out / "spec-kit" / "specs"
    if not specs_root.is_dir():
        return []
    map_ids = _map_ids(out)
    problems: list[str] = []
    specs = sorted(specs_root.rglob("spec.md"))
    if not specs:
        problems.append(f"spec-kit/specs exists under {out} but has no spec.md")
        return problems
    for spec in specs:
        rel = spec.relative_to(out).as_posix()
        text = spec.read_text(encoding="utf-8")
        sections: list[tuple[str, str]] = []
        current: str | None = None
        body: list[str] = []
        for line in text.splitlines():
            if FR_HEADING.match(line.strip()):
                if current is not None:
                    sections.append((current, "\n".join(body)))
                current = line.strip()
                body = []
            elif current is not None:
                body.append(line)
        if current is not None:
            sections.append((current, "\n".join(body)))
        if not sections:
            problems.append(f"{rel} has no FR headings")
            continue
        for heading, section in sections:
            blob = heading + "\n" + section
            ticks = BACKTICK.findall(blob)
            cited_map = {tick for tick in ticks if tick in map_ids}
            cited_evidence = any(
                tick.startswith(("runtime:", "map:", "evidence:"))
                or tick.endswith(".json")
                for tick in ticks
            )
            if cited_map or cited_evidence:
                continue
            if re.search(r"evidence\s*:", blob, re.IGNORECASE):
                continue
            problems.append(
                f"{rel} {heading} cites neither a map id nor an evidence ref"
            )
    return problems


def cmd_check(args: Namespace) -> int:
    out = _out_dir(getattr(args, "out", None))
    problems = check_tree(out)
    style = guide.style_for()
    if not problems:
        suggestion = guide.next_for("check", "clean", args, out=out)
        guide.emit([f"check: clean ({guide.rel_to_cwd(out)})"], guide.render_next(suggestion, style))
        return 0
    suggestion = guide.next_for("check", "problems", args, out=out)
    guide.emit(
        [f"  {problem}" for problem in problems],
        [f"check: {len(problems)} problem(s)."],
        guide.render_next(suggestion, style),
    )
    return 1
