"""Script scanners: React/JSX, Next.js, Vue, Angular, jQuery and Handlebars helpers.

Stdlib token scanning, not a parser. Comments are blanked first, brackets are
balanced where an expression has to be cut out, and operands of deeply nested JSX
may come out unresolved. Every fact carries its 1-based `line`.
"""

from __future__ import annotations

import re

from steps.core.viewscan import expr as ex
from steps.core.viewscan import markup
from steps.core.viewscan.base import Lines, balanced, brace_block, strip_comments

SCRIPT_ENGINES = {"react", "vue", "angular", "jquery", "handlebars"}


def _blank(text: str, pattern: str) -> str:
    """Blank every match of `pattern`, keeping newlines so lines stay put."""
    return re.sub(pattern, lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.DOTALL)


def _boundary(text: str, at: int) -> bool:
    """True when the character at `at` ends a condition read backwards (depth 0)."""
    ch = text[at]
    if ch in ",;":
        return True
    if ch == "=":
        return text[at - 1:at] not in ("=", "!", "<", ">") and text[at + 1:at + 2] != "="
    if ch == ":":
        return text[at - 1:at] != "?"
    return text[at - 6:at + 1] == "return "


def _cond_before(text: str, index: int) -> str:
    """Condition text ending at `index`, read back to the opener or separator at depth 0."""
    depth = 0
    start = index
    while start > 0:
        ch = text[start - 1]
        if ch in ")]}":
            depth += 1
        elif ch in "([{":
            if depth == 0:
                break
            depth -= 1
        elif depth == 0 and _boundary(text, start - 1):
            break
        start -= 1
    return " ".join(text[start:index].split())


class _Out:
    def __init__(self, text: str) -> None:
        self.text = text
        self.lines = Lines(text)
        self.scan = markup.new_scan()
        self._inputs: dict[str, dict] = {}

    def line(self, offset: int) -> int:
        return self.lines.at(offset)

    def input(self, name: str, offset: int, type_: str | None = None, inferred: bool = False) -> None:
        current = self._inputs.get(name)
        if current is None or (current["inferred"] and not inferred):
            self._inputs[name] = {"name": name, "type": type_, "inferred": inferred, "line": self.line(offset)}

    def add(self, key: str, row: dict) -> None:
        if row not in self.scan[key]:
            self.scan[key].append(row)

    def predicate(self, expression: str, offset: int, construct: str, effect: str) -> None:
        clean = ex.strip_wrappers(expression)
        if clean:
            self.add("predicates", {
                "expr": clean, "line": self.line(offset), "construct": construct, "effect": effect,
            })

    def finish(self) -> dict:
        self.scan["inputs"] = sorted(self._inputs.values(), key=lambda r: (r["line"], r["name"]))
        for key in ("children", "slots", "outputs", "i18n", "assets", "dom"):
            self.scan[key].sort(key=lambda r: (r["line"], str(r.get("ref") or r.get("name") or r.get("key") or r.get("selector"))))
        self.scan["predicates"].sort(key=lambda r: (r["line"], r["construct"], r["expr"]))
        return self.scan


_ARITH = re.compile(r"[\w)\]]\s*[-+*/%]\s*[\w(]")
_DERIVED = re.compile(r"\b(?:const|let|var)\s+([\w$]+)\s*(?::[^=]+)?=\s*([^;\n]+)")
_USE_MEMO = re.compile(r"\buseMemo\s*\(\s*\(\)\s*=>\s*")
_FORMAT_CALL = re.compile(r"([\w$.]+)\.(toFixed|toLocale\w*|toPrecision)\(([^)]*)\)|\bIntl\.(\w+)\(")
_I18N_CALL = re.compile(r"""(?<![\w$.])(?:t|\$t|i18n\.t|translate)\(\s*['"]([\w.\-: ]+)['"]""")
_FORMATTED = re.compile(r"""(?:FormattedMessage[^>]*\bid|formatMessage\(\s*\{\s*id)\s*[=:]\s*["']([^"']+)["']""")
_IMPORT_ASSET = re.compile(r"""import\s+(?:[\w$*{}\s,]+\s+from\s+)?["']([^"']+\.(?:css|scss|sass|less|svg|png|jpe?g|gif|webp))["']""")


