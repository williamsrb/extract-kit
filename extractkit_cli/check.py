"""`extractkit check` — schemas, FR-10 descriptor coverage, OpenAPI x-source."""

from __future__ import annotations

import re
from argparse import Namespace
from functools import lru_cache
from pathlib import Path

import yaml

from . import context, guide, result, schema
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
CONSTITUTION_FILE = "spec-kit/constitution/project.md"
CONSTITUTION_SECTIONS = (
    "Product", "Stack", "Architecture", "Conventions", "Integrations", "Delivery",
    "Invariants", "Open questions",
)
SPEC_REVIEW_FILE = "reports/spec-review.md"
SPEC_REVIEW_SEVERITIES = ("high", "medium", "low")
SPEC_REVIEW_FIX_IN = ("extractor", "rules/review.md", "spec.capabilities", "source")
SPEC_REVIEW_FIELDS = ("Spec", "Severity", "Fix in", "Evidence")
FINDING_HEADING = re.compile(r"^###\s+(SR-\d+)\b.*$", re.MULTILINE)
SPEC_PATH = re.compile(r"spec-kit/specs/[^/\s`]+/spec\.md")
BUSINESS_SECTIONS = (
    "Purpose and audience", "Actors", "Capabilities", "Business flow",
    "Business rules by capability", "Glossary", "Integrations", "Open questions",
)
EVIDENCE_REFS = re.compile(r"^\s*Evidence\s*:(.*)$", re.MULTILINE)
BACKTICKED = re.compile(r"`([^`]+)`")
SOURCE_REF = re.compile(r"^(.+):(\d+)$")
RULE_ID = re.compile(r"VR-[0-9a-f]{10}")
CAPABILITIES_FILE = "business/capabilities.json"
PLATFORM_CAPABILITY = "platform-and-operations"
CAPABILITY_SECTIONS = (
    "User Scenarios & Testing", "Requirements", "Key Entities", "Success Criteria", "Edge Cases", "Evidence",
)
DOMAIN_SECTIONS = (
    "State machines", "Formulas", "External calls", "Emails", "Scheduled and external jobs",
    "Idempotency and retries",
)
DO_NOT_PORT_FILE = "reports/do-not-port.md"
DO_NOT_PORT_SECTIONS = ("Security behavior", "Defects", "Dead code")
MAX_SPEC_BYTES = 60 * 1024
FR_BULLET = re.compile(r"^\s*[-*]\s+\*{0,2}(FR-\d{3,})\*{0,2}\s*[:.\-]\s*(.*)$")
CALL_GRAPH_FR = re.compile(r"\b(?:Calls|Exports)\s+`")
DNP_ENTRY = re.compile(r"^\s*[-*]\s+\*{0,2}(DNP-\d+)\*{0,2}\b(.*)$")


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
    stat = path.stat()
    return 1 <= int(match.group(2)) <= _line_count(path, stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=4096)
def _line_count(path: Path, _mtime_ns: int, _size: int) -> int:
    with path.open("rb") as handle:
        return sum(1 for _ in handle)


def _manifest_source(out: Path) -> Path | None:
    manifest_path = out / "MANIFEST.yaml"
    source_raw = (
        (load_yaml(manifest_path, "MANIFEST.yaml").get("source") or {}).get("path")
        if manifest_path.is_file() else None
    )
    return Path(source_raw) if source_raw else None


def _business_gaps(out: Path) -> list[str]:
    """Problems in `business/BUSINESS.md`. An absent file is not a problem."""
    path = out / BUSINESS_FILE
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    sections = _split_h2(text)
    problems = _evidenced_doc_gaps(out, BUSINESS_FILE, text, sections, BUSINESS_SECTIONS)
    surface_ids = _ids_in_maps(out)
    rule_ids = _rule_ids(out)
    headings = _capabilities(sections.get("Capabilities", ""))
    for title, body in headings:
        cited = set(BACKTICKED.findall(body)) | set(RULE_ID.findall(body))
        if not cited & (surface_ids | rule_ids):
            problems.append(f"{BUSINESS_FILE} capability '{title}' cites no rule id or surface id")
    problems.extend(_capability_list_gaps(out, [title for title, _body in headings]))
    return problems


