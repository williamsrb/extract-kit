"""core.templates — stack-neutral view-layer inventory into inventory/templates.json.

Detects the template and view engines of a checkout (FreeMarker, Thymeleaf, Mustache,
Handlebars, Pebble, React, Next.js, Angular, Vue, jQuery), scans each template file once
and records every fact with `path:line`. Later steps (component mapping, view rules)
read this file and never rescan. Stdlib only; the source tree is read-only.
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path

from extractkit_cli import schema
from extractkit_cli.common import load_json
from steps.core.viewscan import controller, detect, markup, script

RENDER_LIBS = ("thymeleaf", "mustache", "freemarker", "handlebars", "pebble")
SCHEMA_ID = "99x.extract.templates/v1"


def controller_rows(ctx: object) -> list[dict]:
    path: Path = ctx.rel("inventory/controllers.json")  # type: ignore[attr-defined]
    if not path.is_file():
        return []
    return list(load_json(path, "inventory/controllers.json").get("controllers") or [])


def render_bindings(rows: list[dict]) -> tuple[dict[str, dict], set[str]]:
    """Views a controller renders: `{path: {engine, controller, line}}` plus React4xp refs.

    Built from the rows of inventory/controllers.json, so it is empty when that step did not run.
    """
    bindings: dict[str, dict] = {}
    react_refs: set[str] = set()
    for row in rows:
        folder = posixpath.dirname(str(row.get("file") or ""))
        libs = [
            lib for imp in row.get("imports") or [] for lib in RENDER_LIBS
            if lib in str(imp.get("module") or "").lower()
        ]
        for view in row.get("views") or []:
            ref = view.get("ref")
            if view.get("via") == "React4xp" and ref:
                react_refs.add(str(ref).rsplit("/", 1)[-1])
            elif view.get("via") == "resolve" and ref and libs:
                target = posixpath.normpath(posixpath.join(folder, str(ref)))
                bindings.setdefault(target, {
                    "engine": libs[0], "controller": row.get("file"), "line": view.get("line"),
                })
    return bindings, react_refs


def _next_route(rel: str) -> str | None:
    parts = rel.rsplit(".", 1)[0].split("/")
    for marker in ("pages", "app"):
        if marker in parts:
            tail = parts[parts.index(marker) + 1:]
            if marker == "app":
                if not tail or tail[-1] != "page":
                    return None
                tail = tail[:-1]
            elif not tail or tail[0] in ("api", "_app", "_document"):
                return None
            elif tail[-1] == "index":
                tail = tail[:-1]
            return "/" + "/".join(tail)
    return None


def _scan(detection: detect.Detection, rel: str, text: str) -> dict:
    stem = posixpath.basename(rel).split(".", 1)[0]
    if detection.engine in markup.MARKUP_ENGINES and not rel.endswith((".ts", ".js", ".vue")):
        return markup.scan(detection.engine, text)
    if detection.engine == "jquery" and rel.endswith((".html", ".htm")):
        return markup.scan("jquery", text)
    return script.scan(detection.engine, text, stem)


def _tagged(scan: dict, path: str) -> dict:
    """Mark every fact of a companion template with its own file, so cites point there."""
    for key in ("inputs", "children", "slots", "outputs", "i18n", "assets", "dom", "predicates"):
        for row in scan[key]:
            row["file"] = path
    return scan


def _id_markers(selector: str) -> list[re.Pattern[str]]:
    patterns: list[re.Pattern[str]] = []
    for sign, name in re.findall(r"([#.])([\w-]+)", selector):
        if sign == "#":
            patterns.append(re.compile(rf"""\bid\s*=\s*["']{re.escape(name)}["']"""))
        else:
            patterns.append(re.compile(rf"""\bclass\s*=\s*["'][^"']*\b{re.escape(name)}\b"""))
    return patterns


def _bind_dom(entries: list[dict], texts: dict[str, str]) -> None:
    """Copy jQuery handler selectors onto the markup files that contain their id or class."""
    scripts = [e for e in entries if e["scan"]["dom"] and e["engine"] == "jquery" and e["role"] == "script"]
    markup_files = [e for e in entries if e["role"] == "template" and e["path"].endswith((".html", ".htm", ".ftl", ".ftlh", ".hbs", ".mustache", ".peb", ".vue"))]
    for js in scripts:
        for row in js["scan"]["dom"]:
            patterns = _id_markers(row["selector"])
            if not patterns:
                continue
            for target in markup_files:
                if any(p.search(texts[target["path"]]) for p in patterns):
                    target["scan"]["dom"].append({
                        "selector": row["selector"], "event": row["event"],
                        "script": js["path"], "line": row["line"],
                    })
    for target in markup_files:
        target["scan"]["dom"].sort(key=lambda r: (r["script"], r["line"], r["selector"]))


def _controller_predicates(source: Path, rows: list[dict]) -> list[dict]:
    found: list[dict] = []
    for row in rows:
        views = row.get("views") or []
        path = source / str(row.get("file") or "")
        if not views or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        predicates = controller.scan(text, max(int(v["line"]) for v in views))
        if predicates:
            found.append({"path": row["file"], "predicates": predicates})
    return found


def collect(
    source: Path, bindings: dict[str, dict], react_refs: set[str], controllers: list[dict] | None = None,
) -> dict:
    paths = list(detect.iter_source_files(source))
    project = detect.build_project(source, paths)
    detections: dict[str, detect.Detection] = {}
    texts: dict[str, str] = {}
    skipped: list[dict] = []
    scanned = 0
    for path in paths:
        rel = detect.rel_path(source, path)
        if path.suffix.lower() not in detect.SCANNED_SUFFIXES:
            continue
        if path.stat().st_size > detect.MAX_BYTES:
            skipped.append({"path": rel, "reason": f"larger than {detect.MAX_BYTES} bytes"})
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeDecodeError):
            skipped.append({"path": rel, "reason": "not readable as UTF-8 text"})
            continue
        scanned += 1
        found = detect.classify_file(rel, text, project, {k: v["engine"] for k, v in bindings.items()}, react_refs)
        if found:
            detections[rel] = found
            texts[rel] = text

    entries: list[dict] = []
    consumed: set[str] = set()
    for rel, found in sorted(detections.items()):
        if rel in consumed:
            continue
        entry = {
            "path": rel, "engine": found.engine, "framework": found.framework,
            "role": found.role, "confidence": found.confidence, "signals": found.signals,
            "scan": _scan(found, rel, texts[rel]),
        }
        if rel in bindings:
            entry["controller"] = {
                key: bindings[rel][key] for key in ("controller", "line")
            }
        if found.engine == "angular" and rel.endswith(".ts"):
            template = entry["scan"].get("meta", {}).get("templateUrl")
            if template:
                companion = posixpath.normpath(posixpath.join(posixpath.dirname(rel), template))
                if companion in detections:
                    consumed.add(companion)
                    entry["companions"] = [companion]
                    entry["scan"] = script.merge(
                        entry["scan"], _tagged(markup.scan("angular", texts[companion]), companion),
                    )
        if found.framework == "nextjs":
            route = _next_route(rel)
            if route:
                entry["route"] = route
        entries.append(entry)
    for rel in sorted(consumed):
        detections.pop(rel, None)
    entries = [e for e in entries if e["path"] not in consumed]
    _bind_dom(entries, texts)
    return {
        "schema": SCHEMA_ID,
        "engines": detect.engines_report(detections, project),
        "files": entries,
        "controllers": _controller_predicates(source, controllers or []),
        "coverage": {
            "scanned": scanned,
            "detected": len(entries),
            "skipped": skipped,
            "excluded": sorted(detect.EXCLUDE_DIRS),
        },
    }


class TemplatesStep:
    id = "core.templates"
    requires: tuple[str, ...] = ()
    produces = ("inventory/templates.json",)
    required = True

    def plan(self, _ctx: object) -> list[str]:
        return []

    def run(self, ctx: object) -> None:
        rows = controller_rows(ctx)
        bindings, react_refs = render_bindings(rows)
        payload = collect(ctx.source, bindings, react_refs, rows)  # type: ignore[attr-defined]
        schema.validate(payload, "templates", what="inventory/templates.json")
        ctx.write_json("inventory/templates.json", payload)  # type: ignore[attr-defined]

    def check(self, _ctx: object) -> list[str]:
        return []
