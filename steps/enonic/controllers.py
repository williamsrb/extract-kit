"""enonic.controllers — regex scan of XP7 controller code into inventory/controllers.json.

Stdlib only; no graft, no runtime. Every recorded fact carries its `line`.
Comments are blanked before matching so commented-out code never reports.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from extractkit_cli import schema, scope
from steps.core.viewscan.base import Lines as _Lines
from steps.core.viewscan.base import brace_block as _brace_block
from steps.core.viewscan.base import strip_comments
from steps.enonic.descriptors import (
    app_name_for,
    iter_resources_roots,
    mapping_controllers,
)

SCRIPT_SUFFIXES = {".js", ".es6", ".ts"}
SKIP_PARTS = {"node_modules", "build", "__tests__", "assets"}

# (resources-relative folder, kind). Folder-per-descriptor kinds hold <name>/<name>.js.
FOLDER_KINDS: tuple[tuple[str, str], ...] = (
    ("site/pages", "page"),
    ("site/layouts", "layout"),
    ("site/parts", "part"),
    ("site/macros", "macro"),
    ("services", "service"),
    ("tasks", "task"),
    ("admin/tools", "admin-tool"),
    ("admin/widgets", "admin-widget"),
)
# Flat kinds: every script under the folder is one controller.
TREE_KINDS: tuple[tuple[str, str], ...] = (
    ("site/error", "error"),
    ("error", "error"),
    ("site/filters", "filter"),
    ("site/processors", "response-processor"),
    ("webapp", "webapp"),
    ("idprovider", "id-provider"),
    ("cron", "cron"),
)

HTTP_METHODS = {
    "get", "post", "put", "delete", "patch", "head", "options", "all", "connect", "trace",
}
LIFECYCLE_EXPORTS = {"filter", "run", "responseProcessor", "canRender"}
RENDER_LIBS = ("thymeleaf", "mustache", "freemarker", "handlebars", "react4xp", "pebble")

_REQUIRE = re.compile(
    r"""(?:const|let|var)\s+(?:(?P<alias>[\w$]+)|\{(?P<names>[^}]*)\})\s*=\s*"""
    r"""require\(\s*(?P<q>['"])(?P<module>[^'"]+)(?P=q)\s*\)""",
)
_REQUIRE_OBJECT = re.compile(r"(?:const|let|var)\s+(?P<obj>[\w$]+)\s*=\s*\{")
_REQUIRE_MEMBER = re.compile(
    r"""(?P<key>[\w$]+)\s*:\s*require\(\s*(?P<q>['"])(?P<module>[^'"]+)(?P=q)\s*\)""",
)
_IMPORT = re.compile(
    r"""import\s+(?:type\s+)?(?:(?P<default>[\w$]+)\s*,?\s*)?(?:\*\s+as\s+(?P<ns>[\w$]+)|\{(?P<names>[^}]*)\})?"""
    r"""\s*from\s*(?P<q>['"])(?P<module>[^'"]+)(?P=q)""",
)
_EXPORT_ASSIGN = re.compile(r"\bexports\.([\w$]+)\s*=")
_EXPORT_DECL = re.compile(r"\bexport\s+(?:async\s+)?(?:function\*?|const|let|var)\s+([\w$]+)")
_EXPORT_LIST = re.compile(r"\bexport\s*\{([^}]*)\}")
_RESOLVE = re.compile(r"""\bresolve\(\s*(?P<q>['"])(?P<ref>[^'"]+)(?P=q)\s*\)""")
_NEW_REACT = re.compile(r"""\bnew\s+React4xp\(\s*(?P<q>['"])(?P<ref>[^'"]+)(?P=q)""")
_CONFIG_INDEX = re.compile(r"""\bapp\.config\[\s*(?P<q>['"])(?P<key>[^'"]+)(?P=q)\s*\]""")
_CONFIG_DOT = re.compile(r"\bapp\.config\.([A-Za-z_$][\w$]*)")
_STRING = re.compile(r"""(?P<q>['"`])(?P<v>(?:\\.|(?!(?P=q)).)*)(?P=q)""", re.DOTALL)
_LIST_ITEM = re.compile(
    r"""(?:^\[|,|^)\s*(?P<q>['"`])(?P<v>(?:\\.|(?!(?P=q)).)*)(?P=q)\s*(?=,|\]$|$)""", re.DOTALL,
)
_QUERY = re.compile(
    r"""\bquery\s*:\s*(?P<q>['"`])(?P<v>(?:\\.|(?!(?P=q)).)*)(?P=q)(?=\s*[,})\n])""", re.DOTALL,
)
_CONTENT_TYPES = re.compile(
    r"""\bcontentTypes\s*:\s*(?P<v>\[[^\]]*\]|(?P<q>['"])(?:\\.|(?!(?P=q)).)*(?P=q))""",
    re.DOTALL,
)


def _names(raw: str) -> list[tuple[str, str]]:
    """`a, b as c` -> [(imported, local)]."""
    pairs: list[tuple[str, str]] = []
    for part in raw.split(","):
        bits = [b.strip() for b in re.split(r"\s+as\s+|:", part.strip()) if b.strip()]
        if bits:
            pairs.append((bits[0], bits[-1]))
    return pairs


def _imports(text: str, lines: _Lines) -> list[dict]:
    found: list[dict] = []
    for match in _REQUIRE.finditer(text):
        found.append(_import_row(
            match.group("module"), match.group("alias"), match.group("names"),
            lines.at(match.start()),
        ))
    for match in _REQUIRE_OBJECT.finditer(text):
        span = _brace_block(text, match.end() - 1)
        if span is None:
            continue
        for member in _REQUIRE_MEMBER.finditer(text, span[0], span[1]):
            found.append(_import_row(
                member.group("module"), f"{match.group('obj')}.{member.group('key')}", None,
                lines.at(member.start()),
            ))
    for match in _IMPORT.finditer(text):
        alias = match.group("ns") or match.group("default")
        found.append(_import_row(
            match.group("module"), alias, match.group("names"), lines.at(match.start()),
        ))
    return sorted(
        (row for row in found if row["module"].startswith("/lib/")),
        key=lambda row: (row["line"], row["module"]),
    )


def _import_row(module: str, alias: str | None, names: str | None, line: int) -> dict:
    row: dict = {"module": module, "line": line}
    if alias:
        row["alias"] = alias
    if names is not None:
        row["names"] = [{"name": a, "local": b} for a, b in _names(names)]
    return row


def _calls(text: str, lines: _Lines, imports: list[dict]) -> list[dict]:
    calls: list[dict] = []
    for row in imports:
        alias = row.get("alias")
        if alias:
            pattern = re.compile(rf"(?<![\w$.]){re.escape(alias)}\.([A-Za-z_$][\w$]*)\s*\(")
            for match in pattern.finditer(text):
                calls.append({
                    "call": f"{alias}.{match.group(1)}",
                    "module": row["module"],
                    "line": lines.at(match.start()),
                })
        for item in row.get("names") or []:
            pattern = re.compile(rf"(?<![\w$.]){re.escape(item['local'])}\s*\(")
            for match in pattern.finditer(text):
                calls.append({
                    "call": item["name"],
                    "module": row["module"],
                    "line": lines.at(match.start()),
                })
    return sorted(calls, key=lambda c: (c["line"], c["call"]))


def _queries(text: str, lines: _Lines) -> list[dict]:
    rows: list[dict] = []
    for match in _QUERY.finditer(text):
        value = match.group("v")
        if match.group("q") == "`" and "${" in value:
            continue
        rows.append({"field": "query", "value": value, "line": lines.at(match.start("v"))})
    for match in _CONTENT_TYPES.finditer(text):
        base = match.start("v")
        for literal in _LIST_ITEM.finditer(match.group("v")):
            value = literal.group("v")
            if literal.group("q") == "`" and "${" in value:
                continue
            rows.append({
                "field": "contentTypes",
                "value": value,
                "line": lines.at(base + literal.start("v")),
            })
    return sorted(rows, key=lambda r: (r["line"], r["field"], r["value"]))


_MODULE_EXPORTS = re.compile(r"\bmodule\.exports\s*=\s*\{")


def export_names(raw: str) -> list[dict]:
    """Every name a module exports, with its line: `exports.x =`, `export ...`, `module.exports = {...}`."""
    text = strip_comments(raw)
    lines = _Lines(text)
    rows: dict[str, int] = {}
    for match in _EXPORT_ASSIGN.finditer(text):
        rows.setdefault(match.group(1), lines.at(match.start()))
    for match in _EXPORT_DECL.finditer(text):
        rows.setdefault(match.group(1), lines.at(match.start()))
    for match in _EXPORT_LIST.finditer(text):
        for _imported, local in _names(match.group(1)):
            rows.setdefault(local, lines.at(match.start()))
    for match in _MODULE_EXPORTS.finditer(text):
        span = _brace_block(text, match.end() - 1)
        if span is not None:
            for key in _object_props(text[span[0]:span[1]]):
                rows.setdefault(key, lines.at(match.start()))
    return [{"name": n, "line": rows[n]} for n in sorted(rows, key=lambda k: (rows[k], k))]


def _methods(text: str, lines: _Lines) -> list[dict]:
    rows: dict[str, int] = {}

    def add(name: str, offset: int) -> None:
        wanted = (
            name in HTTP_METHODS
            or name in LIFECYCLE_EXPORTS
            or re.fullmatch(r"handle\w*", name) is not None
        )
        if wanted:
            rows.setdefault(name, lines.at(offset))

    for match in _EXPORT_ASSIGN.finditer(text):
        add(match.group(1), match.start())
    for match in _EXPORT_DECL.finditer(text):
        add(match.group(1), match.start())
    for match in _EXPORT_LIST.finditer(text):
        for _imported, local in _names(match.group(1)):
            add(local, match.start())
    return [{"name": n, "line": rows[n]} for n in sorted(rows, key=lambda k: (rows[k], k))]


def _views(text: str, lines: _Lines, imports: list[dict], calls: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for match in _RESOLVE.finditer(text):
        rows.append({"via": "resolve", "ref": match.group("ref"), "line": lines.at(match.start())})
    for match in _NEW_REACT.finditer(text):
        rows.append({"via": "React4xp", "ref": match.group("ref"), "line": lines.at(match.start())})
    renderers = {
        r["alias"] for r in imports
        if r.get("alias") and any(lib in r["module"].lower() for lib in RENDER_LIBS)
    }
    for call in calls:
        alias, _, fn = call["call"].rpartition(".")
        if fn == "render" and alias in renderers:
            rows.append({"via": call["call"], "ref": None, "line": call["line"]})
    return sorted(rows, key=lambda r: (r["line"], r["via"], r["ref"] or ""))


def _i18n(text: str, lines: _Lines) -> list[dict]:
    rows: list[dict] = []
    for match in re.finditer(r"\blocalize\s*\(", text):
        span = _brace_block(text, match.end())
        if span is None or text[match.end():span[0]].strip():
            continue
        block = text[span[0]:span[1]]
        key = re.search(r"""\bkey\s*:\s*(?P<q>['"])(?P<v>[^'"]+)(?P=q)""", block)
        if key:
            rows.append({"key": key.group("v"), "line": lines.at(span[0] + key.start("v"))})
    return sorted(rows, key=lambda r: (r["line"], r["key"]))


def _config_keys(text: str, lines: _Lines) -> list[dict]:
    rows = [
        {"key": m.group("key"), "line": lines.at(m.start())}
        for m in _CONFIG_INDEX.finditer(text)
    ]
    rows += [{"key": m.group(1), "line": lines.at(m.start())} for m in _CONFIG_DOT.finditer(text)]
    return sorted(rows, key=lambda r: (r["line"], r["key"]))


_REQ = r"(?:req|request)"
_PARAM = re.compile(rf"""\b{_REQ}\.params(?:\.(?P<dot>[\w$]+)|\[\s*(?P<q>['"])(?P<key>[^'"]+)(?P=q)\s*\])""")
_HEADER = re.compile(rf"""\b{_REQ}\.headers(?:\.(?P<dot>[\w$]+)|\[\s*(?P<q>['"])(?P<key>[^'"]+)(?P=q)\s*\])""")
_COOKIE = re.compile(rf"""\b{_REQ}\.cookies(?:\.(?P<dot>[\w$]+)|\[\s*(?P<q>['"])(?P<key>[^'"]+)(?P=q)\s*\])""")
_BODY_VAR = re.compile(
    rf"""(?:const|let|var)\s+(?:(?P<name>[\w$]+)|\{{(?P<names>[^}}]*)\}})\s*=\s*JSON\.parse\(\s*(?:{_REQ}\.body|(?P<alias>[\w$]+))""",
)
_STATUS = re.compile(r"\bstatus\s*:\s*(\d{3})\b")
_CONTENT_TYPE = re.compile(r"""\bcontentType\s*:\s*(?P<q>['"`])(?P<v>(?:\\.|(?!(?P=q)).)*)(?P=q)""")
_REDIRECT = re.compile(r"""\bredirect\s*:\s*(?:(?P<q>['"])(?P<v>[^'"]*)(?P=q))?|\.redirect\s*\(""")
_HAS_ROLE = re.compile(r"""\bhasRole\s*\(\s*(?:(?P<q>['"])(?P<v>[^'"]*)(?P=q))?""")
_USER_CHECK = re.compile(r"\b(?P<v>getUser|isAuthenticated|isUnauthori[sz]ed\w*)\s*\(")
_PRINCIPALS = re.compile(r"\bprincipals\s*:\s*\[(?P<v>[^\]]*)\]")
_LOGIN = re.compile(r"""\buser\s*:\s*\{[^}]*?\blogin\s*:\s*(?P<q>['"])(?P<v>[^'"]+)(?P=q)""")


_PARAM_ALIAS = re.compile(rf"(?:const|let|var)\s+(?P<name>[\w$]+)\s*=\s*{_REQ}\.params\b")
_BODY_ALIAS = re.compile(rf"(?:const|let|var)\s+(?P<name>[\w$]+)\s*=\s*{_REQ}\.body\b")
_PARAMS_WHOLE = re.compile(rf"\b{_REQ}\.params\b(?!\s*(?:\.|\[))")


def _name(match: re.Match) -> str:
    return match.group("dot") or match.group("key")


def _inputs(text: str, lines: _Lines) -> list[dict]:
    rows: list[dict] = []
    for source, pattern in (("param", _PARAM), ("header", _HEADER), ("cookie", _COOKIE)):
        rows += [
            {"source": source, "name": _name(m), "line": lines.at(m.start())}
            for m in pattern.finditer(text)
        ]
    for match in _PARAM_ALIAS.finditer(text):
        var = re.escape(match.group("name"))
        rows += [
            {"source": "param", "name": _name(read), "line": lines.at(match.end() + read.start())}
            for read in re.finditer(
                rf"""(?<![\w$.]){var}(?:\.(?P<dot>[\w$]+)(?![\w$])|\[\s*(?P<q>['"])(?P<key>[^'"]+)(?P=q)\s*\])""",
                text[match.end():],
            )
        ]
    aliased = {m.end() - len("params") for m in _PARAM_ALIAS.finditer(text)}
    rows += [
        {"source": "param", "name": "*", "line": lines.at(m.start())}
        for m in _PARAMS_WHOLE.finditer(text) if m.end() - len("params") not in aliased
    ]
    body_vars = {m.group("name") for m in _BODY_ALIAS.finditer(text)}
    for match in _BODY_VAR.finditer(text):
        if match.group("alias") and match.group("alias") not in body_vars:
            continue
        line = lines.at(match.start())
        if match.group("names") is not None:
            rows += [
                {"source": "body", "name": imported, "line": line}
                for imported, _local in _names(match.group("names"))
            ]
            continue
        var = re.escape(match.group("name"))
        for read in re.finditer(
            rf"""(?<![\w$.]){var}(?:\.(?P<dot>[\w$]+)(?![\w$])|\[\s*(?P<q>['"])(?P<key>[^'"]+)(?P=q)\s*\])(?!\s*=[^=])""",
            text[match.end():],
        ):
            rows.append({
                "source": "body", "name": _name(read), "line": lines.at(match.end() + read.start()),
            })
    return sorted(rows, key=lambda r: (r["line"], r["source"], r["name"]))


def _responses(text: str, lines: _Lines) -> list[dict]:
    rows = [
        {"kind": "status", "value": m.group(1), "line": lines.at(m.start())}
        for m in _STATUS.finditer(text)
    ]
    rows += [
        {"kind": "contentType", "value": m.group("v"), "line": lines.at(m.start())}
        for m in _CONTENT_TYPE.finditer(text)
    ]
    rows += [
        {"kind": "redirect", "value": m.group("v") if m.groupdict().get("v") else None,
         "line": lines.at(m.start())}
        for m in _REDIRECT.finditer(text)
    ]
    return sorted(rows, key=lambda r: (r["line"], r["kind"], r["value"] or ""))


def _auth(text: str, lines: _Lines) -> list[dict]:
    rows = [
        {"kind": "role-check", "value": m.group("v"), "line": lines.at(m.start())}
        for m in _HAS_ROLE.finditer(text)
    ]
    rows += [
        {"kind": "user-check", "value": m.group("v"), "line": lines.at(m.start())}
        for m in _USER_CHECK.finditer(text)
    ]
    for match in _PRINCIPALS.finditer(text):
        for item in _STRING.finditer(match.group("v")):
            rows.append({"kind": "elevated", "value": item.group("v"), "line": lines.at(match.start())})
    rows += [
        {"kind": "elevated", "value": f"user:{m.group('v')}", "line": lines.at(m.start())}
        for m in _LOGIN.finditer(text)
    ]
    return sorted(rows, key=lambda r: (r["line"], r["kind"], r["value"] or ""))


def _listeners(text: str, lines: _Lines, imports: list[dict], calls: list[dict]) -> list[dict]:
    aliases = {
        r["alias"] for r in imports
        if r.get("alias") and r["module"] == "/lib/xp/event"
    } | {"event"}
    rows: list[dict] = []
    for alias in sorted(aliases):
        for match in re.finditer(rf"(?<![\w$.]){re.escape(alias)}\.listener\s*\(", text):
            span = _brace_block(text, match.end())
            if span is None or text[match.end():span[0]].strip():
                continue
            block = text[span[0]:span[1]]
            kind = re.search(r"""\btype\s*:\s*(?P<q>['"])(?P<v>[^'"]+)(?P=q)""", block)
            if kind:
                first, last = lines.at(span[0]), lines.at(span[1])
                effects = sorted({
                    c["call"] for c in calls
                    if first <= c["line"] <= last and not c["call"].endswith(".listener")
                })
                row = {"type": kind.group("v"), "line": lines.at(span[0] + kind.start("v"))}
                if effects:
                    row["calls"] = effects
                rows.append(row)
    return sorted(rows, key=lambda r: (r["line"], r["type"]))


def scan_text(raw: str) -> dict:
    text = strip_comments(raw)
    lines = _Lines(text)
    imports = _imports(text, lines)
    calls = _calls(text, lines, imports)
    return {
        "imports": imports,
        "calls": calls,
        "queries": _queries(text, lines),
        "methods": _methods(text, lines),
        "views": _views(text, lines, imports, calls),
        "i18n": _i18n(text, lines),
        "configKeys": _config_keys(text, lines),
        "listeners": _listeners(text, lines, imports, calls),
        "inputs": _inputs(text, lines),
        "responses": _responses(text, lines),
        "auth": _auth(text, lines),
    }


def _object_props(block: str) -> dict[str, str]:
    """Top-level `key: value` pairs of a `{...}` literal; values stay source text."""
    inner, parts, depth, quote, start = block[1:-1], [], 0, "", 0
    for index, ch in enumerate(inner):
        if quote:
            if ch == quote and inner[index - 1] != "\\":
                quote = ""
        elif ch in "'\"`":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(inner[start:index])
            start = index + 1
    parts.append(inner[start:])
    props: dict[str, str] = {}
    for part in parts:
        pair = re.match(r"""\s*['"]?([\w$]+)['"]?\s*(?::\s*(.*))?\Z""", part, re.DOTALL)
        if pair:
            props[pair.group(1)] = " ".join((pair.group(2) or pair.group(1)).split())
    return props


def _literal(value: str | None) -> str | None:
    if value is None:
        return None
    match = _STRING.fullmatch(value)
    if match is None or (match.group("q") == "`" and "${" in match.group("v")):
        return None
    return match.group("v")


def http_requests(raw: str) -> list[dict]:
    """`httpClient.request({ url, method })` calls: literal `url`/`method`, else `urlExpr`."""
    text = strip_comments(raw)
    lines = _Lines(text)
    imports = [r for r in _imports(text, lines) if "http-client" in r["module"]]
    patterns = [
        rf"(?<![\w$.]){re.escape(r['alias'])}\.request\s*\(" for r in imports if r.get("alias")
    ]
    for row in imports:
        patterns += [
            rf"(?<![\w$.]){re.escape(n['local'])}\s*\("
            for n in row.get("names") or [] if n["name"] == "request"
        ]
    rows: list[dict] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            span = _brace_block(text, match.end())
            if span is None or text[match.end():span[0]].strip():
                # `request(requestObj)`: the options are built elsewhere, the call line is still the cite.
                rows.append({"line": lines.at(match.start())})
                continue
            props = _object_props(text[span[0]:span[1]])
            url, method = props.get("url"), props.get("method")
            row: dict = {"line": lines.at(match.start())}
            if _literal(url) is not None:
                row["url"] = _literal(url)
            elif url is not None:
                row["urlExpr"] = url
            if _literal(method) is not None:
                row["method"] = _literal(method).lower()
            rows.append(row)
    return sorted(rows, key=lambda r: r["line"])


def _is_script(path: Path) -> bool:
    return (
        path.is_file()
        and path.suffix in SCRIPT_SUFFIXES
        and not path.name.endswith(".d.ts")
        and ".test." not in path.name
        and not SKIP_PARTS.intersection(path.parts)
    )


def _rel(source: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(source.resolve()).as_posix()
    except ValueError:
        return str(path)


def _candidates(root: Path) -> list[tuple[Path, str]]:
    found: dict[Path, str] = {}
    for rel, kind in FOLDER_KINDS:
        base = root / rel
        if base.is_dir():
            for path in sorted(base.glob("*/*")):
                if path.stem == path.parent.name and _is_script(path):
                    found.setdefault(path, kind)
    for rel, kind in TREE_KINDS:
        base = root / rel
        if base.is_dir():
            for path in sorted(base.rglob("*")):
                if _is_script(path):
                    found.setdefault(path, kind)
    for suffix in sorted(SCRIPT_SUFFIXES):
        main = root / f"main{suffix}"
        if _is_script(main):
            found.setdefault(main, "main")
    for controller in mapping_controllers(root):
        if _is_script(controller):
            found.setdefault(controller, "mapping")
    return sorted(found.items())


def collect_controllers(source: Path, exclude: Iterable[str] = ()) -> list[dict]:
    rows: list[dict] = []
    for root in iter_resources_roots(source, exclude):
        app = app_name_for(root, source)
        for path, kind in _candidates(root):
            text = path.read_text(encoding="utf-8", errors="replace")
            rows.append({
                "file": _rel(source, path),
                "folder": _rel(source, path.parent),
                "kind": kind,
                "name": path.parent.name if kind in {k for _, k in FOLDER_KINDS} | {"cron"} else path.stem,
                "app": app,
                **scan_text(text),
            })
    return sorted(rows, key=lambda r: r["file"])


class EnonicControllersStep:
    id = "enonic.controllers"
    requires: tuple[str, ...] = ()
    produces = ("inventory/controllers.json",)
    required = True

    def plan(self, _ctx: object) -> list[str]:
        return []

    def run(self, ctx: object) -> None:
        payload = {
            "schema": "extractkit.controllers/v1",
            "controllers": collect_controllers(ctx.source, scope.of(ctx)),  # type: ignore[attr-defined]
        }
        schema.validate(payload, "controllers", what="inventory/controllers.json")
        ctx.write_json("inventory/controllers.json", payload)  # type: ignore[attr-defined]

    def check(self, _ctx: object) -> list[str]:
        return []
