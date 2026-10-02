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
            ops.append(op)
    return ops


def _all_method(explicit: set[str]) -> str:
    """`all` serves every method without its own export; show it on the first such one."""
    return next((m for m in ALL_FALLBACK if m not in explicit), "post")


def _controller_file(controllers: list[dict], app: str, name: str) -> str:
    return next(
        row["file"] for row in controllers
        if row.get("kind") == "service" and row.get("app") == app and row.get("name") == name
    )


def _operation_block(op: dict) -> dict:
    block = {
        "operationId": op["operationId"],
        "summary": op["summary"],
        "x-source": op["x-source"],
        "x-direction": op["direction"],
        "responses": {
            "200": {"description": "Observed at the cited source line. Field-minimal."}
        },
    }
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
                "Field-minimal, source-traceable contracts. Production URLs are "
                "metadata only. Do not use Try it out against production."
            ),
        },
        "x-production-endpoints": [],
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
        "(spec is inlined in spec.js so file:// works). Production URLs "
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