def _capability_list_gaps(out: Path, headings: list[str]) -> list[str]:
    """`business/capabilities.json` must list exactly the capabilities BUSINESS.md names."""
    path = out / CAPABILITIES_FILE
    if not path.is_file():
        return [f"{CAPABILITIES_FILE} is missing: the business task writes it beside {BUSINESS_FILE}"]
    try:
        payload = load_json(path, CAPABILITIES_FILE)
        schema.validate(payload, "capabilities", what=CAPABILITIES_FILE)
    except ExtractkitError as exc:
        return [str(exc)]
    rows = payload["capabilities"]
    problems: list[str] = []
    titles = {row["title"].strip().casefold(): row["id"] for row in rows}
    for title in headings:
        if title.strip().casefold() not in titles:
            problems.append(f"{CAPABILITIES_FILE} has no row for the capability '{title}' of {BUSINESS_FILE}")
    wanted = {title.strip().casefold() for title in headings}
    problems.extend(
        f"{CAPABILITIES_FILE} row '{row['id']}' ({row['title']}) has no '### {row['title']}' heading in {BUSINESS_FILE}"
        for row in rows if row["title"].strip().casefold() not in wanted
    )
    ids = [row["id"] for row in rows]
    problems.extend(f"{CAPABILITIES_FILE} lists the id '{i}' twice" for i in sorted({i for i in ids if ids.count(i) > 1}))
    if PLATFORM_CAPABILITY not in ids:
        problems.append(f"{CAPABILITIES_FILE} has no '{PLATFORM_CAPABILITY}' capability for the cross-cutting facts")
    return problems


def _capability_ids(out: Path) -> list[str]:
    path = out / CAPABILITIES_FILE
    if not path.is_file():
        return []
    try:
        return [str(row["id"]) for row in load_json(path, CAPABILITIES_FILE).get("capabilities") or []]
    except (ExtractkitError, KeyError, TypeError):
        return []


def _known_refs(out: Path) -> set[str]:
    return _ids_in_maps(out) | _context_ids(out) | _rule_ids(out)


