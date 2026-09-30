"""enonic.integrations — static harvest into field-minimal OpenAPI 3.1."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from extractkit_cli.common import REPO_ROOT, write_text
from steps.enonic.descriptors import collect_resources

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


def harvest_outbound(source: Path) -> list[dict]:
    ops: list[dict] = []
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.suffix not in JS_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        match = HTTP_CLIENT_RE.search(text)
        if not match:
            continue
        rel = _rel(source, path)
        line = _line_no(text, match)
        ops.append({
            "operationId": f"outbound_{path.stem}",
            "summary": f"Outbound HTTP from {rel}",
            "path": f"/outbound/{path.stem}",
            "method": "post",
            "direction": "outbound",
            "x-source": [f"{rel}:{line}"],
        })
    return ops


def harvest_browser_embed(source: Path) -> list[dict]:
    ops: list[dict] = []
    seen: set[str] = set()
    for path in sorted(source.rglob("*.html")):
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


def harvest_inbound(source: Path) -> list[dict]:
    ops: list[dict] = []
    for resource in collect_resources(source):
        if resource.get("kind") != "service":
            continue
        app = resource.get("app") or "unknown"
        name = resource.get("name") or "service"
        path = resource.get("path") or ""
        ops.append({
            "operationId": f"inbound_{name}",
            "summary": f"XP service {name}",
            "path": f"/_/service/{app}/{name}",
            "method": "post",
            "direction": "inbound",
            "x-source": [f"{path}:1"],
        })
    return ops


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
    if op.get("x-embed-url"):
        block["x-embed-url"] = op["x-embed-url"]
    return block


def build_openapi(source: Path, title: str) -> dict:
    ops = harvest_inbound(source) + harvest_outbound(source) + harvest_browser_embed(source)
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
    if not ctx.apply:  # type: ignore[attr-defined]
        return
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
        spec = build_openapi(source, title)
        ctx.write_yaml("integrations/openapi.yaml", spec)  # type: ignore[attr-defined]
        _copy_swagger_ui(ctx, spec)

    def check(self, _ctx: object) -> list[str]:
        return []
