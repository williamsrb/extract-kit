"""core.view_rules — business rules written in the view layer, with evidence.

Deterministic: the kit normalizes every predicate the view scanners recorded, resolves
its operands, scores it and groups repeats and divergences. It never names a rule. The
agent adds `name` and `intent` in `rules/review.md` (marked `_(inferred)_`) and an
analyst confirms; both are carried over by rule id on a re-run.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from extractkit_cli import schema
from extractkit_cli.common import load_json
from extractkit_cli.outtree import EXTRACT_DIRNAME, HEADLESS_DIRNAME
from steps.core.behavior import walk_fields
from steps.core.viewscan import expr as ex

SCHEMA_ID = "extractkit.view-rules/v1"
KINDS = (
    "visibility", "eligibility", "calculation", "validation", "formatting", "selection",
    "routing", "market",
)
DOMAIN_TERMS = (
    "price", "amount", "date", "role", "market", "country", "status", "type", "age", "qty",
    "quantity", "discount", "limit", "total", "tax", "vat", "fee", "currency", "eligible",
    "member", "tier",
)
MARKET_TERMS = ("market", "country", "locale", "region", "currency", "language", "lang", "brand")
INDEX_TERMS = {"index", "first", "last", "odd", "even", "idx", "count"}
BUSINESS_AT = 2
EFFECT_KIND = {
    "show": "visibility", "compute": "calculation", "validate": "validation",
    "format": "formatting", "select": "selection", "route": "routing", "css": "visibility",
}
_COMPARE = re.compile(r"[<>]=?|[!=]=")
_WORDS = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")
_EMPTY_GUARD = re.compile(
    r"(?:!=|==)\s*(?:null|undefined|\"\")|\bis\s+(?:not\s+)?empty\b|\bempty\b|has_content|isEmpty|#len\s*(?:[<>]=?|[!=]=)\s*[01]\b",
)
_ARITH = re.compile(r"\$\w+(?:\.#len)?\s*[-+*/%]\s*[\w$(]|[\w)]\s*[-+*/%]\s*\$\w+")


def _words(name: str) -> list[str]:
    return [w.lower() for w in _WORDS.findall(name)]


def _domain(leaf: str) -> bool:
    for word in _words(leaf):
        stem = word[:-1] if word.endswith("s") and len(word) > 3 else word
        if word in DOMAIN_TERMS or stem in DOMAIN_TERMS:
            return True
    return False


def _market(leaf: str) -> bool:
    return any(w in MARKET_TERMS or (w[:-1] in MARKET_TERMS) for w in _words(leaf))


def _trivial(literal: str) -> bool:
    return literal in ("0", "1", '""')


def score(
    shape: str, effect: str, leaves: list[str], literals: list[str], construct: str = "",
) -> tuple[int, list[str]]:
    """Signed score and the named signals behind it. Business when >= BUSINESS_AT."""
    signals: list[tuple[int, str]] = []
    domain = [leaf for leaf in dict.fromkeys(leaves) if _domain(leaf)]
    for leaf in domain[:2]:
        signals.append((2, f"domain:{leaf}"))
    meaningful = [lit for lit in literals if not _trivial(lit) and not lit.startswith(('"#', '".'))]
    if meaningful:
        signals.append((2, f"literal:{meaningful[0]}"))
        if _COMPARE.search(shape):
            signals.append((1, "comparison"))
    if _ARITH.search(shape):
        signals.append((1, "arithmetic"))
    if ".#len" in shape:
        signals.append((-2, "length-check"))
    bare = re.fullmatch(r"!?\s*\$\w+", shape) or re.fullmatch(r"!\(?\s*\$\w+\s*\)?", shape)
    if effect != "format" and construct != "section" and (_EMPTY_GUARD.search(shape) or bare):
        signals.append((-2, "empty-guard"))
    if construct == "macro-default" and literals and all(_trivial(lit) for lit in literals):
        signals.append((-2, "trivial-default"))
    if any(leaf.lower() in INDEX_TERMS for leaf in leaves):
        signals.append((-2, "index-check"))
    if effect == "format":
        signals.append((-3, "format-call"))
    if effect == "css" and not domain:
        signals.append((-1, "css-toggle"))
    total = sum(weight for weight, _ in signals)
    return total, [f"{'+' if weight > 0 else ''}{weight} {name}" for weight, name in signals]


def classify(effect: str, leaves: list[str], literals: list[str], total: int) -> str:
    """Kind from effect and operands. A domain comparison on a visibility effect is eligibility."""
    kind = EFFECT_KIND.get(effect, "visibility")
    if effect in ("show", "select", "route", "css") and any(_market(leaf) for leaf in leaves):
        return "market"
    if kind == "visibility" and total >= BUSINESS_AT:
        return "eligibility"
    return kind


def rule_id(path: str, line: int, shape: str) -> str:
    digest = hashlib.sha1(f"{path}:{line}:{shape}".encode()).hexdigest()
    return f"VR-{digest[:10]}"


# ----------------------------------------------------------------- operands

class _Scope:
    """Where an operand name can come from, searched in this order."""

    def __init__(self, components: list[dict], types: list[dict]) -> None:
        self.inputs: dict[str, dict[str, str]] = {}
        self.config: dict[str, dict[str, str]] = {}
        for surface in components:
            names = {i["name"]: i["name"] for i in (surface.get("template") or {}).get("inputs") or []}
            for _path, field in walk_fields(surface.get("config") or []):
                if field.get("name"):
                    names.setdefault(field["name"], field["name"])
            self.inputs[surface["id"]] = names
            keys = {k["key"]: k["key"] for k in (surface.get("behavior") or {}).get("configKeys") or []}
            keys.update({k: k for k in surface.get("configKeys") or []})
            self.config[surface["id"]] = keys
        self.fields: dict[str, str] = {}
        for surface in types:
            for path, field in walk_fields(surface.get("fields") or []):
                if field.get("name"):
                    self.fields.setdefault(field["name"], f"{surface['id']}#{path}")

    def resolve(self, component: str | None, path: str) -> dict:
        leaf = ex.leaf(path)
        root = re.split(r"[.\[]", path, maxsplit=1)[0]
        row = {"name": path, "leaf": leaf}
        inputs = self.inputs.get(component or "", {})
        if leaf in inputs or root in inputs:
            return {**row, "resolved": "input", "ref": f"{component}#{inputs.get(leaf) or inputs.get(root)}"}
        if leaf in self.fields:
            return {**row, "resolved": "field", "ref": self.fields[leaf]}
        keys = self.config.get(component or "", {})
        if leaf in keys or re.match(r"(?:app\.)?config\.", path):
            return {**row, "resolved": "config", "ref": f"{component}#{keys.get(leaf, leaf)}"}
        return {**row, "resolved": "unresolved", "ref": None}


# ------------------------------------------------------------------- build

def build_rules(
    templates: dict, components: list[dict], types: list[dict], contexts: dict[str, str],
) -> list[dict]:
    scope = _Scope(components, types)
    by_file: dict[str, str] = {}
    by_controller: dict[str, str] = {}
    for surface in components:
        template = surface.get("template") or {}
        if template.get("file"):
            by_file[template["file"]] = surface["id"]
        behavior_file = (surface.get("behavior") or {}).get("file")
        if behavior_file:
            by_controller[behavior_file] = surface["id"]
    raw: list[tuple[str, str | None, dict]] = []
    for entry in templates.get("files") or []:
        component = by_file.get(entry["path"])
        raw.extend((entry["path"], component, pred) for pred in entry["scan"]["predicates"])
    for controller in templates.get("controllers") or []:
        component = by_controller.get(controller["path"])
        raw.extend((controller["path"], component, pred) for pred in controller["predicates"])
    rules: list[dict] = []
    seen: set[str] = set()
    for path, component, pred in raw:
        shape = ex.shape(pred["expr"])
        paths = ex.operands(pred["expr"])
        leaves = [ex.leaf(p) for p in paths]
        literals = ex.literals(pred["expr"])
        total, signals = score(shape, pred["effect"], leaves, literals, pred["construct"])
        path = pred.get("file", path)
        ident = rule_id(path, pred["line"], shape)
        if ident in seen:
            continue
        seen.add(ident)
        rules.append({
            "id": ident,
            "kind": classify(pred["effect"], leaves, literals, total),
            "bucket": "business" if total >= BUSINESS_AT else "presentational",
            "score": total,
            "signals": signals,
            "expression": pred["expr"],
            "shape": shape,
            "operands": [scope.resolve(component, p) for p in paths],
            "literals": literals,
            "effect": pred["effect"],
            "construct": pred["construct"],
            "component": component or None,
            "context": contexts.get(component or "", "unassigned"),
            "source": f"{path}:{pred['line']}",
            "repeated": False,
            "divergent": False,
            "group": None,
            "status": "extracted",
        })
    return sorted(rules, key=lambda r: (r["source"].rsplit(":", 1)[0], int(r["source"].rsplit(":", 1)[1]), r["id"]))


def _file(rule: dict) -> str:
    return rule["source"].rsplit(":", 1)[0]


def group_rules(rules: list[dict]) -> list[dict]:
    """Repeated (same shape, several files) and divergent (same operands, several shapes) groups."""
    groups: list[dict] = []
    by_shape: dict[str, list[dict]] = {}
    for rule in rules:
        by_shape.setdefault(rule["shape"], []).append(rule)
    for shape, members in sorted(by_shape.items()):
        files = sorted({_file(r) for r in members})
        if len(files) > 1:
            gid = "G-" + hashlib.sha1(f"repeated:{shape}".encode()).hexdigest()[:8]
            groups.append({
                "id": gid, "type": "repeated", "shape": shape, "rules": [r["id"] for r in members],
                "files": files,
            })
            for rule in members:
                rule["repeated"] = True
                rule["group"] = rule["group"] or gid
    by_operands: dict[tuple[str, ...], list[dict]] = {}
    for rule in rules:
        leaves = tuple(sorted({o["leaf"] for o in rule["operands"]}))
        if rule["bucket"] == "business" and leaves:
            by_operands.setdefault(leaves, []).append(rule)
    for leaves, members in sorted(by_operands.items()):
        shapes = sorted({r["shape"] for r in members})
        files = sorted({_file(r) for r in members})
        if len(shapes) > 1 and len(files) > 1:
            gid = "G-" + hashlib.sha1(f"divergent:{'|'.join(leaves)}".encode()).hexdigest()[:8]
            groups.append({
                "id": gid, "type": "divergent", "operands": list(leaves),
                "variants": [
                    {"shape": s, "rules": [r["id"] for r in members if r["shape"] == s]} for s in shapes
                ],
                "rules": [r["id"] for r in members], "files": files,
            })
            for rule in members:
                rule["divergent"] = True
                rule["group"] = gid
    return groups


# ----------------------------------------------------------- runtime samples

def _flatten(value: object, key: str, out: dict[str, list[object]]) -> None:
    if isinstance(value, dict):
        for child_key, child in value.items():
            if not str(child_key).startswith("_"):
                _flatten(child, str(child_key), out)
    elif isinstance(value, list) and value and all(isinstance(v, (dict, list)) for v in value):
        for child in value:
            _flatten(child, key, out)
    elif key:
        out.setdefault(key, []).append(value)


def sampled_values(ctx: object) -> dict[str, list[object]] | None:
    """`leaf -> sampled values` from the CMS survey and runtime pages; None without a sample."""
    values: dict[str, list[object]] = {}
    seen_sample = False
    survey: Path = ctx.rel("inventory/content-survey.json")  # type: ignore[attr-defined]
    runtime: Path = ctx.rel("inventory/runtime.json")  # type: ignore[attr-defined]
    if survey.is_file():
        for row in load_json(survey, "inventory/content-survey.json").get("types") or []:
            for sample in row.get("sampled") or []:
                seen_sample = True
                _flatten(sample.get("components") or [], "", values)
                _flatten(sample.get("data") or {}, "", values)
    if runtime.is_file():
        for page in load_json(runtime, "inventory/runtime.json").get("pages") or []:
            seen_sample = True
            _flatten(page.get("components") or [], "", values)
            _flatten(page.get("data") or {}, "", values)
    return values if seen_sample else None


def _empty(value: object) -> bool:
    return value in (None, "", [], {})


def attach_samples(rules: list[dict], values: dict[str, list[object]] | None) -> None:
    if values is None:
        return
    for rule in rules:
        samples: dict[str, list[object]] = {}
        for operand in rule["operands"]:
            seen = values.get(operand["leaf"])
            if seen is None:
                continue
            distinct: list[object] = []
            for value in seen:
                if value not in distinct and not _empty(value):
                    distinct.append(value)
            samples[operand["leaf"]] = distinct[:10]
            operand["sampleCount"] = len(seen)
        rule["samples"] = samples
        observed = [o for o in rule["operands"] if "sampleCount" in o]
        if rule["bucket"] == "business" and observed and not any(samples[o["leaf"]] for o in observed):
            rule["possiblyDead"] = True


# ------------------------------------------------------------------ review

REVIEW_LINE = re.compile(r"^- \[(?P<tick>[ xX])\] `?(?P<id>VR-[0-9a-f]+)`?")
FIELD_LINE = re.compile(r"^\s+- (?P<key>name|intent|out-of-scope):[ \t]*(?P<value>.*)$")


def parse_review(text: str) -> dict[str, dict]:
    """`id -> {ticked, name, intent, outOfScope}` from a rules/review.md."""
    state: dict[str, dict] = {}
    current: dict | None = None
    for line in text.splitlines():
        head = REVIEW_LINE.match(line)
        if head:
            current = {"ticked": head.group("tick").lower() == "x", "name": "", "intent": "", "outOfScope": False}
            state[head.group("id")] = current
            continue
        field = FIELD_LINE.match(line)
        if field and current is not None:
            value = field.group("value").strip()
            if field.group("key") == "out-of-scope":
                current["outOfScope"] = value.lower() in ("yes", "true", "x")
            else:
                current[field.group("key")] = re.sub(r"\s*_\(inferred\)_\s*$", "", value)
        elif line.strip() and not line.startswith(" "):
            current = None
    return state


def previous_review(ctx: object) -> dict[str, dict]:
    """Review state of this sidecar if it has one, else of the newest sibling run."""
    own: Path = ctx.rel("rules/review.md")  # type: ignore[attr-defined]
    if own.is_file():
        return parse_review(own.read_text(encoding="utf-8"))
    out: Path = ctx.out  # type: ignore[attr-defined]
    siblings = sorted(
        (p for p in out.parent.iterdir() if p.is_dir() and p != out and (p / "rules" / "review.md").is_file()),
        key=lambda p: p.name,
        reverse=True,
    ) if out.parent.name in (EXTRACT_DIRNAME, HEADLESS_DIRNAME) and out.parent.is_dir() else []
    return parse_review((siblings[0] / "rules" / "review.md").read_text(encoding="utf-8")) if siblings else {}


def apply_review(rules: list[dict], state: dict[str, dict]) -> list[str]:
    """Carry names, intents and ticks over by id. Returns ids that disappeared."""
    ids = {rule["id"] for rule in rules}
    for rule in rules:
        carried = state.get(rule["id"])
        if carried is None:
            continue
        rule["name"] = carried["name"]
        rule["intent"] = carried["intent"]
        rule["outOfScope"] = carried["outOfScope"]
        if carried["ticked"]:
            rule["status"] = "confirmed"
        elif carried["name"] and carried["intent"]:
            rule["status"] = "named"
    return sorted(i for i in state if i not in ids)


# ------------------------------------------------------------------ render

def _contexts(ctx: object) -> dict[str, str]:
    path: Path = ctx.rel("map/bounded-contexts.json")  # type: ignore[attr-defined]
    if not path.is_file():
        return {}
    index: dict[str, str] = {}
    for context in load_json(path, "map/bounded-contexts.json").get("contexts") or []:
        for surface in context.get("surfaces") or []:
            index.setdefault(surface, context["id"])
    return index


def _coverage_line(templates: dict) -> str:
    cov = templates.get("coverage") or {}
    skipped = cov.get("skipped") or []
    reasons = "; ".join(f"{s['path']} ({s['reason']})" for s in skipped[:5]) or "none"
    return (
        f"Coverage: {cov.get('scanned', 0)} source files scanned, {cov.get('detected', 0)} template "
        f"files detected, {len(skipped)} skipped ({reasons}). "
        f"Excluded folders: {', '.join(cov.get('excluded') or [])}."
    )


def _rule_line(rule: dict) -> str:
    signals = ", ".join(rule["signals"]) or "no signals"
    flags = "".join(
        f" · {label}" for label, on in (
            ("divergent", rule["divergent"]), ("repeated", rule["repeated"]),
            ("possibly-dead", rule.get("possiblyDead")),
        ) if on
    )
    named = f" — {rule['name']} _(inferred)_" if rule.get("name") else ""
    return (
        f"- `{rule['id']}` `{rule['source']}` · {rule['bucket']} (score {rule['score']}: {signals})"
        f"{flags} — `{rule['expression']}`{named}"
    )


def render_rules_md(rules: list[dict], groups: list[dict], templates: dict, removed: list[str]) -> str:
    business = [r for r in rules if r["bucket"] == "business"]
    lines = [
        "# View-layer rules",
        "",
        _coverage_line(templates),
        "",
        (
            f"{len(rules)} rule(s): {len(business)} business, {len(rules) - len(business)} presentational. "
            "Names and intents are written by the agent in `rules/review.md` (marked `_(inferred)_`) "
            "and confirmed by an analyst."
        ),
        "",
    ]
    divergent = [g for g in groups if g["type"] == "divergent"]
    if divergent:
        lines += ["## Divergent rules", ""]
        for group in divergent:
            lines.append(f"- `{group['id']}` same operands {', '.join(f'`{o}`' for o in group['operands'])}, different logic:")
            for variant in group["variants"]:
                cites = ", ".join(
                    f"`{r['source']}`" for r in rules if r["id"] in variant["rules"]
                )
                lines.append(f"  - `{variant['shape']}` at {cites}")
        lines.append("")
    by_context: dict[str, dict[str, list[dict]]] = {}
    for rule in rules:
        by_context.setdefault(rule["context"], {}).setdefault(rule["component"] or "unmapped", []).append(rule)
    for context in sorted(by_context):
        lines += [f"## Context `{context}`", ""]
        for component in sorted(by_context[context]):
            lines += [f"### `{component}`", ""]
            members = by_context[context][component]
            for kind in KINDS:
                chosen = [r for r in members if r["kind"] == kind]
                if not chosen:
                    continue
                lines += [f"#### {kind}", ""]
                lines += [_rule_line(r) for r in sorted(chosen, key=lambda r: (r["bucket"] != "business", r["source"]))]
                lines.append("")
    if removed:
        lines += ["## Removed since the previous run", ""]
        lines += [f"- `{i}`" for i in removed]
        lines.append("")
    return "\n".join(lines)


def render_literals_md(rules: list[dict]) -> str:
    rows: dict[str, list[tuple[str, str, str]]] = {}
    for rule in rules:
        if not _COMPARE.search(rule["shape"]):
            continue
        for literal in rule["literals"]:
            rows.setdefault(literal, []).append((
                ", ".join(o["leaf"] for o in rule["operands"]) or "-", rule["source"], rule["id"],
            ))
    lines = [
        "# Literals used in comparisons",
        "",
        "A literal that differs between files for the same operand is a migration risk.",
        "",
        "| literal | operands | where | rule |",
        "|---|---|---|---|",
    ]
    for literal in sorted(rows):
        for operands, source, ident in sorted(set(rows[literal])):
            lines.append(f"| `{literal}` | {operands} | `{source}` | `{ident}` |")
    lines.append("")
    return "\n".join(lines)


def render_review_md(rules: list[dict], removed: list[str]) -> str:
    lines = [
        "# Rule review",
        "",
        "Agent: fill `name:` and `intent:` for each business rule and mark them `_(inferred)_`.",
        "Analyst: tick `[x]` to confirm. Write `out-of-scope: yes` for a rule the migration drops.",
        "Edits are carried over by rule id on the next run.",
        "",
    ]
    for rule in (r for r in rules if r["bucket"] == "business"):
        tick = "x" if rule["status"] == "confirmed" else " "
        name = f"{rule['name']} _(inferred)_" if rule.get("name") else ""
        intent = f"{rule['intent']} _(inferred)_" if rule.get("intent") else ""
        lines += [
            f"- [{tick}] `{rule['id']}` `{rule['source']}` · {rule['kind']} · `{rule['expression']}`",
            f"  - name: {name}".rstrip(),
            f"  - intent: {intent}".rstrip(),
            f"  - out-of-scope: {'yes' if rule.get('outOfScope') else 'no'}",
            "",
        ]
    if removed:
        lines += ["## Removed", ""]
        lines += [f"- `{i}` no longer found in the source" for i in removed]
        lines.append("")
    return "\n".join(lines)


class ViewRulesStep:
    id = "core.view_rules"
    requires = ("inventory/templates.json",)
    produces = ("rules/view-rules.json", "rules/RULES.md", "rules/literals.md", "rules/review.md")
    required = True

    def plan(self, _ctx: object) -> list[str]:
        return []

    def run(self, ctx: object) -> None:
        templates_path: Path = ctx.rel("inventory/templates.json")  # type: ignore[attr-defined]
        templates = load_json(templates_path, "inventory/templates.json") if templates_path.is_file() else {
            "files": [], "controllers": [], "coverage": {},
        }
        components = self._components(ctx)
        types = self._types(ctx)
        rules = build_rules(templates, components, types, _contexts(ctx))
        groups = group_rules(rules)
        attach_samples(rules, sampled_values(ctx))
        removed = apply_review(rules, previous_review(ctx))
        payload = {
            "schema": SCHEMA_ID,
            "coverage": templates.get("coverage") or {},
            "rules": rules,
            "groups": groups,
            "removed": removed,
        }
        schema.validate(payload, "view-rules", what="rules/view-rules.json")
        ctx.write_json("rules/view-rules.json", payload)  # type: ignore[attr-defined]
        ctx.write_text("rules/RULES.md", render_rules_md(rules, groups, templates, removed))  # type: ignore[attr-defined]
        ctx.write_text("rules/literals.md", render_literals_md(rules))  # type: ignore[attr-defined]
        ctx.write_text("rules/review.md", render_review_md(rules, removed))  # type: ignore[attr-defined]

    @staticmethod
    def _components(ctx: object) -> list[dict]:
        path: Path = ctx.rel("map/project-map.json")  # type: ignore[attr-defined]
        return list(load_json(path, "map/project-map.json").get("surfaces") or []) if path.is_file() else []

    @staticmethod
    def _types(ctx: object) -> list[dict]:
        path: Path = ctx.rel("map/content-model.json")  # type: ignore[attr-defined]
        return list(load_json(path, "map/content-model.json").get("types") or []) if path.is_file() else []

    def check(self, _ctx: object) -> list[str]:
        return []
