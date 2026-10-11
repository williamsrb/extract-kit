"""enonic.domain_packet — the facts about one source module, for the `domain.behavior` agent task.

A packet is deterministic and bounded: what a module exports, what it calls, which jobs and
listeners start it, which requests it reads and answers, and which rules sit in it. It is keyed
by source module and not by capability, because capabilities exist only after the `business`
agent task has run and this step runs before it. The agent maps modules to capabilities.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from extractkit_cli import schema, scope
from extractkit_cli.common import load_json
from steps.enonic.controllers import (
    SCRIPT_SUFFIXES,
    export_names,
    http_requests,
    scan_text,
)
from steps.enonic.descriptors import iter_resources_roots

SCHEMA_ID = "extractkit.domain-packet/v1"
INDEX_SCHEMA_ID = "extractkit.domain-packet-index/v1"
GROUPED = ("services", "tasks", "cron")
SOURCE_CAP = 5
ENTRY_KINDS = ("service", "task", "cron", "init", "external-caller")


def _is_source(path: Path) -> bool:
    return (
        path.is_file() and path.suffix in SCRIPT_SUFFIXES and ".min." not in path.name
        and not path.name.endswith(".d.ts") and not scope.SKIP_DIRS.intersection(path.parts)
    )


def module_of(rel_to_root: str) -> str | None:
    """`lib/modules/orders/a.js` -> `lib.modules.orders`; `services/x/x.js` -> `services`."""
    parts = rel_to_root.split("/")
    if parts[0] == "lib":
        if len(parts) >= 4 and parts[1] == "modules":
            return f"lib.modules.{parts[2]}"
        return f"lib.{parts[1]}" if len(parts) >= 3 else "lib"
    if parts[0] in GROUPED:
        return parts[0]
    if rel_to_root.rsplit(".", 1)[0] == "main":
        return "main"
    return None


def _group_files(source: Path, exclude: Iterable[str]) -> dict[str, list[Path]]:
    modules: dict[str, list[Path]] = {}
    for root in iter_resources_roots(source, exclude):
        for path in sorted(root.rglob("*")):
            if not _is_source(path):
                continue
            name = module_of(path.relative_to(root).as_posix())
            if name:
                modules.setdefault(name, []).append(path)
    return dict(sorted(modules.items()))


def _rel(source: Path, path: Path) -> str:
    return path.resolve().relative_to(source.resolve()).as_posix()


def _lib_module_id(ref: str) -> str:
    """`/lib/modules/orders/list` -> `lib.modules.orders`; the packet `module_of` puts that file in."""
    return module_of(ref.strip("/") + ".js") or ".".join(ref.strip("/").split("/")[:2])


def _without_credentials(url: str) -> str:
    """Drop userinfo and query values from a literal URL; the query keys stay."""
    parts = urlsplit(url)
    host = parts.netloc.rsplit("@", 1)[-1]
    query = "&".join(f"{k}=" for k, _ in parse_qsl(parts.query, keep_blank_values=True))
    return urlunsplit((parts.scheme, host, parts.path, query, ""))


def _file_facts(source: Path, path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    facts = scan_text(text)
    rel = _rel(source, path)
    return {
        "file": rel,
        "lines": text.count("\n") + 1,
        "exports": [{"name": e["name"], "line": e["line"]} for e in export_names(text)],
        "imports": facts["imports"],
        "calls": facts["calls"],
        "configKeys": facts["configKeys"],
        "i18n": facts["i18n"],
        "listeners": facts["listeners"],
        "http": [{**r, "url": _without_credentials(r["url"])} if "url" in r else r for r in http_requests(text)],
        "inputs": facts["inputs"],
        "responses": facts["responses"],
        "auth": facts["auth"],
    }


def _cap(sources: list[str]) -> list[str]:
    return sources[:SOURCE_CAP]


def _platform_calls(files: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[str]] = {}
    for item in files:
        for call in item["calls"]:
            if call["module"].startswith("/lib/xp/"):
                grouped.setdefault((call["module"], call["call"]), []).append(f"{item['file']}:{call['line']}")
    return [
        {"module": module, "call": name, "count": len(sources), "sources": _cap(sources)}
        for (module, name), sources in sorted(grouped.items())
    ]


def _uses(files: list[dict], own: str) -> list[dict]:
    grouped: dict[str, list[str]] = {}
    for item in files:
        for row in item["imports"]:
            if not row["module"].startswith("/lib/xp/"):
                grouped.setdefault(row["module"], []).append(f"{item['file']}:{row['line']}")
    rows = [
        {"module": module, "packet": _lib_module_id(module), "sources": _cap(sources)}
        for module, sources in sorted(grouped.items())
    ]
    return [row for row in rows if row["packet"] != own]


def _entry_points(surfaces: list[dict], module: str, files: set[str]) -> dict:
    """Jobs, listeners, external callers and services that reach this module."""
    jobs, listeners, callers = [], [], []
    for surface in surfaces:
        kind = surface.get("kind")
        entry = str(surface.get("entry") or "")
        starts = [c.get("call") for c in surface.get("starts") or []]
        reaches = any(_lib_module_id(str(call).split("#")[0]) == module for call in starts)
        if kind == "cron" and (reaches or entry in files):
            jobs.append({
                "id": surface["id"], "schedule": surface.get("schedule"), "tasks": surface.get("tasks") or [],
                "starts": [c for c in surface.get("starts") or []
                           if _lib_module_id(str(c.get("call")).split("#")[0]) == module] or surface.get("starts"),
                "source": entry,
            })
        elif kind == "init" and (reaches or entry in files):
            listeners.append({
                "id": surface["id"], "actions": surface.get("actions") or [],
                "listeners": (surface.get("behavior") or {}).get("listeners") or [], "source": entry,
            })
        elif kind == "external-caller" and module == "services" and surface.get("callers"):
            callers.append({
                "id": surface["id"], "source": entry, "targets": surface["callers"],
                "schedules": surface.get("schedules") or [],
            })
    return {"jobs": jobs, "listeners": listeners, "externalCallers": callers}


def _rules(rules: list[dict], files: set[str]) -> list[dict]:
    keep = ("id", "kind", "bucket", "effect", "scope", "expression", "source", "dead", "deadAt", "deadReason", "unreferenced")
    return [
        {k: rule[k] for k in keep if k in rule}
        for rule in rules
        if rule["source"].rsplit(":", 1)[0] in files
    ]


def build_packet(
    source: Path, module: str, paths: list[Path], surfaces: list[dict], rules: list[dict],
) -> dict:
    files = [_file_facts(source, path) for path in paths]
    names = {item["file"] for item in files}
    http = [
        {**row, "file": item["file"]} for item in files for row in item["http"]
    ]
    packet = {
        "schema": SCHEMA_ID,
        "module": module,
        "files": [{"path": i["file"], "lines": i["lines"]} for i in files],
        "exports": [
            {"file": i["file"], "name": e["name"], "line": e["line"]} for i in files for e in i["exports"]
        ],
        "uses": _uses(files, module),
        "platform": _platform_calls(files),
        "http": http,
        "configKeys": sorted({k["key"] for i in files for k in i["configKeys"]}),
        "i18n": sorted({k["key"] for i in files for k in i["i18n"]}),
        "requests": [
            {"file": i["file"], "inputs": i["inputs"], "responses": i["responses"], "auth": i["auth"]}
            for i in files if i["inputs"] or i["responses"] or i["auth"]
        ],
        **_entry_points(surfaces, module, names),
        "rules": _rules(rules, names),
    }
    return packet


class EnonicDomainPacketStep:
    id = "enonic.domain_packet"
    requires = ("map/project-map.json",)
    produces = ("domain/packet/INDEX.json",)
    required = True

    def plan(self, _ctx: object) -> list[str]:
        return ["write domain/packet/<module>.json and domain/packet/INDEX.json"]

    def run(self, ctx: object) -> None:
        source: Path = ctx.source  # type: ignore[attr-defined]
        surfaces = _json(ctx, "map/project-map.json", "surfaces")
        rules = _json(ctx, "rules/view-rules.json", "rules")
        index: list[dict] = []
        for module, paths in _group_files(source, scope.of(ctx)).items():
            packet = build_packet(source, module, paths, surfaces, rules)
            schema.validate(packet, "domain-packet", what=f"domain/packet/{module}.json")
            ctx.write_json(f"domain/packet/{module}.json", packet)  # type: ignore[attr-defined]
            size = ctx.rel(f"domain/packet/{module}.json").stat().st_size  # type: ignore[attr-defined]
            index.append({
                "module": module, "file": f"domain/packet/{module}.json", "bytes": size,
                "files": len(packet["files"]), "exports": len(packet["exports"]), "rules": len(packet["rules"]),
            })
        payload = {"schema": INDEX_SCHEMA_ID, "modules": index}
        schema.validate(payload, "domain-packet-index", what="domain/packet/INDEX.json")
        ctx.write_json("domain/packet/INDEX.json", payload)  # type: ignore[attr-defined]

    def check(self, _ctx: object) -> list[str]:
        return []


def _json(ctx: object, rel: str, key: str) -> list[dict]:
    path: Path = ctx.rel(rel)  # type: ignore[attr-defined]
    return [r for r in (load_json(path, rel).get(key) or []) if isinstance(r, dict)] if path.is_file() else []
