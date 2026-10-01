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
EVIDENCE_LINE = re.compile(r"^\s*Evidence\s*:\s*\S", re.MULTILINE)
INFERRED = "`_(inferred)_`"
BUSINESS_FILE = "business/BUSINESS.md"
BUSINESS_SECTIONS = (
    "Purpose and audience", "Actors", "Capabilities", "Business flow",
    "Business rules by capability", "Glossary", "Integrations", "Open questions",
)
EVIDENCE_REFS = re.compile(r"^\s*Evidence\s*:(.*)$", re.MULTILINE)
BACKTICKED = re.compile(r"`([^`]+)`")
SOURCE_REF = re.compile(r"^(.+):(\d+)$")
RULE_ID = re.compile(r"VR-[0-9a-f]{10}")


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


def _ids_in_maps(out: Path) -> set[str]:
    """Ids of the surfaces, components, types and routes in the map files."""
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
            found.update(
                item["id"] for item in items
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            )
    return found


def _context_ids(out: Path) -> set[str]:
    path = out / "map" / "bounded-contexts.json"
    if not path.is_file():
        return set()
    contexts = load_json(path, "map/bounded-contexts.json").get("contexts") or []
    return {c["id"] for c in contexts if isinstance(c, dict) and isinstance(c.get("id"), str)}


def _rule_ids(out: Path) -> set[str]:
    path = out / "rules" / "view-rules.json"
    if not path.is_file():
        return set()
    rules = load_json(path, "rules/view-rules.json").get("rules") or []
    return {r["id"] for r in rules if isinstance(r, dict) and isinstance(r.get("id"), str)}


def _split_h2(text: str) -> dict[str, str]:
    """H2 title to the section body. Text before the first H2 is under ''."""
    sections: dict[str, list[str]] = {"": []}
    current = ""
    for line in text.splitlines():
        match = re.match(r"^##\s+(.+?)\s*#*\s*$", line)
        if match:
            current = match.group(1)
            sections.setdefault(current, [])
        else:
            sections[current].append(line)
    return {title: "\n".join(lines) for title, lines in sections.items()}


def _capabilities(section: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, list[str]]] = []
    for line in section.splitlines():
        match = re.match(r"^###\s+(.+?)\s*$", line)
        if match:
            blocks.append((match.group(1), []))
        elif blocks:
            blocks[-1][1].append(line)
    return [(title, "\n".join(lines)) for title, lines in blocks]


def _evidence_refs(text: str) -> list[str]:
    refs: list[str] = []
    for tail in EVIDENCE_REFS.findall(text):
        ticked = BACKTICKED.findall(tail)
        refs.extend(ticked or [part.strip() for part in tail.split(",") if part.strip()])
    return refs


def _source_ref_resolves(ref: str, source: Path | None) -> bool:
    match = SOURCE_REF.match(ref)
    if match is None or source is None:
        return False
    path = (source / match.group(1)).resolve()
    if not path.is_file() or not path.is_relative_to(source.resolve()):
        return False
    with path.open("rb") as handle:
        lines = sum(1 for _ in handle)
    return 1 <= int(match.group(2)) <= lines


def _business_gaps(out: Path) -> list[str]:
    """Problems in `business/BUSINESS.md`. An absent file is not a problem."""
    path = out / BUSINESS_FILE
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    sections = _split_h2(text)
    problems = [
        f"{BUSINESS_FILE} is missing the section '## {title}'"
        for title in BUSINESS_SECTIONS if title not in sections
    ]
    surface_ids = _ids_in_maps(out)
    rule_ids = _rule_ids(out)
    known = surface_ids | _context_ids(out) | rule_ids
    manifest_path = out / "MANIFEST.yaml"
    source_raw = (
        (load_yaml(manifest_path, "MANIFEST.yaml").get("source") or {}).get("path")
        if manifest_path.is_file() else None
    )
    source = Path(source_raw) if source_raw else None
    for ref in dict.fromkeys(_evidence_refs(text)):
        if ref in known or _source_ref_resolves(ref, source):
            continue
        if RULE_ID.fullmatch(ref):
            problems.append(f"{BUSINESS_FILE} cites rule {ref}, which is not in rules/view-rules.json")
        else:
            problems.append(
                f"{BUSINESS_FILE} Evidence ref `{ref}` does not resolve to a source path:line, "
                "a map id, a context id or a rule id"
            )
    for title, body in _capabilities(sections.get("Capabilities", "")):
        cited = set(BACKTICKED.findall(body)) | set(RULE_ID.findall(body))
        if not cited & (surface_ids | rule_ids):
            problems.append(f"{BUSINESS_FILE} capability '{title}' cites no rule id or surface id")
    for title, body in sections.items():
        where = f"section '## {title}'" if title else "text before the first section"
        problems.extend(
            f"{BUSINESS_FILE} {where} has an {INFERRED} paragraph without an `Evidence:` line"
            for _ in _unevidenced_inferred(body)
        )
    return problems


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


