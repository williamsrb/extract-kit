"""core.speckit — as-is constitution + per-context spec.md. No tasks by default."""

from __future__ import annotations

from pathlib import Path

from extractkit_cli.common import load_json


def _contexts(ctx: object) -> list[dict]:
    path: Path = ctx.rel("map/bounded-contexts.json")  # type: ignore[attr-defined]
    if not path.is_file():
        return []
    payload = load_json(path, "map/bounded-contexts.json")
    return [c for c in (payload.get("contexts") or []) if isinstance(c, dict)]


def _surfaces(ctx: object) -> dict[str, dict]:
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


CONSTITUTION = """# Constitution (as-is)

This extract describes the **existing** product. It is not a destination-stack
constitution and not an XP8 / React4XP port plan.

## Principles

1. Evidence over assumption. Every functional requirement cites a map id or an evidence ref.
2. Source stays read-only. Dead code is a report, not a delete.
3. Runtime beats static. Round 2 beats round 1. Contradictions stay listed.
4. Production URLs are metadata. Do not verify them from this kit.
5. `tasks.md` is off unless the operator passes `--tasks`.

## Out of scope

- Port plans, `DECISIONS.md`, `IMPLEMENTATION.md`
- Rewriting the product onto another stack
"""


def _spec_md(context: dict, index: dict[str, dict]) -> str:
    ctx_id = str(context.get("id") or "context")
    title = str(context.get("title") or ctx_id)
    ids = [str(x) for x in (context.get("surfaces") or []) if x]
    lines = [
        f"# {title} (as-is)",
        "",
        f"Bounded context `{ctx_id}`. Mode: as-is. Not a port spec.",
        "",
        "## Requirements",
        "",
    ]
    if not ids:
        lines.append("### FR-1 Context exists")
        lines.append("")
        lines.append(f"The bounded context `{ctx_id}` is recorded in `map/bounded-contexts.json`.")
        lines.append("")
        return "\n".join(lines)
    for n, ident in enumerate(ids, start=1):
        row = index.get(ident) or {}
        kind = row.get("kind") or "surface"
        status = row.get("status") or "unverified-live"
        evidence = row.get("evidence") or []
        lines.append(f"### FR-{n} {kind} `{ident}` remains {status}")
        lines.append("")
        lines.append(
            f"The {kind} `{ident}` is part of this context. "
            f"Status `{status}` from `map/project-map.json`."
        )
        if evidence:
            lines.append("")
            lines.append("Evidence: " + ", ".join(f"`{e}`" for e in evidence))
        lines.append("")
    return "\n".join(lines)


class SpeckitStep:
    id = "spec.kit"
    requires = ("map/bounded-contexts.json",)
    produces = ("spec-kit/constitution.md",)
    required = True

    def plan(self, ctx: object) -> list[str]:
        n = len(_contexts(ctx))
        actions = [
            "write spec-kit/constitution.md (as-is)",
            f"write {n} spec-kit/specs/<context>/spec.md file(s)",
        ]
        if getattr(ctx, "tasks", False):
            actions.append("write tasks.md (--tasks)")
        return actions

    def run(self, ctx: object) -> None:
        ctx.write_text("spec-kit/constitution.md", CONSTITUTION)  # type: ignore[attr-defined]
        ctx.write_text(  # type: ignore[attr-defined]
            "spec-kit/constitution/as-is.md",
            "# As-is fragment\n\nSee the parent constitution.md.\n",
        )
        index = _surfaces(ctx)
        contexts = _contexts(ctx)
        if not contexts:
            ctx.write_text(  # type: ignore[attr-defined]
                "spec-kit/specs/default/spec.md",
                "# Default (as-is)\n\n### FR-1 Maps exist\n\n"
                "See `map/project-map.json`.\n",
            )
            return
        for context in contexts:
            slug = _slug(str(context.get("id") or "context"))
            ctx.write_text(  # type: ignore[attr-defined]
                f"spec-kit/specs/{slug}/spec.md",
                _spec_md(context, index),
            )
            if getattr(ctx, "tasks", False):
                ctx.write_text(  # type: ignore[attr-defined]
                    f"spec-kit/specs/{slug}/tasks.md",
                    f"# Tasks for {slug}\n\nOptional. Off by default.\n",
                )

    def check(self, _ctx: object) -> list[str]:
        return []
