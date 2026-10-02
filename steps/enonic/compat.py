"""enonic.compat — factual XP7 to XP8 compatibility list, written outside spec-kit/.

Not a port plan. Every row says what the source uses and quotes what an XP8
offline doc page states about it. No row claims an API is removed unless that
page says so. Pages are named relative to `~/.agents/kb/offline-reference/`.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path

from extractkit_cli import scope
from extractkit_cli.common import load_json
from steps.enonic.controllers import HTTP_METHODS
from steps.enonic.descriptors import collect_site_mappings

DOCS = "xp8/docs"
UPGRADE = f"{DOCS}/code/stable/upgrade.md"
UPGRADE_URL = "https://developer.enonic.com/docs/code/stable/upgrade"
LIB_PAGE = DOCS + "/code/stable/libraries/lib-{leaf}.md"
LIB_LEAVES = frozenset({
    "admin", "app", "auditlog", "auth", "cluster", "common", "content", "context", "event",
    "export", "grid", "i18n", "io", "mail", "node", "portal", "project", "repo", "scheduler",
    "schema", "sse", "task", "value", "vhost", "websocket",
})
LIB_SECTIONS = frozenset({
    "admin", "node", "content", "project", "repo", "scheduler", "cluster", "i18n", "task",
    "auth", "export", "context",
})

# kind -> (page, section, what the page states)
DESCRIPTORS: dict[str, tuple[str, str, str]] = {
    "site": (UPGRADE, "Site descriptor split", (
        "`site.xml` is split into `site.yaml` (processors, mappings, apis) and `cms.yaml` "
        "(mixin references, previously x-data, and the site form); the `site` directory is renamed `cms`."
    )),
    "content-type": (UPGRADE, "Content type descriptor", "The XML descriptor is converted to YAML."),
    "mixin": (UPGRADE, "Mixins renamed to Form Fragments",
              "Mixins are renamed to Form Fragments; the `mixins` directory is renamed `form-fragments`."),
    "x-data": (UPGRADE, "X-data renamed to Mixin",
               "X-data is renamed to Mixin; the `x-data` directory is renamed `mixins`."),
    "page": (UPGRADE, "Page descriptor", "The XML descriptor is converted to YAML."),
    "layout": (UPGRADE, "Layout descriptor", "The XML descriptor is converted to YAML."),
    "part": (UPGRADE, "Part descriptor", "The XML descriptor is converted to YAML."),
    "macro": (UPGRADE, "Macro descriptors", "Macro descriptors must be converted from XML to YAML."),
    "task": (UPGRADE, "Task", "Task descriptors must be converted from XML to YAML."),
    "service": (UPGRADE, "HTTP Services", (
        "HTTP Services are deprecated but continue to work; Universal APIs under `apis/` with a "
        "`.yaml` descriptor are recommended."
    )),
    "admin-tool": (UPGRADE, "Admin Tools", "Admin Tool descriptors must be converted from XML to YAML."),
    "admin-widget": (UPGRADE, "Widgets / Admin Extensions", (
        "Widgets are part of the Admin Extensions API; `admin/widgets` is renamed "
        "`admin/extensions`; descriptors must be converted from XML to YAML."
    )),
    "id-provider": (UPGRADE, "ID Provider", "ID Provider descriptors must be converted from XML to YAML."),
    "application": (UPGRADE, "Application Descriptor", "`application.xml` must be converted to `enonic.yaml`."),
}
# kinds with no XML descriptor: (page, section, statement)
SCRIPT_KINDS: dict[str, tuple[str, str, str]] = {
    "error": (f"{DOCS}/code/stable/web/error.md", "page",
              "The upgrade page lists no change for error handlers."),
    "webapp": (f"{DOCS}/code/stable/web/webapps.md", "page",
               "The upgrade page lists no change for webapp controllers."),
    "i18n-bundle": (f"{DOCS}/code/stable/fundamentals/i18n.md", "page",
                    "lib-i18n reads the standard `/i18n/phrases` location only (upgrade page, lib-i18n)."),
    "i18n-bundle in site/i18n": (
        UPGRADE, "lib-i18n",
        ("Methods no longer use the undocumented `/site/i18n/phrases` bundle location by default; "
         "move the files to `/i18n/phrases`."),
    ),
}
SITE_ITEMS = (
    (f"{DOCS}/code/stable/web/sites/mappings.md", "mapping"),
    (f"{DOCS}/code/stable/web/filters.md", "filter"),
    (f"{DOCS}/code/stable/web/sites/processors.md", "response-processor"),
)
CALL_NOTES: dict[tuple[str, str], tuple[str, str]] = {
    ("content", "move"): ("lib-content", "`move` and `rename` are merged into a single `move` method."),
    ("content", "rename"): ("lib-content", "`move` and `rename` are merged into a single `move` method."),
    ("content", "setChildOrder"): ("lib-content", "`setChildOrder` and `reorderChildren` are merged into a single `sort` method."),
    ("content", "reorderChildren"): ("lib-content", "`setChildOrder` and `reorderChildren` are merged into a single `sort` method."),
    ("content", "setPermissions"): ("lib-content", "`setPermissions` is removed. Use `applyPermissions` instead."),
    ("content", "modify"): ("lib-content", "`modify` is deprecated. Use `update` instead."),
    ("content", "modifyMedia"): ("lib-content", "`modifyMedia` is deprecated. Use `updateMedia` instead."),
    ("content", "delete"): ("lib-content", "`delete` is renamed `deleteContent`; the old export is still available."),
    ("node", "setRootPermissions"): ("lib-node", "`setRootPermissions` is removed. Use `applyPermissions` instead."),
    ("node", "modify"): ("lib-node", "`modify` is deprecated. Use `update` instead."),
    ("admin", "getAssetsUri"): ("lib-admin", "`getAssetsUri` is removed."),
    ("admin", "getBaseUri"): ("lib-admin", "`getBaseUri` is removed. Use `getHomeToolUrl` instead."),
    ("admin", "getLocale"): ("lib-admin", "`getLocale` is removed without replacement."),
    ("admin", "getLocales"): ("lib-admin", "`getLocales` is removed. Use `request.locales` instead."),
    ("admin", "getPhrases"): ("lib-admin", "`getPhrases` is removed. Use lib-i18n `getPhrases` instead."),
    ("admin", "getLauncherUrl"): ("lib-admin", "`getLauncherUrl` is removed; the launcher is a widget now."),
    ("admin", "getLauncherPath"): ("lib-admin", "`getLauncherPath` is removed; the launcher is a widget now."),
    ("i18n", "localize"): ("lib-i18n", "`localize` no longer accepts the `application` parameter."),
    ("task", "submit"): ("lib-task", "`submit` is removed. Use `executeFunction` instead."),
    ("task", "submitNamed"): ("lib-task", "`submitNamed` is removed. Use `submitTask` instead."),
    ("portal", "serviceUrl"): ("HTTP Services", "Use `portal.apiUrl()` instead of `portal.serviceUrl()` for APIs."),
}
OTHER_LIBS = {
    "/lib/util": ("Other libraries", "lib-util is deprecated."),
    "/lib/guillotine": ("Other libraries", "lib-guillotine is not supported for XP8."),
}


def _url(page: str) -> str:
    if page == UPGRADE:
        return UPGRADE_URL
    return "https://developer.enonic.com/docs/" + page.removeprefix(f"{DOCS}/").removesuffix(".md")


def _link(page: str, section: str) -> str:
    return f"[{page} § {section}]({_url(page)})"


def _page_link(page: str) -> str:
    return f"[{page}]({_url(page)})"


def _leaf(module: str) -> str:
    return module.rsplit("/", 1)[-1]


def _fn(call: str) -> str:
    return call.rsplit(".", 1)[-1]


def descriptor_counts(resources: list[dict], applications: int) -> list[tuple[str, int]]:
    counts = Counter(
        r["kind"] for r in resources
        if str(r.get("path") or "").endswith(".xml") and r.get("kind") in DESCRIPTORS
    )
    if applications:
        counts["application"] = applications
    return sorted(counts.items())


def _descriptor_section(counts: list[tuple[str, int]], script_only: dict[str, int]) -> list[str]:
    lines = [
        "## XML descriptors", "",
        "Each XML descriptor needs a YAML counterpart in XP8.", "",
        "| kind | XML descriptors | checked against | the page states |", "|---|---|---|---|",
    ]
    for kind, n in counts:
        page, section, said = DESCRIPTORS[kind]
        lines.append(f"| {kind} | {n} | {_link(page, section)} | {said} |")
    lines.append(f"\nTotal XML descriptors: {sum(n for _, n in counts)}.")
    if script_only:
        lines.append(
            "Services and tasks without an XML descriptor: "
            + ", ".join(f"{n} {kind}{'' if n == 1 else 's'}" for kind, n in sorted(script_only.items()))
            + f". The {_link(UPGRADE, 'HTTP Services')} section covers services either way."
        )
    return lines


def _script_section(resources: list[dict]) -> list[str]:
    rows = Counter(
        f"{r['kind']} in site/i18n" if r.get("location") == "site/i18n" else r["kind"]
        for r in resources if r.get("kind") in SCRIPT_KINDS
    )
    if not rows:
        return []
    lines = [
        "", "## Script-only items", "",
        "| kind | found | checked against | the page states |", "|---|---|---|---|",
    ]
    for kind in sorted(rows):
        page, _section, said = SCRIPT_KINDS[kind]
        lines.append(f"| {kind} | {rows[kind]} | {_page_link(page)} | {said} |")
    return lines


def _modules(controllers: list[dict]) -> dict[str, dict]:
    modules: dict[str, dict] = defaultdict(lambda: {"files": set(), "calls": 0})
    for row in controllers:
        by_module = Counter(c["module"] for c in row.get("calls") or [])
        for imp in row.get("imports") or []:
            info = modules[imp["module"]]
            info["files"].add(row["file"])
            info["calls"] += by_module[imp["module"]]
    return modules


def _library_section(controllers: list[dict]) -> list[str]:
    modules = _modules(controllers)
    xp = sorted(m for m in modules if m.startswith("/lib/xp/"))
    lines = ["", "## System libraries in use", ""]
    if not xp:
        return [*lines, "No `/lib/xp/*` import was found in the controllers scanned."]
    lines += ["| module | controllers | calls | checked against | upgrade page section |", "|---|---|---|---|---|"]
    for module in xp:
        leaf = _leaf(module)
        page = _page_link(LIB_PAGE.format(leaf=leaf)) if leaf in LIB_LEAVES else "no page in the offline XP8 index"
        section = "has a section" if leaf in LIB_SECTIONS else "no section"
        info = modules[module]
        lines.append(f"| `{module}` | {len(info['files'])} | {info['calls']} | {page} | {section} |")
    others = sorted(m for m in modules if m in OTHER_LIBS or any(m.startswith(o + "/") for o in OTHER_LIBS))
    for module in others:
        key = next(o for o in OTHER_LIBS if module == o or module.startswith(o + "/"))
        section, said = OTHER_LIBS[key]
        lines.append(f"\n`{module}` ({len(modules[module]['files'])} controllers): {said} {_link(UPGRADE, section)}")
    return lines


def _call_notes(controllers: list[dict]) -> list[str]:
    rows: list[tuple[str, str, str]] = []
    for row in controllers:
        for call in row.get("calls") or []:
            module = call["module"]
            note = CALL_NOTES.get((_leaf(module), _fn(call["call"])))
            if module.startswith("/lib/xp/") and note:
                rows.append((f"{row['file']}:{call['line']}", f"{module} {_fn(call['call'])}", _link(UPGRADE, note[0]) + " " + note[1]))
    if not rows:
        return []
    lines = ["", "## Calls the upgrade page names", "", "| location | call | the page states |", "|---|---|---|"]
    lines += [f"| `{loc}` | `{call}` | {said} |" for loc, call, said in sorted(rows)]
    return lines


def _export_section(controllers: list[dict]) -> list[str]:
    lowercase = [
        (row["file"], m["name"], m["line"])
        for row in controllers for m in row.get("methods") or []
        if m["name"] in HTTP_METHODS and m["name"] != "all"
    ]
    resolves = [
        (row["file"], v["line"])
        for row in controllers for v in row.get("views") or [] if v["via"] == "resolve"
    ]
    lines: list[str] = []
    if lowercase:
        lines += [
            "", "## HTTP method exports", "",
            (
                f"{len(lowercase)} lowercase exports. {_link(UPGRADE, 'HTTP functions')}: lowercase "
                "names are deprecated but still supported; uppercase names are recommended; "
                "`all` stays lowercase."
            ),
            "",
        ]
        lines += [f"- `{name}` at `{file}:{line}`" for file, name, line in sorted(lowercase)]
    if resolves:
        lines += [
            "", "## `resolve` calls", "",
            (
                f"{len(resolves)} call(s). {_link(UPGRADE, 'Script Globals')}: `resolve` no longer "
                "uses `src/main/resources/site` as its first root folder; only "
                "`src/main/resources` is used."
            ),
            "",
        ]
        lines += [f"- `{file}:{line}`" for file, line in sorted(resolves)]
    return lines


def _site_section(resources: list[dict], mappings: list[dict]) -> list[str]:
    filters = [r for r in resources if r.get("kind") == "filter"]
    processors = [r for r in resources if r.get("kind") == "response-processor"]
    if not (mappings or filters or processors):
        return []
    lines = [
        "", "## Site mappings, filters and processors", "",
        f"{_link(UPGRADE, 'Site descriptor split')}: `site.yaml` holds processors, mappings and apis.", "",
    ]
    for mapping in sorted(mappings, key=lambda m: (m["path"], m["controller"], m["filter"])):
        target = mapping["controller"] or mapping["filter"] or "(none)"
        kind = "controller" if mapping["controller"] else "filter"
        extra = " ".join(f"{k} `{mapping[k]}`" for k in ("match", "pattern") if mapping.get(k))
        lines.append(f"- mapping ({kind}) `{target}` {extra} in `{mapping['path']}`".rstrip())
    for row in sorted(filters, key=lambda r: r["path"]):
        lines.append(f"- filter `{row['name']}` at `{row['path']}`")
    for row in sorted(processors, key=lambda r: r["name"]):
        lines.append(f"- response processor `{row['name']}` order {row.get('order') or 'unset'} at `{row['path']}`")
    lines.append("")
    lines.append("Checked against: " + ", ".join(_page_link(page) for page, _ in SITE_ITEMS))
    return lines


def render_report(
    source: Path, resources: list[dict], controllers: list[dict], exclude: Iterable[str] = (),
) -> str:
    applications = len(scope.kept(source, source.rglob("src/main/resources/application.xml"), exclude))
    lines = [
        "# XP8 compatibility (facts, not a plan)", "",
        "XP7-specific items this source uses. Written outside `spec-kit/`; `promote` does not copy it.",
        "Each row cites the XP8 offline page it was checked against (relative to `~/.agents/kb/offline-reference/`).",
        "A row says an API is removed only where that page says so.", "",
    ]
    script_only = Counter(
        r["kind"] for r in resources
        if r.get("kind") in ("service", "task") and not str(r.get("path") or "").endswith(".xml")
    )
    lines += _descriptor_section(descriptor_counts(resources, applications), dict(script_only))
    lines += _script_section(resources)
    lines += _library_section(controllers)
    lines += _call_notes(controllers)
    lines += _export_section(controllers)
    lines += _site_section(resources, collect_site_mappings(source, exclude))
    return "\n".join(lines) + "\n"


class EnonicCompatStep:
    id = "enonic.compat"
    requires = ("inventory/static.json",)
    produces = ("reports/xp8-compat.md",)
    required = False

    def plan(self, _ctx: object) -> list[str]:
        return []

    def run(self, ctx: object) -> None:
        static = ctx.rel("inventory/static.json")  # type: ignore[attr-defined]
        if not static.is_file():
            ctx.record_skip(  # type: ignore[attr-defined]
                self.id, "no inventory/static.json to count descriptors from",
                "run the static phase first: extractkit run --profile enonic "
                "--source <legacy-checkout> --until static",
            )
            return
        controllers_path = ctx.rel("inventory/controllers.json")  # type: ignore[attr-defined]
        controllers = (
            load_json(controllers_path, "inventory/controllers.json").get("controllers") or []
            if controllers_path.is_file() else []
        )
        resources = load_json(static, "inventory/static.json").get("resources") or []
        ctx.write_text(  # type: ignore[attr-defined]
            "reports/xp8-compat.md",
            render_report(ctx.source, resources, controllers, scope.of(ctx)),  # type: ignore[attr-defined]
        )

    def check(self, _ctx: object) -> list[str]:
        return []
