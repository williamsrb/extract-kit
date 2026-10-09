"""enonic.integrations — static harvest into field-minimal OpenAPI 3.1."""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Iterable
from pathlib import Path

from extractkit_cli import scope
from extractkit_cli.common import REPO_ROOT, load_json, write_text
from steps.enonic.controllers import HTTP_METHODS, http_requests
from steps.enonic.descriptors import collect_resources

ALL_FALLBACK = ("post", "get", "put", "delete", "patch", "head", "options", "trace")

HTTP_CLIENT_RE = re.compile(r"""['"]/lib/http-client['"]""")
SCRIPT_SRC_RE = re.compile(
    r"""\bsrc\s*=\s*['"](https?://[^'"]+)['"]""",
    re.IGNORECASE,
)
JS_SUFFIXES = {".js", ".es6", ".ts"}
TEMPLATE_DIR = REPO_ROOT / "templates" / "swagger-ui"


def _rel(source: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(source.resolve()).as_posix()
    except ValueError:
        return str(path)


def _line_no(text: str, match: re.Match[str]) -> int:
    return text[: match.start()].count("\n") + 1


def _comment_line(line: str) -> bool:
    stripped = line.strip()
    return (
        stripped.startswith(("<!--", "//", "*"))
        or "<!--/*" in line
    )


def harvest_outbound(source: Path, exclude: Iterable[str] = ()) -> list[dict]:
    ops: list[dict] = []
    for path in sorted(scope.iter_files(source, exclude)):
        if path.suffix not in JS_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        match = HTTP_CLIENT_RE.search(text)
        if not match:
            continue
        rel = _rel(source, path)
        requests = http_requests(text) or [{"line": _line_no(text, match)}]
        for index, request in enumerate(requests):
            suffix = "" if index == 0 else f"_{index + 1}"
            op = {
                "operationId": f"outbound_{path.stem}{suffix}",
                "summary": f"Outbound HTTP from {rel}",
                "path": f"/outbound/{path.stem}" + ("" if index == 0 else f"/{index + 1}"),
                "method": request.get("method") if request.get("method") in HTTP_METHODS else "post",
                "direction": "outbound",
                "x-source": [f"{rel}:{request['line']}"],
            }
            if "url" in request:
                op["x-url"] = request["url"]
            if "urlExpr" in request:
                op["x-url-expr"] = request["urlExpr"]
            ops.append(op)
    return ops


CALLER_SUFFIXES = {
    ".php", ".sh", ".bash", ".py", ".rb", ".pl", ".js", ".mjs", ".cjs", ".ts", ".yml", ".yaml", ".cron", ".crontab",
}
SERVICE_URL = re.compile(r"/_/service/(?P<app>[A-Za-z0-9_.\-]+)/(?P<name>[A-Za-z0-9_\-]+)")
CRON_FIELD = r"(?:\*|[\d,\-*/A-Za-z]+)"
CRON_LINE = re.compile(rf"^\s*(?P<spec>(?:@\w+|{CRON_FIELD}(?:\s+{CRON_FIELD}){{4}}))\s+(?P<cmd>\S.*)$")


def _is_crontab(path: Path) -> bool:
    return "crontab" in path.name.lower() or path.suffix == ".cron"


def _under_resources(path: Path) -> bool:
    parts = path.parts
    return any(parts[i:i + 3] == ("src", "main", "resources") for i in range(len(parts)))


def _schedules(folder_files: list[Path], names: set[str], source: Path) -> list[dict]:
    rows: list[dict] = []
    for path in folder_files:
        if not _is_crontab(path):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for index, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            match = CRON_LINE.match(line)
            if match and any(name in match.group("cmd") for name in names):
                rows.append({
                    "cron": match.group("spec"), "command": match.group("cmd").strip(),
                    "source": f"{_rel(source, path)}:{index}",
                })
    return rows


def collect_external_callers(source: Path, exclude: Iterable[str] = ()) -> list[dict]:
    """Non-XP files that call `/_/service/<app>/<name>`, with the crontab line that runs them."""
    files = [
        p for p in scope.iter_files(source, exclude)
        if not _under_resources(p.relative_to(source))
    ]
    rows: list[dict] = []
    for path in files:
        if path.suffix not in CALLER_SUFFIXES or _is_crontab(path):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        targets = [
            {"app": m.group("app"), "service": m.group("name"), "line": _line_no(text, m)}
            for m in SERVICE_URL.finditer(text)
        ]
        if not targets:
            continue
        siblings = [p for p in files if p.parent == path.parent]
        including = {
            p.name for p in siblings
            if p != path and not _is_crontab(p) and path.name in p.read_text(encoding="utf-8", errors="replace")
        }
        row = {
            "name": path.stem, "path": _rel(source, path), "app": targets[0]["app"],
            "targets": targets,
            "schedules": _schedules(siblings, {path.name, *including}, source),
        }
        if including:
            row["includedBy"] = sorted(including)
        rows.append(row)
    return rows


def harvest_browser_embed(source: Path, exclude: Iterable[str] = ()) -> list[dict]:
    ops: list[dict] = []
    seen: set[str] = set()
    for path in sorted(p for p in scope.iter_files(source, exclude) if p.suffix == ".html"):
        if "site" not in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = _rel(source, path)
        for index, line in enumerate(text.splitlines(), 1):
            if _comment_line(line):
                continue
            for match in SCRIPT_SRC_RE.finditer(line):
                url = match.group(1)
                key = f"{rel}:{url}"
                if key in seen:
                    continue
                seen.add(key)
                slug = re.sub(r"[^a-zA-Z0-9]+", "-", url.split("/")[-1]) or "embed"
                ops.append({
                    "operationId": f"browser_embed_{slug}",
                    "summary": f"Browser embed {url}",
                    "path": f"/browser-embed/{slug}",
                    "method": "get",
                    "direction": "browser-embed",
                    "x-source": [f"{rel}:{index}"],
                    "x-embed-url": url,
                })
    return ops


def _service_methods(controllers: list[dict], app: str, name: str) -> list[dict]:
    """Exported HTTP methods of one service controller, in source order."""
    for row in controllers:
        if row.get("kind") == "service" and row.get("app") == app and row.get("name") == name:
            return [m for m in row.get("methods") or [] if m.get("name") in HTTP_METHODS]
    return []


def harvest_inbound(
    source: Path, controllers: list[dict] | None = None, exclude: Iterable[str] = (),
) -> list[dict]:
    ops: list[dict] = []
    for resource in collect_resources(source, exclude):
        if resource.get("kind") != "service":
            continue
        app = resource.get("app") or "unknown"
        name = resource.get("name") or "service"
        path = resource.get("path") or ""
        found = _service_methods(controllers or [], app, name)
        exported = [(m["name"], m["line"]) for m in found] or [("post", None)]
        explicit = {name for name, _ in exported}
        for method, line in exported:
            suffix = "" if len(exported) == 1 else f"_{method}"
            op = {
                "operationId": f"inbound_{name}{suffix}",
                "summary": f"XP service {name}",
                "path": f"/_/service/{app}/{name}",
                "method": _all_method(explicit) if method == "all" else method,
                "direction": "inbound",
                "x-source": [f"{path}:1"],
            }
            if line is not None:
                op["x-source"] = [f"{_controller_file(controllers or [], app, name)}:{line}"]
            if method == "all":
                op["x-exported-method"] = "all"
            if found:
                op.update(_contract(_service_row(controllers or [], app, name)))
            ops.append(op)
    return ops


def _all_method(explicit: set[str]) -> str:
    """`all` serves every method without its own export; show it on the first such one."""
    return next((m for m in ALL_FALLBACK if m not in explicit), "post")


def _service_row(controllers: list[dict], app: str, name: str) -> dict:
    return next(
        (row for row in controllers
         if row.get("kind") == "service" and row.get("app") == app and row.get("name") == name),
        {},
    )


def _auth_modes(rows: list[dict]) -> list[str]:
    modes: list[str] = []
    for row in rows:
        value = row.get("value") or ""
        if row["kind"] == "role-check":
            mode = value if value.startswith("role:") else f"role:{value or '<computed>'}"
        elif row["kind"] == "elevated":
            mode = f"elevated:{value}"
        elif row["kind"] == "user-check":
            mode = "authenticated"
        else:
            continue
        if mode not in modes:
            modes.append(mode)
    return modes or ["none"]


def _contract(row: dict) -> dict:
    """Inputs, auth and response codes the controller scan recorded, cited by `path:line`."""
    file = row.get("file") or ""
    contract: dict = {
        "x-inputs": [
            {"in": i["source"], "name": i["name"], "x-source": f"{file}:{i['line']}"}
            for i in row.get("inputs") or []
        ],
        "x-auth": {
            "modes": _auth_modes(row.get("auth") or []),
            "scope": "controller",
            "x-source": [f"{file}:{a['line']}" for a in row.get("auth") or []],
        },
        "x-responses": [
            {"kind": r["kind"], "value": r["value"], "x-source": f"{file}:{r['line']}"}
            for r in row.get("responses") or []
        ],
    }
    return contract


def _controller_file(controllers: list[dict], app: str, name: str) -> str:
    return next(
        row["file"] for row in controllers
        if row.get("kind") == "service" and row.get("app") == app and row.get("name") == name
    )


_PARAM_IN = {"param": "query", "header": "header", "cookie": "cookie"}


def _parameters(inputs: list[dict]) -> tuple[list[dict], dict | None]:
    parameters: list[dict] = []
    fields: dict[str, dict] = {}
    seen: set[tuple[str, str]] = set()
    for item in inputs:
        if item["in"] == "body":
            fields.setdefault(item["name"], {"x-source": item["x-source"]})
            continue
        location = _PARAM_IN[item["in"]]
        if (location, item["name"]) in seen:
            continue
        seen.add((location, item["name"]))
        parameters.append({
            "name": item["name"], "in": location, "required": False,
            "schema": {"type": "string"}, "x-source": item["x-source"],
        })
    body = None
    if fields:
        body = {"content": {"application/json": {"schema": {"type": "object", "properties": fields}}}}
    return parameters, body


def _responses_block(rows: list[dict]) -> dict:
    codes = [r for r in rows if r["kind"] == "status"]
    types = [r["value"] for r in rows if r["kind"] == "contentType"]
    redirects = [r for r in rows if r["kind"] == "redirect"]
    if not codes and not redirects:
        return {"200": {"description": "Observed at the cited source line. Field-minimal."}}
    block: dict = {}
    for row in codes:
        block.setdefault(row["value"], {
            "description": f"Literal status at {row['x-source']}.", "x-source": row["x-source"],
        })
    for row in redirects:
        block.setdefault("3XX", {
            "description": f"Redirect to {row['value'] or 'a computed target'} at {row['x-source']}.",
            "x-source": row["x-source"],
        })
    if types and block:
        first = next((c for c in block if c.startswith("2")), next(iter(block)))
        block[first]["content"] = {t: {} for t in types}
    return block


def _operation_block(op: dict) -> dict:
    block = {
        "operationId": op["operationId"],
        "summary": op["summary"],
        "x-source": op["x-source"],
        "x-direction": op["direction"],
        "responses": _responses_block(op.get("x-responses") or []),
    }
    parameters, body = _parameters(op.get("x-inputs") or [])
    if parameters:
        block["parameters"] = parameters
    if body:
        block["requestBody"] = body
    if op.get("x-auth"):
        block["x-auth"] = op["x-auth"]
    for extra in ("x-embed-url", "x-url", "x-url-expr", "x-exported-method"):
        if op.get(extra):
            block[extra] = op[extra]
    return block


def build_openapi(
    source: Path, title: str, controllers: list[dict] | None = None, exclude: Iterable[str] = (),
) -> dict:
    ops = (
        harvest_inbound(source, controllers, exclude)
        + harvest_outbound(source, exclude)
        + harvest_browser_embed(source, exclude)
    )
    paths: dict[str, dict] = {}
    for op in ops:
        item = paths.setdefault(op["path"], {})
        item[op["method"]] = _operation_block(op)
    return {
        "openapi": "3.1.0",
        "info": {
            "title": title,
            "version": "extracted",
            "description": (
                "Field-minimal, source-traceable contracts. Observed URLs are "
                "metadata only, each tagged with the env it came from. "
                "Do not use Try it out against production."
            ),
        },
        "x-observed-endpoints": [],
        "paths": paths,
    }


def spec_js_body(spec: object) -> str:
    payload = json.dumps(spec, ensure_ascii=False)
    payload = payload.replace("<", "\\u003c")
    return "window.EXTRACTKIT_SPEC = " + payload + ";\n"


def write_swagger_spec(dest_dir: Path, spec: object) -> None:
    write_text(dest_dir / "spec.js", spec_js_body(spec))


def _copy_swagger_ui(ctx: object, spec: object) -> None:
    dest: Path = ctx.rel("integrations/swagger-ui")  # type: ignore[attr-defined]
    ctx.plan.record(f"write {dest}/ (read-only swagger-ui)")  # type: ignore[attr-defined]
    ctx.plan.record(f"write {dest / 'spec.js'}")  # type: ignore[attr-defined]
    dest.mkdir(parents=True, exist_ok=True)
    if TEMPLATE_DIR.is_dir():
        for item in TEMPLATE_DIR.iterdir():
            if item.name == "spec.js":
                continue
            target = dest / item.name
            if item.is_file():
                shutil.copy2(item, target)
            elif item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
    write_swagger_spec(dest, spec)
    readme = dest / "README.md"
    write_text(
        readme,
        "Read-only Swagger UI. Try it out is disabled. Open index.html "
        "(spec is inlined in spec.js so file:// works). Observed URLs "
        "are metadata only.\n",
    )


def _controllers(ctx: object) -> list[dict]:
    path: Path = ctx.rel("inventory/controllers.json")  # type: ignore[attr-defined]
    if not path.is_file():
        return []
    return list(load_json(path, "inventory/controllers.json").get("controllers") or [])


class EnonicIntegrationsStep:
    id = "enonic.integrations"
    requires = ("inventory/static.json",)
    produces = ("integrations/openapi.yaml", "integrations/swagger-ui/")
    required = True

    def plan(self, _ctx: object) -> list[str]:
        return []

    def run(self, ctx: object) -> None:
        source: Path = ctx.source  # type: ignore[attr-defined]
        title = f"{ctx.profile.get('name', 'extract')} integration contracts"  # type: ignore[attr-defined]
        spec = build_openapi(source, title, _controllers(ctx), scope.of(ctx))
        ctx.write_yaml("integrations/openapi.yaml", spec)  # type: ignore[attr-defined]
        _copy_swagger_ui(ctx, spec)

    def check(self, _ctx: object) -> list[str]:
        return []