def _template_gaps(out: Path) -> list[str]:
    """Template files without a component surface, and surfaces that are not spec-ready."""
    templates_path = out / "inventory" / "templates.json"
    components_path = out / "map" / "component-map.json"
    if not templates_path.is_file() or not components_path.is_file():
        return []
    components = load_json(components_path, "map/component-map.json").get("components") or []
    mapped = {
        (c.get("template") or {}).get("file") for c in components if isinstance(c, dict)
    }
    problems: list[str] = []
    for entry in load_json(templates_path, "inventory/templates.json").get("files") or []:
        if entry["path"] not in mapped:
            problems.append(
                f"template {entry['path']} is in inventory/templates.json but maps to no component surface"
            )
    for component in components:
        template = component.get("template") if isinstance(component, dict) else None
        if template is None:
            continue
        missing = [
            name for name, present in (
                ("entry", bool(component.get("entry"))),
                ("inputs", isinstance(template.get("inputs"), list)),
                ("children", all(c.get("status") for c in template.get("children") or [])),
                ("dataSource", bool(template.get("dataSource"))),
                ("status", bool(component.get("status"))),
            ) if not present
        ]
        if missing:
            problems.append(
                f"component {component.get('id')} is not spec-ready: missing {', '.join(missing)}"
            )
    return problems


def _rule_gaps(out: Path) -> list[str]:
    """Business view rules that no spec FR cites and that review.md does not drop."""
    from steps.core import view_rules

    rules_path = out / "rules" / "view-rules.json"
    specs = sorted((out / "spec-kit" / "specs").rglob("spec.md")) if (out / "spec-kit" / "specs").is_dir() else []
    if not rules_path.is_file() or not specs:
        return []
    review = out / "rules" / "review.md"
    dropped = {
        ident for ident, row in view_rules.parse_review(review.read_text(encoding="utf-8")).items()
        if row["outOfScope"]
    } if review.is_file() else set()
    cited = "\n".join(spec.read_text(encoding="utf-8") for spec in specs)
    return [
        f"business rule {rule['id']} ({rule['source']}) is not cited in any spec FR and not marked "
        "out-of-scope in rules/review.md"
        for rule in load_json(rules_path, "rules/view-rules.json").get("rules") or []
        if rule["bucket"] == "business" and rule["id"] not in dropped and rule["id"] not in cited
    ]


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
        ("inventory/controllers.json", "controllers"),
        ("inventory/templates.json", "templates"),
        ("rules/view-rules.json", "view-rules"),
        ("inventory/content-volume.json", "content-volume"),
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

    problems.extend(_template_gaps(out))
    problems.extend(_rule_gaps(out))
    problems.extend(_spec_fr_gaps(out))
    problems.extend(_business_gaps(out))

    return problems


def _unevidenced_inferred(section: str) -> list[str]:
    """Inferred paragraphs with no `Evidence:` line in them or right after them."""
    paragraphs = [p for p in re.split(r"\n\s*\n", section) if p.strip()]
    bad: list[str] = []
    for index, paragraph in enumerate(paragraphs):
        if "_(inferred)_" not in paragraph or EVIDENCE_LINE.search(paragraph):
            continue
        following = paragraphs[index + 1] if index + 1 < len(paragraphs) else ""
        if not EVIDENCE_LINE.match(following):
            bad.append(paragraph)
    return bad


def _spec_fr_gaps(out: Path) -> list[str]:
    specs_root = out / "spec-kit" / "specs"
    if not specs_root.is_dir():
        return []
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
        preamble = ""
        for line in text.splitlines():
            if FR_HEADING.match(line.strip()):
                if current is not None:
                    sections.append((current, "\n".join(body)))
                else:
                    preamble = "\n".join(body)
                current = line.strip()
                body = []
            else:
                body.append(line)
        if current is not None:
            sections.append((current, "\n".join(body)))
        problems.extend(
            f"{rel} has an {INFERRED} paragraph without an `Evidence:` line before its first FR"
            for _ in _unevidenced_inferred(preamble)
        )
        if not sections:
            problems.append(f"{rel} has no FR headings")
            continue
        for heading, section in sections:
            if not EVIDENCE_LINE.search(section):
                problems.append(f"{rel} {heading} has no `Evidence:` line")
            problems.extend(
                f"{rel} {heading} has an {INFERRED} paragraph without an `Evidence:` line"
                for _ in _unevidenced_inferred(section)
            )
    return problems


NAMED_CHECKS = {"business": _business_gaps, "spec_fr": _spec_fr_gaps}


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
