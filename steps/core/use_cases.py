"""use_cases — Given/When/Then journeys built from extracted facts only.

Runtime pages become one journey each (composition, `runtime:` and `baseline:`
refs). Static contexts get one journey per surface that has fields, config,
regions, controller behavior or a recorded composition.
"""

from __future__ import annotations

import re
from pathlib import Path

from extractkit_cli.common import load_json
from steps.core import behavior

BASELINE_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*`([^`]+)/`\s*\|", re.MULTILINE)
BASELINE_FILES = ("desktop.png", "mobile.png", "page.html")


def _load_contexts(ctx: object) -> list[dict]:
    path: Path = ctx.rel("map/bounded-contexts.json")  # type: ignore[attr-defined]
    if not path.is_file():
        return []
    payload = load_json(path, "map/bounded-contexts.json")
    return [c for c in (payload.get("contexts") or []) if isinstance(c, dict)]


def _surface_index(ctx: object) -> dict[str, dict]:
    path: Path = ctx.rel("map/project-map.json")  # type: ignore[attr-defined]
    if not path.is_file():
        return {}
    payload = load_json(path, "map/project-map.json")
    index: dict[str, dict] = {}
    for surface in payload.get("surfaces") or []:
        if isinstance(surface, dict) and surface.get("id"):
            index[str(surface["id"])] = surface
    return index


def _runtime_pages(ctx: object) -> list[dict]:
    path: Path = ctx.rel("inventory/runtime.json")  # type: ignore[attr-defined]
    if not path.is_file():
        return []
    payload = load_json(path, "inventory/runtime.json")
    return [p for p in payload.get("pages") or [] if isinstance(p, dict) and not p.get("error")]


def _baseline_slugs(ctx: object) -> dict[str, str]:
    path: Path = ctx.rel("baseline/INDEX.md")  # type: ignore[attr-defined]
    if not path.is_file():
        return {}
    return dict(BASELINE_ROW.findall(path.read_text(encoding="utf-8")))


def _slug(context_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in context_id)


def _gwt(given: str, when: str, then: str, refs: list[str], facts: list[str] | None = None) -> list[str]:
    return [
        f"**Given** {given}", "",
        f"**When** {when}", "",
        f"**Then** {then}", "",
        *([*(f"- {fact}" for fact in facts), ""] if facts else []),
        behavior.evidence_line(refs), "",
    ]


def _page_journey(page: dict, ctx: object, slugs: dict[str, str]) -> list[str]:
    path = str(page.get("path") or page.get("key") or "")
    order = [str(x) for x in page.get("templateOrder") or []]
    refs = [f"runtime:{page.get('key')}:r{page.get('round') or 1}"]
    slug = slugs.get(path)
    if slug:
        refs += [f"baseline:{slug}/{name}" for name in BASELINE_FILES if ctx.rel(  # type: ignore[attr-defined]
            f"baseline/{slug}/{name}").is_file()]
    composition = ", ".join(f"`{c}`" for c in order) if order else "no recorded components"
    lines = [f"## Open `{path}`", ""]
    lines += _gwt(
        f"content of type `{page.get('type') or 'unknown'}` at path `{path}`",
        "a visitor opens it",
        f"it renders the composition {composition}",
        refs,
    )
    return lines


def _rule_journeys(rules: list[dict]) -> list[str]:
    lines: list[str] = []
    for rule in rules:
        lines += _gwt(
            f"the rule `{rule['id']}` ({rule['kind']}) applies to `{rule['component']}`",
            f"`{rule['expression']}` is evaluated",
            behavior.EFFECT_THEN.get(rule["effect"], "its outcome applies"),
            [rule["source"], rule["id"]],
        )
    return lines


def _surface_journey(surface: dict, rules: list[dict] | None = None) -> list[str] | None:
    bullets = behavior.acceptance(surface)
    if not bullets and not rules:
        return None
    ident = surface.get("id") or ""
    kind = surface.get("kind") or "surface"
    lines = [f"## {kind} `{ident}`", ""]
    if bullets:
        lines += _gwt(
            f"the {kind} `{ident}` is in the extract map with status `{surface.get('status')}`",
            "it is used",
            "it shows this behavior:",
            behavior.evidence_refs(surface),
            bullets,
        )
    return lines + _rule_journeys(rules or [])


class UseCasesStep:
    id = "use_cases"
    requires = ("map/bounded-contexts.json",)
    produces = ("use-cases/",)
    required = True

    def plan(self, ctx: object) -> list[str]:
        n = len(_load_contexts(ctx))
        return [f"write {n} use-cases/<context>.md file(s)"]

    def run(self, ctx: object) -> None:
        contexts = _load_contexts(ctx)
        surfaces = _surface_index(ctx)
        if not contexts:
            ctx.write_text(  # type: ignore[attr-defined]
                "use-cases/README.md",
                "# Use cases\n\nNo bounded contexts. Run `maps.merge` first.\n",
            )
            return
        pages = _runtime_pages(ctx)
        slugs = _baseline_slugs(ctx)
        rules = behavior.rules_by_component(ctx)
        for context in contexts:
            ctx_id = str(context.get("id") or "context")
            title = str(context.get("title") or ctx_id)
            body = [
                f"# Use cases: {title}",
                "",
                f"Bounded context `{ctx_id}`. Journeys as Given/When/Then, from extracted facts.",
                "",
            ]
            if ctx_id.startswith("runtime-"):
                name = ctx_id.removeprefix("runtime-")
                for page in pages:
                    if str(page.get("context") or "runtime") == name:
                        body += _page_journey(page, ctx, slugs)
            else:
                for ident in context.get("surfaces") or []:
                    journey = _surface_journey(surfaces.get(str(ident)) or {"id": ident}, rules.get(str(ident)))
                    if journey:
                        body += journey
            if len(body) == 4:
                body += _gwt(
                    f"the bounded context `{ctx_id}` is in the extract map",
                    "its surfaces are read",
                    "no fields, config, regions or controller behavior were extracted for it",
                    ["map/bounded-contexts.json"],
                )
            ctx.write_text(  # type: ignore[attr-defined]
                f"use-cases/{_slug(ctx_id)}.md",
                "\n".join(body),
            )

    def check(self, _ctx: object) -> list[str]:
        return []
