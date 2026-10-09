"""Behavior text for spec and use cases — built only from extracted facts.

No inference lives here. Every sentence comes from a field, a config input, a
region, a controller fact (with `file:line`), or a recorded runtime composition.
A model may rewrite the prose later; the skill marks that `_(inferred)_`.
"""

from __future__ import annotations

HTTP_CLIENT = "http-client"


def walk_fields(fields: list[dict], prefix: str = "") -> list[tuple[str, dict]]:
    """Every field with its dotted path; item-set items and option items included."""
    found: list[tuple[str, dict]] = []
    for field in fields:
        path = f"{prefix}{field['name']}" if field.get("name") else prefix.rstrip(".")
        found.append((path, field))
        found += walk_fields(field.get("items") or [], path + ".")
        for option in field.get("options") or []:
            found += walk_fields(option.get("items") or [], f"{path}.{option.get('name')}.")
    return found


def _ticks(values: list[str]) -> str:
    return ", ".join(f"`{v}`" for v in values)


def _occurs(occ: dict | None) -> str:
    if not occ:
        return ""
    high = occ.get("max")
    return f"{occ.get('min', 0)}..{'*' if not high else high}"


def _field_bullet(path: str, field: dict, noun: str) -> str:
    if field.get("mixin") and not field.get("name"):
        return f"Includes mixin `{field['mixin']}`, which is not part of this extract."
    kind = field.get("type") or "input"
    text = f"{noun} `{path}` is a {kind}"
    if field.get("occurrences"):
        text += f" occurring {_occurs(field['occurrences'])}"
    config = field.get("config") or {}
    if config.get("allowContentType"):
        text += f", limited to content types {_ticks(config['allowContentType'])}"
    if config.get("option"):
        text += f", offering {_ticks(config['option'])}"
    if field.get("options"):
        names = [o.get("name") or "" for o in field["options"]]
        text += f", selecting {_occurs(field.get('selection'))} of {_ticks(names)}"
    if field.get("fromMixin"):
        text += f", from mixin `{field['fromMixin']}`"
    return text + "."


def _loc(behavior: dict, line: int) -> str:
    return f"`{behavior.get('file')}:{line}`"


def _behavior_bullets(behavior: dict) -> list[str]:
    bullets: list[str] = []
    for method in behavior.get("methods") or []:
        bullets.append(f"Exports `{method['name']}` ({_loc(behavior, method['line'])}).")
    for call in behavior.get("calls") or []:
        verb = "Sends HTTP with" if HTTP_CLIENT in call["module"] else "Calls"
        bullets.append(f"{verb} `{call['call']}` from `{call['module']}` ({_loc(behavior, call['line'])}).")
    for query in behavior.get("queries") or []:
        label = "query" if query["field"] == "query" else "content type filter"
        bullets.append(f"Uses {label} `{query['value']}` ({_loc(behavior, query['line'])}).")
    for view in behavior.get("views") or []:
        target = f" `{view['ref']}`" if view.get("ref") else ""
        bullets.append(f"Renders through `{view['via']}`{target} ({_loc(behavior, view['line'])}).")
    for item in behavior.get("i18n") or []:
        bullets.append(f"Localises key `{item['key']}` ({_loc(behavior, item['line'])}).")
    for item in behavior.get("configKeys") or []:
        bullets.append(f"Reads app config `{item['key']}` ({_loc(behavior, item['line'])}).")
    for item in behavior.get("listeners") or []:
        bullets.append(f"Listens for events of type `{item['type']}` ({_loc(behavior, item['line'])}).")
    return bullets


def acceptance(surface: dict) -> list[str]:
    """Acceptance bullets for one surface, in a fixed order, from extracted facts only."""
    bullets: list[str] = []
    for path, field in walk_fields(surface.get("fields") or []):
        bullets.append(_field_bullet(path, field, "Field"))
    for path, field in walk_fields(surface.get("config") or []):
        bullets.append(_field_bullet(path, field, "Config input"))
    for region in surface.get("regions") or []:
        bullets.append(f"Exposes region `{region}`.")
    bullets += _behavior_bullets(surface.get("behavior") or {})
    for key in surface.get("configKeys") or []:
        bullets.append(f"The app reads config key `{key}`.")
    cited = {r["type"]: r["source"] for r in reversed(surface.get("listenerRefs") or [])}
    for event in surface.get("listeners") or []:
        where = f" (`{cited[event]}`)" if event in cited else ""
        bullets.append(f"The app listens for `{event}` events{where}.")
    if surface.get("composition"):
        bullets.append(f"Renders as the composition {_ticks(surface['composition'])}.")
    return bullets


EFFECT_THEN = {
    "show": "the element it guards is shown",
    "compute": "the value it derives is computed",
    "validate": "the input is validated",
    "format": "the value is formatted",
    "select": "the matching branch is chosen",
    "route": "the visitor is routed",
    "css": "its presentation state changes",
    "authorize": "access is granted or refused by role",
    "transition": "the record moves to, or stays in, the state it names",
}


def rules_by_component(ctx: object) -> dict[str, list[dict]]:
    """Business view rules grouped by component surface id; empty without rules/view-rules.json."""
    from extractkit_cli.common import load_json

    path = ctx.rel("rules/view-rules.json")  # type: ignore[attr-defined]
    if not path.is_file():
        return {}
    grouped: dict[str, list[dict]] = {}
    for rule in load_json(path, "rules/view-rules.json").get("rules") or []:
        if rule["bucket"] == "business" and rule["component"] and not rule.get("outOfScope"):
            grouped.setdefault(rule["component"], []).append(rule)
    return grouped


def rule_bullets(rules: list[dict]) -> list[str]:
    """One cited bullet per business rule: id, kind, expression and `path:line`."""
    out = []
    for rule in rules:
        name = f" {rule['name']} _(inferred)_." if rule.get("name") else ""
        flag = " Diverges from another copy of this rule." if rule.get("divergent") else ""
        if rule.get("dead"):
            flag += f" Dead code: never runs ({rule['deadAt']}, {rule['deadReason']})."
        if rule.get("unreferenced"):
            flag += " Unreferenced: its function has no callers."
        out.append(
            f"Rule `{rule['id']}` ({rule['kind']}): `{rule['expression']}` ({rule['source']}).{name}{flag}"
        )
    return out


def evidence_refs(surface: dict) -> list[str]:
    """Map id, descriptor path, runtime/usage refs, and the controller file."""
    refs = [str(surface.get("id") or ""), str(surface.get("entry") or "")]
    refs += [str(e) for e in surface.get("evidence") or []]
    behavior = surface.get("behavior") or {}
    if behavior.get("file"):
        refs.append(str(behavior["file"]))
    refs += [str(r["source"]) for r in surface.get("listenerRefs") or []]
    return [r for i, r in enumerate(refs) if r and r not in refs[:i]]


def evidence_line(refs: list[str]) -> str:
    return "Evidence: " + ", ".join(f"`{r}`" for r in refs)