def _branches(o: _Out) -> int:
    return sum(1 for p in o.scan["predicates"] if p["effect"] in ("show", "select"))


def _derived(o: _Out, text: str, effect: str = "compute") -> None:
    for match in _DERIVED.finditer(text):
        rhs = match.group(2).strip().rstrip(",")
        masked = re.sub(r"""(['"`])(?:\\.|(?!\1).)*\1""", '""', rhs)
        if "=>" in masked or re.search(r"<[A-Za-z][\w.]*[\s/>]", masked):
            continue
        if _ARITH.search(masked) and ex.operands(rhs):
            o.predicate(rhs, match.start(2), "derived", effect)
    for match in _USE_MEMO.finditer(text):
        end = balanced(text, text.rfind("(", 0, match.start() + 8))
        body = text[match.end():end - 1] if end else ""
        body = body.split(", [")[0].strip().lstrip("(").rstrip(")")
        body = re.sub(r"^\{?\s*return\s+", "", body).rstrip("; }")
        if body and _ARITH.search(body):
            o.predicate(body, match.start(), "useMemo", "compute")


def _formatting(o: _Out, text: str) -> None:
    for match in _FORMAT_CALL.finditer(text):
        o.predicate(match.group(0), match.start(), "format", "format")


def _i18n(o: _Out, text: str) -> None:
    for match in list(_I18N_CALL.finditer(text)) + list(_FORMATTED.finditer(text)):
        o.add("i18n", {"key": match.group(1), "line": o.line(match.start())})


def _assets(o: _Out, text: str) -> None:
    for match in _IMPORT_ASSET.finditer(text):
        o.add("assets", {"ref": match.group(1), "line": o.line(match.start())})


# ------------------------------------------------------------------- React

_COMPONENT = re.compile(
    r"""(?:export\s+(?:default\s+)?)?(?:function\s+([A-Z]\w*)\s*\(([^)]*)\)|const\s+([A-Z]\w*)\s*(?::[^=]+)?=\s*(?:React\.)?(?:memo\()?(?:async\s*)?\(([^)]*)\)\s*(?::[^=]+)?=>)""",
)
_PROPS_TYPE = re.compile(r"(?:interface\s+(\w*Props)\s*(?:extends[^{]*)?\{|type\s+(\w*Props)\s*=\s*\{)")
_JSX_CHILD = re.compile(r"<([A-Z][\w.]*)\b")


def _destructured(params: str) -> list[str]:
    match = re.match(r"\s*\{([^}]*)\}", params)
    if not match:
        return []
    names = []
    for part in match.group(1).split(","):
        name = re.split(r"[:=]", part.strip())[0].strip().lstrip(".")
        if re.fullmatch(r"[\w$]+", name):
            names.append(name)
    return names


def _props_types(text: str) -> dict[str, str]:
    types: dict[str, str] = {}
    for match in _PROPS_TYPE.finditer(text):
        end = balanced(text, match.end() - 1)
        block = text[match.end():end - 1] if end else ""
        for member in re.finditer(r"([\w$]+)\??\s*:\s*([^;\n,]+)", block):
            types[member.group(1)] = member.group(2).strip()
    return types


def _jsx_conditions(o: _Out, text: str) -> None:
    for match in re.finditer(r"&&\s*\(?\s*<", text):
        o.predicate(_cond_before(text, match.start()), match.start(), "jsx &&", "show")
    for match in re.finditer(r"(?<![?.])\?(?![?.])\s*\(?\s*<", text):
        o.predicate(_cond_before(text, match.start()), match.start(), "jsx ternary", "show")
    for match in re.finditer(r"className\s*=\s*\{", text):
        end = balanced(text, match.end() - 1)
        body = text[match.end():end - 1] if end else ""
        for tern in re.finditer(r"(?<![?.])\?(?![?.])", body):
            cond = _cond_before(body, tern.start())
            if cond:
                o.predicate(cond, match.start(), "className", "css")
    for match in re.finditer(r"\bif\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)\s*\{?\s*return\s+null\b", text):
        o.predicate(f"!({match.group(1).strip()})", match.start(), "return null", "show")