def _items(text: str) -> list[tuple[int, str]]:
    """Bullet items with their first line number: a bullet and the indented lines that continue it."""
    items: list[tuple[int, list[str]]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if re.match(r"^\s*[-*]\s+\S", line):
            items.append((number, [line.strip()]))
        elif line.strip() and items and line.startswith((" ", "\t")):
            items[-1][1].append(line.strip())
    return [(number, " ".join(lines)) for number, lines in items]


def _inline_refs(item: str) -> list[str]:
    """Refs after the last `Evidence:` of a bullet: backticked, else comma separated."""
    _, sep, tail = item.rpartition("Evidence:")
    if not sep:
        return []
    return BACKTICKED.findall(tail) or [part.strip() for part in tail.split(",") if part.strip()]


def _capability_spec_gaps(out: Path) -> list[str]:
    """`spec-kit/specs/<capability>/spec.md`: Spec Kit sections, MUST requirements, evidence, size."""
    root = out / "spec-kit" / "specs"
    specs = sorted(root.glob("*/spec.md")) if root.is_dir() else []
    problems: list[str] = []
    known = _known_refs(out)
    source = _manifest_source(out)
    for spec in specs:
        rel = spec.relative_to(out).as_posix()
        raw = spec.read_bytes()
        if len(raw) > MAX_SPEC_BYTES:
            problems.append(f"{rel} is {len(raw)} bytes, over the {MAX_SPEC_BYTES} byte limit; keep the P1 stories and cut")
        text = raw.decode("utf-8", errors="replace")
        sections = _split_h2(text)
        problems.extend(f"{rel} is missing the section '## {t}'" for t in CAPABILITY_SECTIONS if t not in sections)
        frs: dict[str, str] = {}
        for _number, item in _items(sections.get("Requirements", "")):
            match = FR_BULLET.match(item)
            if match:
                frs[match.group(1)] = match.group(2)
        if "Requirements" in sections and not frs:
            problems.append(f"{rel} has no '- **FR-###**: ...' requirement under '## Requirements'")
        for ident, body in frs.items():
            if "MUST" not in body:
                problems.append(f"{rel} {ident} does not use MUST")
            if CALL_GRAPH_FR.search(body):
                problems.append(f"{rel} {ident} reads as a call graph (Calls/Exports), not as behavior")
        appendix = {m.group(1): m.group(2) for _n, i in _items(sections.get("Evidence", ""))
                    if (m := FR_BULLET.match(i))}
        for ident in frs:
            refs = [r for r in BACKTICKED.findall(appendix.get(ident, "")) if r]
            if not refs:
                problems.append(f"{rel} {ident} has no evidence in '## Evidence'")
            problems.extend(
                f"{rel} {ident} Evidence ref `{ref}` does not resolve to a source path:line, a map id or a rule id"
                for ref in refs if ref not in known and not _source_ref_resolves(ref, source)
            )
    return problems


def _domain_behavior_gaps(out: Path) -> list[str]:
    """`domain/<capability>.md`: the sections, and a source `path:line` on every bullet."""
    root = out / "domain"
    files = sorted(p for p in root.glob("*.md")) if root.is_dir() else []
    problems: list[str] = []
    source = _manifest_source(out)
    for path in files:
        rel = path.relative_to(out).as_posix()
        text = path.read_text(encoding="utf-8")
        sections = _split_h2(text)
        problems.extend(f"{rel} is missing the section '## {t}'" for t in DOMAIN_SECTIONS if t not in sections)
        for number, item in _items(text):
            refs = _inline_refs(item)
            if not refs:
                problems.append(f"{rel}:{number} bullet has no `Evidence:` ref")
            problems.extend(
                f"{rel}:{number} Evidence ref `{ref}` does not resolve to a path:line in the source"
                for ref in refs if not _source_ref_resolves(ref, source)
            )
    return problems


def _do_not_port_gaps(out: Path) -> list[str]:
    """`reports/do-not-port.md`: evidence on every entry, and no capability FR that cites a listed item."""
    path = out / DO_NOT_PORT_FILE
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    sections = _split_h2(text)
    problems = [f"{DO_NOT_PORT_FILE} is missing the section '## {t}'" for t in DO_NOT_PORT_SECTIONS if t not in sections]
    known_rules = _rule_ids(out)
    source = _manifest_source(out)
    capabilities = set(_capability_ids(out))
    listed: dict[str, str] = {}
    for title in DO_NOT_PORT_SECTIONS:
        for _number, item in _items(sections.get(title, "")):
            match = DNP_ENTRY.match(item)
            if not match:
                continue
            ident, refs = match.group(1), _inline_refs(item)
            if not refs:
                problems.append(f"{DO_NOT_PORT_FILE} {ident} has no `Evidence:` ref")
            for ref in refs:
                if ref in known_rules or _source_ref_resolves(ref, source):
                    if title in ("Defects", "Dead code"):
                        listed[ref] = ident
                else:
                    problems.append(f"{DO_NOT_PORT_FILE} {ident} Evidence ref `{ref}` does not resolve")
            cap = re.search(r"Capability:\s*`([^`]+)`", item)
            if capabilities and (cap is None or cap.group(1) not in capabilities | {PLATFORM_CAPABILITY}):
                problems.append(f"{DO_NOT_PORT_FILE} {ident} names no capability from {CAPABILITIES_FILE}")
    root = out / "spec-kit" / "specs"
    for spec in sorted(root.glob("*/spec.md")) if root.is_dir() else []:
        sections_s = _split_h2(spec.read_text(encoding="utf-8"))
        for _number, item in _items(sections_s.get("Requirements", "")) + _items(sections_s.get("Evidence", "")):
            for ref in {*BACKTICKED.findall(item), *RULE_ID.findall(item)} & set(listed):
                match = FR_BULLET.match(item)
                where = match.group(1) if match else "a requirement"
                problems.append(
                    f"{spec.relative_to(out).as_posix()} {where} cites `{ref}`, which {DO_NOT_PORT_FILE} "
                    f"lists as {listed[ref]}: do not port it"
                )
    return problems


CREDENTIAL_KEY = re.compile(
    r"""["']?(?P<key>[\w.\-]*(?:password|passwd|secret|token|api[_-]?key|shared[_-]?key)[\w.\-]*)["']?\s*[=:]\s*"""
    r"""["']?(?P<value>[^\s"'#,}<]{8,})""",
    re.IGNORECASE,
)
CREDENTIAL_XML = re.compile(
    r"<(?P<key>[\w.\-]*(?:password|passwd|secret|token|api[_-]?key|shared[_-]?key)[\w.\-]*)>\s*(?P<value>[^<\s]{8,})\s*</",
    re.IGNORECASE,
)
CONFIG_SUFFIXES = {".cfg", ".properties", ".env", ".yml", ".yaml", ".json", ".xml", ".toml", ".ini", ".conf", ".gradle"}
PLACEHOLDER = re.compile(r"^(?:\$\{|\$\(|%\(|<|\{\{|\*+$|x+$|changeme|null$|true$|false$|undefined$)", re.IGNORECASE)


def _credential_literals(source: Path) -> dict[str, tuple[str, str]]:
    """`value -> (key, path:line)` for credential-looking keys in the source's config files."""
    from . import scope

    found: dict[str, tuple[str, str]] = {}
    for path in scope.iter_files(source):
        name = path.name.lower()
        if path.suffix.lower() not in CONFIG_SUFFIXES and not name.startswith(".env"):
            continue
        if name in {"package-lock.json", "yarn.lock", "composer.lock"} or path.stat().st_size > 1_000_000:
            continue
        rel = path.relative_to(source).as_posix()
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for pattern in (CREDENTIAL_KEY, CREDENTIAL_XML):
                for match in pattern.finditer(line):
                    value = match.group("value")
                    if not PLACEHOLDER.match(value):
                        found.setdefault(value, (match.group("key"), f"{rel}:{number}"))
    return found


def _secrets_gaps(out: Path) -> list[str]:
    """No credential literal of the source's config may appear in any sidecar Markdown. Names the key, never the value."""
    source = _manifest_source(out)
    if source is None or not source.is_dir():
        return []
    literals = _credential_literals(source)
    if not literals:
        return []
    problems: list[str] = []
    for path in sorted(out.rglob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for value, (key, where) in literals.items():
            if value in text:
                problems.append(
                    f"{path.relative_to(out).as_posix()} holds the literal of credential key `{key}` "
                    f"(from {where}); write the key and path:line, never the value"
                )
                break
    return problems


def _constitution_gaps(out: Path) -> list[str]:
    """Problems in `spec-kit/constitution/project.md`. An absent file is not a problem."""
    path = out / CONSTITUTION_FILE
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    sections = _split_h2(text)
    problems = _evidenced_doc_gaps(out, CONSTITUTION_FILE, text, sections, CONSTITUTION_SECTIONS)
    problems.extend(
        f"{CONSTITUTION_FILE} section '## {title}' has no `Evidence:` line"
        for title in CONSTITUTION_SECTIONS
        if title != "Open questions" and title in sections and not EVIDENCE_LINE.search(sections[title])
    )
    return problems


def _evidenced_doc_gaps(out: Path, rel: str, text: str, sections: dict[str, str],
                        required: tuple[str, ...]) -> list[str]:
    """Missing H2 sections, unresolved `Evidence:` refs and inferred paragraphs with no evidence."""
    problems = [f"{rel} is missing the section '## {title}'" for title in required if title not in sections]
    known = _ids_in_maps(out) | _context_ids(out) | _rule_ids(out)
    source = _manifest_source(out)
    for ref in dict.fromkeys(_evidence_refs(text)):
        if ref in known or _source_ref_resolves(ref, source):
            continue
        if RULE_ID.fullmatch(ref):
            problems.append(f"{rel} cites rule {ref}, which is not in rules/view-rules.json")
        else:
            problems.append(
                f"{rel} Evidence ref `{ref}` does not resolve to a source path:line, "
                "a map id, a context id or a rule id"
            )
    for title, body in sections.items():
        where = f"section '## {title}'" if title else "text before the first section"
        problems.extend(
            f"{rel} {where} has an {INFERRED} paragraph without an `Evidence:` line"
            for _ in _unevidenced_inferred(body)
        )
    return problems


def _field_value(block: str, name: str) -> str | None:
    match = re.search(rf"^\s*{re.escape(name)}\s*:[ \t]*(.*)$", block, re.MULTILINE)
    return match.group(1).strip() if match else None


def _spec_review_gaps(out: Path) -> list[str]:
    """Problems in `reports/spec-review.md`. An absent file is not a problem."""
    path = out / SPEC_REVIEW_FILE
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    problems: list[str] = []
    if not re.search(r"^# Spec review\s*$", text, re.MULTILINE):
        problems.append(f"{SPEC_REVIEW_FILE} is missing the H1 '# Spec review'")
    headings = list(FINDING_HEADING.finditer(text))
    if not headings:
        if not re.search(r"^No findings\.\s*$", text, re.MULTILINE):
            problems.append(f"{SPEC_REVIEW_FILE} has no '### SR-<n>' finding and no 'No findings.' line")
        return problems
    known = _ids_in_maps(out) | _context_ids(out) | _rule_ids(out)
    source = _manifest_source(out)
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        block = text[heading.end():end]
        finding = heading.group(1)
        values = {name: _field_value(block, name) for name in SPEC_REVIEW_FIELDS}
        problems.extend(
            f"{SPEC_REVIEW_FILE} {finding} has no `{name}:` line"
            for name, value in values.items() if not value
        )
        severity, fix_in, spec = values["Severity"], values["Fix in"], values["Spec"]
        if severity and severity not in SPEC_REVIEW_SEVERITIES:
            problems.append(
                f"{SPEC_REVIEW_FILE} {finding} Severity `{severity}` is not one of "
                f"{', '.join(SPEC_REVIEW_SEVERITIES)}"
            )
        if fix_in and fix_in not in SPEC_REVIEW_FIX_IN:
            problems.append(
                f"{SPEC_REVIEW_FILE} {finding} Fix in `{fix_in}` is not one of "
                f"{', '.join(SPEC_REVIEW_FIX_IN)}"
            )
        if spec:
            spec_path = SPEC_PATH.search(spec)
            if spec_path is None or not (out / spec_path.group(0)).is_file():
                problems.append(
                    f"{SPEC_REVIEW_FILE} {finding} Spec `{spec}` is not a "
                    "spec-kit/specs/<slug>/spec.md in this sidecar"
                )
        for ref in dict.fromkeys(_evidence_refs(block)):
            if ref not in known and not _source_ref_resolves(ref, source):
                problems.append(
                    f"{SPEC_REVIEW_FILE} {finding} Evidence ref `{ref}` does not resolve to a source "
                    "path:line, a map id, a context id or a rule id"
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


EVIDENCE_DIR = "spec-kit/evidence"


def _evidence_specs(out: Path) -> list[Path]:
    """The per-context evidence specs `spec.kit` writes: `spec-kit/evidence/<context>.md`."""
    root = out / EVIDENCE_DIR
    return sorted(p for p in root.glob("*.md") if not p.name.endswith(".tasks.md")) if root.is_dir() else []


def _rule_gaps(out: Path) -> list[str]:
    """Business view rules that no evidence-spec FR cites and that review.md does not drop.

    Server-side rules with no component have no surface to cite them; the domain files carry them.
    """
    from steps.core import view_rules

    rules_path = out / "rules" / "view-rules.json"
    specs = _evidence_specs(out)
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
        and (rule.get("scope") != "server" or rule.get("component"))
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
    problems.extend(_capability_spec_gaps(out))
    problems.extend(_domain_behavior_gaps(out))
    problems.extend(_do_not_port_gaps(out))
    problems.extend(_secrets_gaps(out))
    problems.extend(_constitution_gaps(out))
    problems.extend(_spec_review_gaps(out))
    problems.extend(context.grounding_gaps(out))

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
    if not (out / EVIDENCE_DIR).is_dir():
        return []
    problems: list[str] = []
    specs = _evidence_specs(out)
    if not specs:
        problems.append(f"{EVIDENCE_DIR} exists under {out} but has no <context>.md")
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


NAMED_CHECKS = {
    "context_grounded": context.grounding_gaps,
    "business": _business_gaps,
    "constitution": _constitution_gaps,
    "spec_fr": _spec_fr_gaps,
    "capability_spec": _capability_spec_gaps,
    "domain_behavior": _domain_behavior_gaps,
    "do_not_port": _do_not_port_gaps,
    "secrets": _secrets_gaps,
    "spec_review": _spec_review_gaps,
}


def cmd_check(args: Namespace) -> int:
    out = _out_dir(getattr(args, "out", None))
    problems = check_tree(out)
    style = guide.style_for()
    if not problems:
        suggestion = guide.next_for("check", "clean", args, out=out)
        result.note_run(sidecar=out, source=guide.sidecar_source(out))
        guide.emit([f"check: clean ({guide.rel_to_cwd(out)})"], guide.render_next(suggestion, style))
        return 0
    suggestion = guide.next_for("check", "problems", args, out=out)
    result.note_run(sidecar=out, source=guide.sidecar_source(out))
    result.note_problems(problems)
    result.note_error("check_failed", f"{len(problems)} problem(s) in {out}", "fix the listed problems, then re-run check")
    guide.emit(
        [f"  {problem}" for problem in problems],
        [f"check: {len(problems)} problem(s)."],
        guide.render_next(suggestion, style),
    )
    return 1
