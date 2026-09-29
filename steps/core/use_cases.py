"""use_cases — one markdown file per bounded context, Given/When/Then."""

from __future__ import annotations

from pathlib import Path

from extractkit_cli.common import load_json


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


def _slug(context_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in context_id)


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
        for context in contexts:
            ctx_id = str(context.get("id") or "context")
            title = str(context.get("title") or ctx_id)
            body = [
                f"# Use cases: {title}",
                "",
                f"Bounded context `{ctx_id}`. Journeys as Given/When/Then.",
                "",
            ]
            journeys = list(context.get("journeys") or [])
            if not journeys:
                journeys = [{
                    "id": f"{ctx_id}-default",
                    "title": f"Use {title}",
                    "surfaces": list(context.get("surfaces") or []),
                }]
            for journey in journeys:
                if not isinstance(journey, dict):
                    continue
                jtitle = journey.get("title") or journey.get("id") or "journey"
                ids = [
                    str(x) for x in (journey.get("surfaces") or context.get("surfaces") or [])
                    if x
                ]
                body.append(f"## {jtitle}")
                body.append("")
                if ids:
                    ident = ids[0]
                    row = surfaces.get(ident) or {}
                    status = row.get("status") or "unverified-live"
                    evidence = row.get("evidence") or []
                    body.append(f"**Given** surface `{ident}` is in the extract map")
                    body.append("")
                    body.append(
                        f"**When** an operator opens that {row.get('kind') or 'surface'}"
                    )
                    body.append("")
                    body.append(
                        f"**Then** its recorded status is `{status}` "
                        f"and evidence is {evidence or ['map:' + ident]}"
                    )
                    body.append("")
                    body.append("evidence[]: " + ", ".join(f"`{e}`" for e in (evidence or [f"map:{ident}"])))
                    body.append("")
                else:
                    body.append("**Given** the bounded context exists")
                    body.append("")
                    body.append("**When** maps are read")
                    body.append("")
                    body.append("**Then** this context has no surfaces yet")
                    body.append("")
            ctx.write_text(  # type: ignore[attr-defined]
                f"use-cases/{_slug(ctx_id)}.md",
                "\n".join(body),
            )

    def check(self, _ctx: object) -> list[str]:
        return []