def _next_routing(o: _Out, text: str) -> None:
    for fn in ("getServerSideProps", "getStaticProps"):
        for match in re.finditer(rf"\b{fn}\b", text):
            span = brace_block(text, match.end())
            if span is None:
                continue
            body = text[span[0]:span[1]]
            for branch in re.finditer(
                r"\bif\s*\((.*?)\)\s*\{?\s*return\s*\{\s*(redirect|notFound)", body, re.DOTALL,
            ):
                o.predicate(branch.group(1), span[0] + branch.start(), f"{fn} {branch.group(2)}", "route")
            _derived(o, body)


def _react(o: _Out, text: str, stem: str) -> None:
    types = _props_types(text)
    component = None
    for match in _COMPONENT.finditer(text):
        name = match.group(1) or match.group(3)
        params = match.group(2) if match.group(1) else match.group(4)
        if component is None or name == stem:
            component = (name, params or "", match.start())
    if component:
        name, params, at = component
        o.scan["meta"] = {"name": name}
        callbacks = []
        for prop in _destructured(params):
            if re.fullmatch(r"on[A-Z]\w*", prop):
                callbacks.append(prop)
                o.add("outputs", {"name": prop, "line": o.line(at)})
            elif prop == "children":
                o.add("slots", {"name": "children", "line": o.line(at)})
            else:
                o.input(prop, at, types.get(prop), inferred=prop not in types and not types)
        for prop, type_ in types.items():
            if re.fullmatch(r"on[A-Z]\w*", prop):
                o.add("outputs", {"name": prop, "line": o.line(at)})
            elif prop == "children":
                o.add("slots", {"name": "children", "line": o.line(at)})
            elif prop not in callbacks:
                o.input(prop, at, type_)
        for match in re.finditer(r"\bprops\.([\w$]+)", text):
            if not re.fullmatch(r"on[A-Z]\w*|children", match.group(1)):
                o.input(match.group(1), match.start(), types.get(match.group(1)), inferred=True)
    own = (component or ("",))[0]
    for match in _JSX_CHILD.finditer(text):
        if match.group(1) not in (own, "Fragment", "React.Fragment", "Suspense"):
            o.add("children", {"ref": match.group(1), "line": o.line(match.start())})
    slot = re.search(r"\{\s*children\s*\}", text)
    if slot:
        o.add("slots", {"name": "children", "line": o.line(slot.start())})
    o.scan["logic"]["loops"] += len(re.findall(r"\.map\(\s*\(?[\w$,\s{}]*\)?\s*=>", text))
    _jsx_conditions(o, text)
    o.scan["logic"]["conditionals"] += _branches(o)
    _derived(o, text)
    _formatting(o, text)
    _next_routing(o, text)
    _i18n(o, text)
    _assets(o, text)


# --------------------------------------------------------------------- Vue

_SFC_SCRIPT = re.compile(r"<script\b[^>]*>(.*?)</script>", re.DOTALL)
_SFC_TEMPLATE_BLOCKS = re.compile(r"<(?:style)\b[^>]*>.*?</style>|<script\b[^>]*>.*?</script>", re.DOTALL)


def _vue_props(o: _Out, text: str) -> None:
    for match in re.finditer(r"defineProps\s*(?:<\s*\{)?", text):
        rest = match.end()
        if text[match.start():rest].endswith("{"):
            end = balanced(text, rest - 1)
            block = text[rest:end - 1] if end else ""
            for member in re.finditer(r"([\w$]+)\??\s*:\s*([^;\n,]+)", block):
                o.input(member.group(1), match.start(), member.group(2).strip())
            continue
        paren = text.find("(", rest)
        if paren >= 0:
            end = balanced(text, paren)
            block = text[paren + 1:end - 1] if end else ""
            _vue_prop_block(o, block, match.start())
    for match in re.finditer(r"\bprops\s*:\s*([\[{])", text):
        end = balanced(text, match.end() - 1)
        _vue_prop_block(o, text[match.end() - 1:end] if end else "", match.start())
    for match in re.finditer(r"""(?:defineEmits\s*\(\s*\[|\$emit\(\s*)([^\])]*)""", text):
        for name in re.findall(r"""['"]([\w:.-]+)['"]""", match.group(1).split(",")[0] if "$emit" in match.group(0) else match.group(1)):
            o.add("outputs", {"name": name, "line": o.line(match.start())})
    for match in re.finditer(r"\bemits\s*:\s*\[([^\]]*)\]", text):
        for name in re.findall(r"""['"]([\w:.-]+)['"]""", match.group(1)):
            o.add("outputs", {"name": name, "line": o.line(match.start())})


