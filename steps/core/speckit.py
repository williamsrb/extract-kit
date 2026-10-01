"""core.speckit — as-is constitution + per-context spec.md. No tasks by default."""

from __future__ import annotations

from pathlib import Path

from extractkit_cli.common import load_json
from steps.core import behavior


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


def _components_section(ids: list[str], index: dict[str, dict]) -> list[str]:
    """Component tree plus an input, slot and output table per component, each cited."""
    members = {i: index[i] for i in ids if (index.get(i) or {}).get("template")}
    if not members:
        return []
    children = {
        i: list(dict.fromkeys(c["surface"] for c in row["template"]["children"] if c["surface"] in members))
        for i, row in members.items()
    }
    nested = {c for kids in children.values() for c in kids}
    lines = ["## Components", "", "Tree (resolved child components only):", ""]

    def walk(ident: str, depth: int, trail: tuple[str, ...]) -> None:
        template = members[ident]["template"]
        lines.append(f"{'  ' * depth}- `{ident}` ({template['engine']}, `{template['file']}`)")
        for child in children[ident]:
            if child not in trail:
                walk(child, depth + 1, (*trail, ident))

    roots = [i for i in members if i not in nested]
    for root in roots or list(members):
        walk(root, 0, ())
    lines.append("")
    for ident, row in members.items():
        template = row["template"]
        lines += [f"Component `{ident}` (x-source: `{template['file']}`)", ""]
        if template["inputs"]:
            lines += ["| input | type | x-source |", "|---|---|---|"]
            for item in template["inputs"]:
                kind = f"{item['type'] or '-'}{' (inferred)' if item['inferred'] else ''}"
                lines.append(f"| `{item['name']}` | {kind} | `{item.get('file', template['file'])}:{item['line']}` |")
            lines.append("")
        for label, key in (("Slots", "slots"), ("Outputs", "outputs")):
            if template[key]:
                lines.append(f"{label}: " + ", ".join(
                    f"`{x['name']}` (`{x.get('file', template['file'])}:{x['line']}`)" for x in template[key]
                ))
                lines.append("")
    return lines


def _open_questions(context_id: str, rules: dict[str, list[dict]]) -> list[str]:
    seen: dict[str, list[dict]] = {}
    for members in rules.values():
        if context_id not in {m.get("context") for m in members}:
            continue
        for rule in members:
            if rule.get("divergent") and rule.get("group"):
                seen.setdefault(rule["group"], []).append(rule)
    if not seen:
        return []
    lines = ["## Open questions", ""]
    for group, members in sorted(seen.items()):
        cites = ", ".join(f"`{m['source']}` (`{m['expression']}`)" for m in members)
        ids = ", ".join(f"`{m['id']}`" for m in members)
        lines.append(f"- Which version of this rule is correct? Copies disagree ({group}): {cites}. Rules: {ids}.")
    lines.append("")
    return lines


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


def _spec_md(context: dict, index: dict[str, dict], rules: dict[str, list[dict]] | None = None) -> str:
    rules = rules or {}
    ctx_id = str(context.get("id") or "context")
    title = str(context.get("title") or ctx_id)
    ids = [str(x) for x in (context.get("surfaces") or []) if x]
    lines = [
        f"# {title} (as-is)",
        "",
        f"Bounded context `{ctx_id}`. Mode: as-is. Not a port spec.",
        "",
        *_components_section(ids, index),
        "## Requirements",
        "",
    ]
    if not ids:
        lines += [
            "### FR-1 Context exists",
            "",
            f"The bounded context `{ctx_id}` is recorded in `map/bounded-contexts.json`.",
            "",
            behavior.evidence_line(["map/bounded-contexts.json"]),
            "",
        ]
        return "\n".join(lines)
    for n, ident in enumerate(ids, start=1):
        row = index.get(ident) or {"id": ident}
        kind = row.get("kind") or "surface"
        status = row.get("status") or "unverified-live"
        bullets = behavior.acceptance(row) + behavior.rule_bullets(rules.get(ident, []))
        lines += [
            f"### FR-{n} {kind} `{ident}` ({status})",
            "",
            f"The {kind} `{ident}` is `{status}` in `map/project-map.json`"
            + (" and shows this behavior." if bullets else "; no behavior was extracted for it."),
            "",
        ]
        if bullets:
            lines += ["Acceptance:", ""]
            lines += [f"- {bullet}" for bullet in bullets]
            lines.append("")
        lines += [behavior.evidence_line(behavior.evidence_refs(row)), ""]
    lines += _open_questions(ctx_id, rules)
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
        rules = behavior.rules_by_component(ctx)
        contexts = _contexts(ctx)
        if not contexts:
            ctx.write_text(  # type: ignore[attr-defined]
                "spec-kit/specs/default/spec.md",
                "# Default (as-is)\n\n### FR-1 Maps exist\n\n"
                "See `map/project-map.json`.\n\nEvidence: `map/project-map.json`\n",
            )
            return
        for context in contexts:
            slug = _slug(str(context.get("id") or "context"))
            ctx.write_text(  # type: ignore[attr-defined]
                f"spec-kit/specs/{slug}/spec.md",
                _spec_md(context, index, rules),
            )
            if getattr(ctx, "tasks", False):
                ctx.write_text(  # type: ignore[attr-defined]
                    f"spec-kit/specs/{slug}/tasks.md",
                    f"# Tasks for {slug}\n\nOptional. Off by default.\n",
                )

    def check(self, _ctx: object) -> list[str]:
        return []
