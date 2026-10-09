"""core.templates — stack-neutral view-layer inventory into inventory/templates.json.

Detects the template and view engines of a checkout (FreeMarker, Thymeleaf, Mustache,
Handlebars, Pebble, React, Next.js, Angular, Vue, jQuery), scans each template file once
and records every fact with `path:line`. Later steps (component mapping, view rules)
read this file and never rescan. Stdlib only; the source tree is read-only.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable
from pathlib import Path

from extractkit_cli import schema, scope
from extractkit_cli.common import load_json
from steps.core.viewscan import controller, dead, detect, markup, script, server
from steps.enonic.descriptors import iter_resources_roots

RENDER_LIBS = ("thymeleaf", "mustache", "freemarker", "handlebars", "pebble")
SCHEMA_ID = "extractkit.templates/v1"


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


def _mark_dead(detection: detect.Detection, rel: str, text: str, scan: dict) -> None:
    """Flag predicates inside comments, constant-false branches and `th:if="false"` blocks."""
    if (
        detection.engine in markup.MARKUP_ENGINES and not rel.endswith((".ts", ".js", ".vue"))
        or detection.engine == "jquery" and rel.endswith((".html", ".htm"))
    ):
        spans = dead.markup_spans(text)
    else:
        spans = dead.js_spans(text)
    dead.mark(scan["predicates"], spans, rel)


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
        dead.mark(predicates, dead.js_spans(text), str(row["file"]))
        if predicates:
            found.append({"path": row["file"], "predicates": predicates})
    return found


# What a file written for each engine contains. A bound `.html` without any of it is static HTML
# the controller passes through the engine, not a template of that engine.
SYNTAX = {
    "thymeleaf": re.compile(r"(?<![\w-])th:\w+|\bdata-th-\w+|\[\[|\$\{|\*\{|#\{"),
    "freemarker": re.compile(r"<#|</#|<@|\$\{"),
    "mustache": re.compile(r"\{\{"),
    "handlebars": re.compile(r"\{\{"),
    "pebble": re.compile(r"\{\{|\{%"),
}
STATIC_REF = re.compile(r"""(?P<q>['"`])(?P<ref>[^'"`\s]+\.html?)(?:\?[^'"`]*)?(?P=q)""")
FETCH_HINT = re.compile(r"fetch|\.get\s*\(|\.load\s*\(|ajax|\burl\b|template|href|src|getResource|readText", re.IGNORECASE)

SERVER_DIRS = ("lib", "services", "tasks", "cron")
SERVER_SUFFIXES = {".js", ".es6", ".ts"}


def _server_predicates(source: Path, exclude: Iterable[str]) -> list[dict]:
    """Business conditions in server-side JS under each resources root's `lib`, `services`, `tasks`, `cron`."""
    found: list[dict] = []
    for root in iter_resources_roots(source, exclude):
        for name in SERVER_DIRS:
            base = root / name
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                if (
                    path.suffix not in SERVER_SUFFIXES or not path.is_file() or ".min." in path.name
                    or path.name.endswith(".d.ts") or scope.SKIP_DIRS.intersection(path.parts)
                    or path.stat().st_size > detect.MAX_BYTES
                ):
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                predicates = server.scan(text)
                if not predicates:
                    continue
                rel = detect.rel_path(source, path)
                dead.mark(predicates, dead.js_spans(text), rel)
                found.append({"path": rel, "predicates": predicates})
    return sorted(found, key=lambda row: row["path"])


def _static_html(
    source: Path, paths: list[Path], entries: list[dict], controllers: list[dict],
) -> list[dict]:
    """HTML files no engine owns but the code still loads: `resolve()`, includes, frontend fetches."""
    owned = {e["path"] for e in entries}
    html = {detect.rel_path(source, p): p for p in paths if p.suffix.lower() in (".html", ".htm")}
    found: dict[str, dict] = {}

    def add(path: str, via: str, file: str, line: int) -> None:
        row = found.setdefault(path, {"path": path, "via": [], "refs": []})
        if via not in row["via"]:
            row["via"].append(via)
        row["refs"].append({"file": file, "line": line})

    for row in controllers:
        folder = posixpath.dirname(str(row.get("file") or ""))
        for view in row.get("views") or []:
            ref = view.get("ref")
            target = posixpath.normpath(posixpath.join(folder, str(ref))) if ref else ""
            if view.get("via") == "resolve" and target in html and target not in owned:
                add(target, "resolve", str(row["file"]), int(view["line"]))
    for entry in entries:
        for child in entry["scan"]["children"]:
            ref = str(child["ref"]).strip("/")
            base = posixpath.dirname(entry["path"])
            for candidate in (posixpath.normpath(posixpath.join(base, ref + ".html")), ref + ".html"):
                hit = candidate if candidate in html else next(
                    (h for h in html if h.endswith("/" + candidate)), None,
                )
                if hit and hit not in owned:
                    add(hit, "include", entry["path"], int(child["line"]))
                    break
    by_name: dict[str, list[str]] = {}
    for rel in html:
        by_name.setdefault(posixpath.basename(rel), []).append(rel)
    for path in paths:
        if path.suffix.lower() not in (".js", ".ts", ".jsx", ".tsx", ".vue", ".html", ".htm"):
            continue
        if path.stat().st_size > detect.MAX_BYTES:
            continue
        rel = detect.rel_path(source, path)
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in STATIC_REF.finditer(text):
            line_start = text.rfind("\n", 0, match.start()) + 1
            context = text[max(line_start, match.start() - 80):match.start()]
            names = by_name.get(posixpath.basename(match.group("ref")), [])
            if len(names) == 1 and names[0] not in owned and names[0] != rel and FETCH_HINT.search(context):
                add(names[0], "fetch", rel, text.count("\n", 0, match.start()) + 1)
    for row in found.values():
        row["refs"] = [{"file": f, "line": n} for f, n in sorted({(r["file"], r["line"]) for r in row["refs"]})]
        row["via"].sort()
    return sorted(found.values(), key=lambda r: r["path"])


def collect(
    source: Path, bindings: dict[str, dict], react_refs: set[str], controllers: list[dict] | None = None,
    exclude: Iterable[str] = (),
) -> dict:
    paths = list(detect.iter_source_files(source, exclude))
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
        _mark_dead(found, rel, texts[rel], entry["scan"])
        pattern = SYNTAX.get(found.engine)
        if rel in bindings and rel.endswith((".html", ".htm")) and pattern and not pattern.search(texts[rel]):
            entry["syntax"] = "none"
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
        "server": _server_predicates(source, exclude),
        "static": _static_html(source, paths, entries, controllers or []),
        "coverage": {
            "scanned": scanned,
            "detected": len(entries),
            "skipped": skipped,
            "excluded": sorted(scope.SKIP_DIRS | set(exclude)),
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
        payload = collect(ctx.source, bindings, react_refs, rows, scope.of(ctx))  # type: ignore[attr-defined]
        schema.validate(payload, "templates", what="inventory/templates.json")
        ctx.write_json("inventory/templates.json", payload)  # type: ignore[attr-defined]

    def check(self, _ctx: object) -> list[str]:
        return []