def _vue_prop_block(o: _Out, block: str, at: int) -> None:
    block = block.strip()
    if block.startswith("["):
        for name in re.findall(r"""['"]([\w$]+)['"]""", block):
            o.input(name, at)
    elif block.startswith("{"):
        depth = 0
        for match in re.finditer(r"([\w$]+)\s*:\s*(\{|[A-Z]\w*|\[)?|[{}\[\]]", block):
            token = match.group(0)
            if token in "{[":
                depth += 1
            elif token in "}]":
                depth -= 1
            elif depth == 1 and match.group(1):
                typ = match.group(2) if match.group(2) and match.group(2) not in "{[" else None
                o.input(match.group(1), at, typ)
                if match.group(2) in ("{", "["):
                    depth += 1


def _vue_script(o: _Out, text: str) -> None:
    _vue_props(o, text)
    for match in re.finditer(r"\bcomputed\s*:\s*\{", text):
        end = balanced(text, match.end() - 1)
        body = text[match.end():end - 1] if end else ""
        for ret in re.finditer(r"\breturn\s+([^;\n]+)", body):
            o.predicate(ret.group(1), match.end() + ret.start(1), "computed", "compute")
    for match in re.finditer(r"\bcomputed\s*\(\s*\(\)\s*=>\s*", text):
        end = text.find("\n", match.end())
        body = text[match.end():end if end > 0 else len(text)]
        body = re.sub(r"^\{?\s*return\s+", "", body.strip()).rstrip("),; ")
        o.predicate(body, match.start(), "computed", "compute")
    for match in re.finditer(r"\bwatch\s*\(\s*\(\)\s*=>\s*([^,]+),", text):
        o.predicate(match.group(1), match.start(), "watch", "compute")
    o.scan["logic"]["conditionals"] += _branches(o)
    _derived(o, text)
    _formatting(o, text)
    _i18n(o, text)
    _assets(o, text)


def _vue(text: str) -> dict:
    script = _SFC_SCRIPT.search(text)
    script_only = _blank(text, r"<template\b.*</template>|<style\b[^>]*>.*?</style>")
    script_only = re.sub(r"</?script\b[^>]*>", lambda m: " " * len(m.group(0)), script_only)
    template_only = _blank(text, r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>")
    template_only = re.sub(r"</?template\b[^>]*>", lambda m: " " * len(m.group(0)), template_only, count=1)
    o = _Out(script_only)
    _vue_script(o, script_only if script else "")
    scan = o.finish()
    merged = markup.scan("vue", template_only)
    return merge(scan, merged)


def merge(primary: dict, other: dict) -> dict:
    """Join a component's script scan with its template scan.

    Declared inputs (props, `@Input()`) are authoritative: template names are kept as
    inferred inputs only when the script declares none.
    """
    out = markup.new_scan()
    declared = any(not row["inferred"] for row in primary["inputs"])
    inputs = {} if declared else {row["name"]: row for row in other["inputs"]}
    inputs.update({row["name"]: row for row in primary["inputs"]})
    out["inputs"] = sorted(inputs.values(), key=lambda r: (r["line"], r["name"]))
    for key in ("children", "slots", "outputs", "i18n", "assets", "dom", "predicates"):
        out[key] = sorted(
            [*primary[key], *(r for r in other[key] if r not in primary[key])],
            key=lambda r: (r["line"], str(r.get("ref") or r.get("name") or r.get("key") or r.get("construct"))),
        )
    out["logic"] = {k: primary["logic"][k] + other["logic"][k] for k in ("loops", "conditionals")}
    if "meta" in primary:
        out["meta"] = primary["meta"]
    return out


# ----------------------------------------------------------------- Angular

_NG_COMPONENT_META = re.compile(r"@Component\s*\(\s*\{")
_NG_INPUT = re.compile(r"@Input\s*\(([^)]*)\)\s*(?:set\s+)?([\w$]+)\s*(?:[?!]?\s*:\s*([^;=\n]+))?")
_NG_OUTPUT = re.compile(r"@Output\s*\([^)]*\)\s*([\w$]+)")
_NG_SIGNAL_INPUT = re.compile(r"\b([\w$]+)\s*=\s*input(?:\.required)?\s*(?:<([^>]+)>)?\s*\(")
_NG_SIGNAL_OUTPUT = re.compile(r"\b([\w$]+)\s*=\s*output\s*(?:<[^>]*>)?\s*\(")
_VALIDATOR = re.compile(r"Validators\.(\w+)(?:\(([^)]*)\))?")


def _angular(o: _Out, text: str) -> None:
    meta: dict = {}
    match = _NG_COMPONENT_META.search(text)
    if match:
        end = balanced(text, match.end() - 1)
        block = text[match.end():end - 1] if end else ""
        selector = re.search(r"""selector\s*:\s*['"]([^'"]+)['"]""", block)
        template = re.search(r"""templateUrl\s*:\s*['"]([^'"]+)['"]""", block)
        inline = re.search(r"template\s*:\s*`", block)
        if selector:
            meta["selector"] = selector.group(1)
        if template:
            meta["templateUrl"] = template.group(1)
        if inline:
            meta["inlineTemplate"] = True
        name = re.search(r"\bclass\s+(\w+)", text[match.end():])
        if name:
            meta["name"] = name.group(1)
    o.scan["meta"] = meta
    for found in _NG_INPUT.finditer(text):
        o.input(found.group(2), found.start(), (found.group(3) or "").strip() or None)
    for found in _NG_SIGNAL_INPUT.finditer(text):
        o.input(found.group(1), found.start(), (found.group(2) or "").strip() or None)
    for found in _NG_OUTPUT.finditer(text):
        o.add("outputs", {"name": found.group(1), "line": o.line(found.start())})
    for found in _NG_SIGNAL_OUTPUT.finditer(text):
        o.add("outputs", {"name": found.group(1), "line": o.line(found.start())})
    for found in _VALIDATOR.finditer(text):
        argument = (found.group(2) or "").strip()
        o.predicate(f"{found.group(1)}({argument})" if argument else found.group(1), found.start(),
                    f"Validators.{found.group(1)}", "validate")
    for found in re.finditer(r"\btransform\s*\(([^)]*)\)[^{]*\{", text):
        end = balanced(text, found.end() - 1)
        body = text[found.end():end - 1] if end else ""
        base = found.end()
        for cond in re.finditer(r"\bif\s*\((.*?)\)\s*[{\n]?\s*(?:return|[\w$.]+\s*=)", body, re.DOTALL):
            o.predicate(cond.group(1), base + cond.start(), "pipe transform", "format")
        for ret in re.finditer(r"\breturn\s+([^;\n]+)", body):
            if _ARITH.search(ret.group(1)):
                o.predicate(ret.group(1), base + ret.start(1), "pipe transform", "compute")
    for found in re.finditer(r"\bcanActivate\w*\b[^{]*\{", text):
        end = balanced(text, found.end() - 1)
        body = text[found.end():end - 1] if end else ""
        for cond in re.finditer(r"\bif\s*\((.*?)\)\s*[{\n]?\s*return", body, re.DOTALL):
            o.predicate(cond.group(1), found.end() + cond.start(), "canActivate", "route")
        for ret in re.finditer(r"\breturn\s+([^;\n]*(?:[<>=!&|]{1,3})[^;\n]*)", body):
            o.predicate(ret.group(1), found.end() + ret.start(1), "canActivate", "route")
    _derived(o, text)
    _formatting(o, text)
    _i18n(o, text)
    _assets(o, text)


# ------------------------------------------------------------------ jQuery

_JQ_SELECTOR = re.compile(r"""(?<![\w$.])(?:\$|jQuery)\(\s*(['"])(.*?)\1\s*\)""")
_JQ_VAL = re.compile(
    r"""(?<![\w$.])(?:\$|jQuery)\(\s*(['"])[#.]?([\w-]+)\1\s*\)\s*\.\s*(?:val|text|html|prop|attr|is|data)\s*\([^)]*\)""",
)
_JQ_EVENT = re.compile(
    r"""(?<![\w$.])(?:\$|jQuery)\(\s*(?P<q>['"])(?P<sel>.*?)(?P=q)\s*\)\s*\.\s*"""
    r"""(?:(?P<on>on)\s*\(\s*['"](?P<event>[\w. ]+)['"]\s*(?:,\s*['"](?P<deleg>[^'"]+)['"]\s*)?,|"""
    r"""(?P<short>click|change|submit|keyup|keydown|blur|focus|input|hover|dblclick)\s*\()""",
)
_JQ_DOC_EVENT = re.compile(
    r"""(?<![\w$.])(?:\$|jQuery)\(\s*(?:document|window)\s*\)\s*\.\s*on\s*\(\s*['"](?P<event>[\w. ]+)['"]\s*,\s*(?P<q>['"])(?P<sel>[^'"]+)(?P=q)\s*,""",
)
_JQ_EFFECT = re.compile(
    r"""\.\s*(toggle|toggleClass|prop|removeClass|addClass)\s*\(\s*(?:['"]([\w-]+)['"]\s*,\s*)?""",
)


def _jq_flatten(text: str) -> str:
    """`$('#price').val()` -> `price`, padded to the same length so offsets and lines hold."""
    return _JQ_VAL.sub(lambda m: m.group(2).replace("-", "_").ljust(len(m.group(0))), text)


_FN_HEAD = re.compile(r"\s*(?:function\b[^{;]*|\(?[\w$,\s]*\)?\s*=>\s*)?")


def _own_block(text: str, start: int) -> tuple[int, int] | None:
    """The `{...}` body that starts right after `start`, not one further down the file."""
    span = brace_block(text, start)
    if span is None or not _FN_HEAD.fullmatch(text, start, span[0]):
        return None
    return span


def _jq_handler(o: _Out, flat: str, match: re.Match[str], selector: str, event: str) -> None:
    o.add("dom", {"selector": selector, "event": event, "line": o.line(match.start())})
    span = _own_block(flat, match.end())
    if span is None:
        return
    for cond in re.finditer(r"\bif\s*\((.*?)\)\s*\{", flat[span[0]:span[1]], re.DOTALL):
        o.predicate(cond.group(1), span[0] + cond.start(), f"handler {event}", "show")


def _jquery(o: _Out, text: str) -> None:
    flat = _jq_flatten(text)
    for match in _JQ_DOC_EVENT.finditer(text):
        _jq_handler(o, flat, match, match.group("sel"), match.group("event").split(".")[0])
    for match in _JQ_EVENT.finditer(text):
        event = (match.group("event") or match.group("short") or "").split(".")[0]
        _jq_handler(o, flat, match, match.group("deleg") or match.group("sel"), event)
    handled = {row["selector"] for row in o.scan["dom"]}
    for match in _JQ_SELECTOR.finditer(text):
        selector = match.group(2)
        if selector not in ("document", "window") and selector not in handled:
            handled.add(selector)
            o.add("dom", {"selector": selector, "event": "", "line": o.line(match.start())})
    for match in _JQ_EFFECT.finditer(flat):
        end = balanced(flat, flat.find("(", match.start()))
        args = flat[match.end():end - 1] if end else ""
        if match.group(1) in ("toggle", "toggleClass", "prop") and args.strip() and (
            match.group(1) != "prop" or match.group(2) == "disabled"
        ):
            effect = "css" if match.group(1) != "prop" else "validate"
            o.predicate(args.split("\n")[0], match.start(), f".{match.group(1)}", effect)
    for match in re.finditer(r"\.validate\s*\(\s*\{", flat):
        end = balanced(flat, match.end() - 1)
        block = flat[match.end():end - 1] if end else ""
        rules = re.search(r"\brules\s*:\s*\{", block)
        if rules:
            rend = balanced(block, rules.end() - 1)
            for field in re.finditer(r"([\w$\"']+)\s*:\s*\{([^{}]*)\}", block[rules.end():rend - 1] if rend else ""):
                name = field.group(1).strip("\"'")
                for rule in re.finditer(r"([\w]+)\s*:\s*([^,}\s][^,}]*)", field.group(2)):
                    o.predicate(_jq_rule(name, rule.group(1), rule.group(2).strip()),
                                match.start(), "validate rule", "validate")
    for match in re.finditer(r"\$\.(?:ajax|post|get)\s*\(", flat):
        end = balanced(flat, match.end() - 1)
        block = flat[match.end():end - 1] if end else ""
        data = re.search(r"\bdata\s*:\s*\{", block)
        if data:
            dend = balanced(block, data.end() - 1)
            for pair in re.finditer(r"([\w$]+)\s*:\s*([^,}]+)", block[data.end():dend - 1] if dend else ""):
                if _ARITH.search(pair.group(2)):
                    o.predicate(pair.group(2).strip(), match.start(), "ajax data", "compute")
    _derived(o, flat)
    o.scan["logic"]["conditionals"] += _branches(o)
    _formatting(o, flat)
    _i18n(o, flat)


def _jq_rule(field: str, rule: str, value: str) -> str:
    if rule == "required":
        return f"required({field})" if value == "true" else f"!required({field})"
    if rule == "min":
        return f"{field} >= {value}"
    if rule == "max":
        return f"{field} <= {value}"
    if rule == "minlength":
        return f"{field}.length >= {value}"
    if rule == "maxlength":
        return f"{field}.length <= {value}"
    return f"{rule}({field}, {value})"


# -------------------------------------------------------------- Handlebars

def _helpers(o: _Out, text: str) -> None:
    for match in re.finditer(r"""\bregisterHelper\s*\(\s*['"]([\w-]+)['"]\s*,\s*(?:function\s*\w*\s*\(([^)]*)\)|\(([^)]*)\)\s*=>|([\w$]+)\s*=>)""", text):
        params = match.group(2) or match.group(3) or match.group(4) or ""
        for param in params.split(","):
            if param.strip():
                o.input(param.strip(), match.start(), None, inferred=False)
        span = _own_block(text, match.end())
        if span is None:
            expression = text[match.end():text.find(")", match.end())]
            o.predicate(expression, match.start(), f"registerHelper:{match.group(1)}", "show")
            continue
        body = text[span[0] + 1:span[1] - 1]
        for ret in re.finditer(r"\breturn\s+([^;\n]+)", body):
            expression = ret.group(1).strip()
            effect = "compute" if _ARITH.search(expression) and not re.search(r"[<>=!]=?|&&|\|\|", expression) else "show"
            o.predicate(expression, span[0] + 1 + ret.start(1), f"registerHelper:{match.group(1)}", effect)
        for cond in re.finditer(r"\bif\s*\((.*?)\)\s*\{", body, re.DOTALL):
            o.predicate(cond.group(1), span[0] + 1 + cond.start(), f"registerHelper:{match.group(1)}", "show")
    _formatting(o, text)


# ----------------------------------------------------------------- dispatch

def scan(engine: str, raw: str, stem: str = "") -> dict:
    """Scan one script file for `engine`; the result has the markup scan shape."""
    text = strip_comments(raw)
    if engine == "vue":
        return _vue(text)
    o = _Out(text)
    if engine == "react":
        _react(o, text, stem)
    elif engine == "angular":
        _angular(o, text)
    elif engine == "jquery":
        _jquery(o, text)
    elif engine == "handlebars":
        _helpers(o, text)
    return o.finish()
