"""Markup scanners: Thymeleaf, FreeMarker, Mustache, Handlebars, Pebble, Angular and Vue templates.

`scan(engine, text)` returns the empty-shape dict of `new_scan()` filled with facts
that each carry a 1-based `line`. Nothing here evaluates an expression or guesses
what it means: predicates are recorded verbatim for `core.view_rules` to normalize.
"""

from __future__ import annotations

import re

from steps.core.viewscan import expr as ex
from steps.core.viewscan.base import Lines

MARKUP_ENGINES = {"thymeleaf", "freemarker", "mustache", "handlebars", "pebble", "angular", "vue"}
HTML_TAGS = {
    "a", "abbr", "article", "aside", "audio", "b", "body", "br", "button", "canvas", "caption",
    "code", "col", "div", "em", "fieldset", "figure", "footer", "form", "h1", "h2", "h3", "h4",
    "h5", "h6", "head", "header", "hr", "html", "i", "iframe", "img", "input", "label", "legend",
    "li", "link", "main", "meta", "nav", "ol", "optgroup", "option", "p", "picture", "pre",
    "script", "section", "select", "small", "source", "span", "strong", "style", "sub", "summary",
    "sup", "svg", "table", "tbody", "td", "template", "textarea", "tfoot", "th", "thead", "time",
    "title", "tr", "ul", "video", "slot", "component", "transition", "keep-alive", "router-view",
    "router-link", "ng-content", "ng-container", "ng-template", "font-awesome-icon",
}


def new_scan() -> dict:
    return {
        "inputs": [], "children": [], "slots": [], "outputs": [], "logic": {"loops": 0, "conditionals": 0},
        "i18n": [], "assets": [], "dom": [], "predicates": [],
    }


class _Collector:
    def __init__(self, text: str) -> None:
        self.text = text
        self.lines = Lines(text)
        self.scan = new_scan()
        self.locals: set[str] = set()
        self._inputs: dict[str, dict] = {}

    def line(self, offset: int) -> int:
        return self.lines.at(offset)

    def child(self, ref: str, offset: int) -> None:
        row = {"ref": ref.strip(), "line": self.line(offset)}
        if row["ref"] and row not in self.scan["children"]:
            self.scan["children"].append(row)

    def slot(self, name: str, offset: int) -> None:
        row = {"name": name, "line": self.line(offset)}
        if row not in self.scan["slots"]:
            self.scan["slots"].append(row)

    def output(self, name: str, offset: int) -> None:
        row = {"name": name, "line": self.line(offset)}
        if row not in self.scan["outputs"]:
            self.scan["outputs"].append(row)

    def i18n(self, key: str, offset: int) -> None:
        self.scan["i18n"].append({"key": key, "line": self.line(offset)})

    def asset(self, ref: str, offset: int) -> None:
        self.scan["assets"].append({"ref": ref, "line": self.line(offset)})

    def declared(self, name: str, offset: int) -> None:
        self._inputs[name] = {"name": name, "type": None, "inferred": False, "line": self.line(offset)}

    def read(self, expr: str, offset: int) -> None:
        for path in ex.operands(expr):
            root = re.split(r"[.\[]", path, maxsplit=1)[0]
            if root in self.locals or root.startswith("#") or root in _RESERVED:
                continue
            self._inputs.setdefault(
                root, {"name": root, "type": None, "inferred": True, "line": self.line(offset)},
            )

    def predicate(self, expr: str, offset: int, construct: str, effect: str) -> None:
        clean = ex.strip_wrappers(expr)
        if clean:
            self.scan["predicates"].append({
                "expr": clean, "line": self.line(offset), "construct": construct, "effect": effect,
            })

    def finish(self) -> dict:
        self.scan["inputs"] = sorted(self._inputs.values(), key=lambda r: (r["line"], r["name"]))
        for key in ("children", "slots", "outputs", "i18n", "assets"):
            self.scan[key].sort(key=lambda r: (r["line"], str(r.get("ref") or r.get("name") or r.get("key"))))
        self.scan["predicates"].sort(key=lambda r: (r["line"], r["construct"], r["expr"]))
        return self.scan


_RESERVED = {
    "param", "session", "application", "request", "response", "T", "true", "false", "null", "loop",
    "index", "first", "last", "odd", "even", "this", "super", "forloop", "@index", "@key",
    "$event", "$index", "$implicit", "window", "document", "i18n",
}
_ASSET = re.compile(
    r"""<(?:link\b[^>]*?\b(?:th:)?href|script\b[^>]*?\b(?:th:)?src)\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)


def _assets(c: _Collector) -> None:
    for match in _ASSET.finditer(c.text):
        c.asset(match.group(1), match.start())


def _formatting(c: _Collector, expr: str, offset: int) -> None:
    c.predicate(expr, offset, "format", "format")


# ---------------------------------------------------------------- Thymeleaf

_TH_ATTR = re.compile(r"""(?:\bth:|\bdata-th-)([a-z]+)\s*=\s*(["'])(.*?)\2""", re.DOTALL)
_TH_FRAGMENT_REF = re.compile(r"^\s*(?:~\{)?\s*([^\s:}(]+(?:\s*::\s*[^\s}(]+)?)")
_TH_PREFIX = re.compile(r"[$*]\{(.*)\}\s*$", re.DOTALL)
_TH_EXPR = re.compile(r"[$*]\{([^{}]*)\}")
_TH_UTIL = re.compile(r"#(?:numbers|dates|strings|calendars|temporals|aggregates)\.\w+\s*\(")
_TH_I18N = re.compile(r"#\{([^}]+)\}")


def _th_inner(value: str) -> str | None:
    """`${a > b}` -> `a > b`; `${a} and ${b}` -> `a and b`; None without a `${…}`."""
    value = value.strip()
    if len(re.findall(r"[$*]\{", value)) > 1:
        return _TH_EXPR.sub(r"\1", value)
    inner = _TH_PREFIX.match(value)
    return inner.group(1) if inner else None


def _thymeleaf(c: _Collector) -> None:
    for match in _TH_ATTR.finditer(c.text):
        name, value, at = match.group(1), match.group(3), match.start()
        if name in ("replace", "insert", "include"):
            ref = _TH_FRAGMENT_REF.match(value)
            if ref:
                c.child(ref.group(1).split("::")[0].strip() or ref.group(1), at)
        elif name == "fragment":
            frag = re.match(r"\s*([\w-]+)\s*(?:\(([^)]*)\))?", value)
            if frag:
                c.slot(frag.group(1), at)
                for param in (frag.group(2) or "").split(","):
                    if param.strip():
                        c.declared(param.strip(), at)
                        c.locals.add(param.strip())
        elif name == "each":
            c.scan["logic"]["loops"] += 1
            var = re.match(r"\s*(\w+)(?:\s*,\s*(\w+))?\s*:", value)
            if var:
                c.locals.update(g for g in var.groups() if g)
        elif name in ("if", "unless", "switch", "case"):
            c.scan["logic"]["conditionals"] += 1
    # Locals first so a later `${item.x}` is not an input.
    for match in _TH_ATTR.finditer(c.text):
        name, value, at = match.group(1), match.group(3), match.start()
        if name == "with":
            for assign in value.split(","):
                target, _, source = assign.partition("=")
                if source.strip():
                    c.locals.add(target.strip())
                    body = _th_inner(source) or source
                    if re.search(r"[-+*/%]|\?|#numbers|#dates", body):
                        c.predicate(body, at, "th:with", "compute")
        elif name in ("if", "unless"):
            body = _th_inner(value) or value
            c.predicate(body if name == "if" else f"!({body})", at, f"th:{name}", "show")
        elif name in ("switch", "case"):
            inner = _th_inner(value)
            if inner or name == "switch":
                c.predicate(inner or value, at, f"th:{name}", "select")
        for expression in _TH_EXPR.finditer(value):
            body = expression.group(1)
            offset = at + match.start(3) - match.start() + expression.start()
            c.read(body, at)
            split = ex.split_ternary(body)
            if split and name not in ("if", "unless", "case", "switch"):
                c.predicate(body, offset, "ternary", "select")
            if _TH_UTIL.search(body):
                _formatting(c, body, offset)
    for match in _TH_I18N.finditer(c.text):
        c.i18n(match.group(1).strip(), match.start())
    _assets(c)


# -------------------------------------------------------------- FreeMarker

_FTL_INCLUDE = re.compile(r"""<#(?:include|import)\s+["']([^"']+)["']""")
_FTL_MACRO_CALL = re.compile(r"<@([\w.]+)")
_FTL_MACRO = re.compile(r"<#macro\s+([\w.]+)([^>]*)>")
_FTL_LIST = re.compile(r"<#list\s+(.+?)\s+as\s+(\w+)(?:\s*,\s*(\w+))?\s*>", re.DOTALL)
_FTL_COND = re.compile(r"<#(if|elseif)\s+")
_FTL_ASSIGN = re.compile(r"<#(?:assign|local)\s+(\w+)\s*=\s*")
_FTL_INTERP = re.compile(r"\$\{([^{}]*)\}")
_FTL_FORMAT = re.compile(r"\?(?:string(?:\.\w+)?|number|round|floor|ceiling|date|datetime|time|c|then)\b")
_FTL_MESSAGE = re.compile(r"""<@(?:spring\.)?message\s+(?:code\s*=\s*)?["']([^"']+)["']""")
_FTL_BUILTIN_CALL = {"spring.message", "spring.bind", "spring.url"}


def _ftl_body(text: str, start: int) -> str:
    """Directive text up to its closing `>`; a `>` inside parentheses or quotes is an operator."""
    depth, quote = 0, ""
    for index in range(start, len(text)):
        ch = text[index]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == ">" and depth <= 0:
            return text[start:index].rstrip("/").strip()
    return text[start:].strip()


def _freemarker(c: _Collector) -> None:
    for match in _FTL_INCLUDE.finditer(c.text):
        c.child(match.group(1), match.start())
    for match in _FTL_MACRO_CALL.finditer(c.text):
        if match.group(1) not in _FTL_BUILTIN_CALL and not match.group(1).startswith("spring."):
            c.child(f"@{match.group(1)}", match.start())
    for match in _FTL_MACRO.finditer(c.text):
        c.slot(match.group(1), match.start())
        for param in match.group(2).split():
            name, _, default = param.partition("=")
            if re.fullmatch(r"\w+", name):
                c.declared(name, match.start())
                c.locals.add(name)
                if default:
                    c.predicate(f"{name} = {default}", match.start(), "macro-default", "compute")
    for match in re.finditer(r"<#nested\b", c.text):
        c.slot("nested", match.start())
    for match in _FTL_LIST.finditer(c.text):
        c.scan["logic"]["loops"] += 1
        c.locals.update(g for g in match.groups()[1:] if g)
        c.read(match.group(1), match.start())
    for match in _FTL_ASSIGN.finditer(c.text):
        body = _ftl_body(c.text, match.end())
        c.locals.add(match.group(1))
        c.read(body, match.start())
        if re.search(r"[-+*/%]|\?then|\?round|\?floor|\?ceiling", body) and not body.startswith(('"', "'")):
            c.predicate(body, match.start(), "assign", "compute")
    for match in _FTL_COND.finditer(c.text):
        body = _ftl_body(c.text, match.end())
        c.scan["logic"]["conditionals"] += 1
        c.read(body, match.start())
        c.predicate(body, match.start(), f"<#{match.group(1)}>", "show")
    for match in _FTL_INTERP.finditer(c.text):
        body = match.group(1)
        c.read(body, match.start())
        if _FTL_FORMAT.search(body):
            _formatting(c, body, match.start())
    for match in re.finditer(r"\?then\(", c.text):
        start = c.text.rfind("${", 0, match.start())
        if start >= 0 and "}" not in c.text[start:match.start()]:
            c.predicate(c.text[start + 2:match.start()] + "?then", match.start(), "?then", "select")
    for match in _FTL_MESSAGE.finditer(c.text):
        c.i18n(match.group(1), match.start())
    _assets(c)


# -------------------------------------------- Mustache / Handlebars / Pebble

_HB_TAG = re.compile(r"\{\{\{?\s*+([#^/>!&]?)([^}]*)\}?\}\}")
_HB_SUBEXPR = re.compile(r"\(\s*(\w+)\s+([^()]+?)\s*\)")
_HB_OPS = {
    "gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "eq": "==", "ne": "!=", "neq": "!=",
    "and": "&&", "or": "||",
}
_HB_KEYWORDS = {"if", "unless", "each", "with", "else", "lookup", "log", "this", "@index", "@key", "@first", "@last"}


def _hb_condition(args: str) -> str:
    """`(gt price 100)` -> `price > 100`; anything else stays as written."""
    def sub(match: re.Match[str]) -> str:
        op = _HB_OPS.get(match.group(1))
        words = match.group(2).split()
        if op and len(words) >= 2:
            return f"({f' {op} '.join(words)})"
        if match.group(1) == "not" and words:
            return f"(!{words[0]})"
        return match.group(0)

    previous = None
    while previous != args:
        previous, args = args, _HB_SUBEXPR.sub(sub, args)
    return args.strip()


def _mustache(c: _Collector, engine: str) -> None:
    for match in _HB_TAG.finditer(c.text):
        sigil, body, at = match.group(1), match.group(2).strip(), match.start()
        if sigil == "!" or sigil == "/":
            continue
        if sigil == ">":
            partial = body.split()[0] if body.split() else ""
            if partial == "@partial-block":
                c.slot("partial-block", at)
            elif partial:
                c.child(partial, at)
            continue
        words = body.split()
        head = words[0] if words else ""
        if sigil == "#":
            if head in ("if", "unless", "each", "with") and engine == "handlebars":
                rest = body[len(head):].strip()
                if head == "each":
                    c.scan["logic"]["loops"] += 1
                    c.read(rest, at)
                    continue
                c.scan["logic"]["conditionals"] += 1
                condition = _hb_condition(rest)
                c.read(condition, at)
                c.predicate(condition if head != "unless" else f"!({condition})", at, f"{{{{#{head}}}}}", "show")
                continue
            if head == ">" or head.startswith(">"):
                continue
            c.scan["logic"]["conditionals"] += 1
            c.read(body, at)
            c.predicate(body, at, "section", "show")
        elif sigil == "^":
            c.scan["logic"]["conditionals"] += 1
            c.read(body, at)
            c.predicate(f"!{body}", at, "inverted-section", "show")
        elif head == "else" and len(words) > 1 and words[1] == "if":
            condition = _hb_condition(" ".join(words[2:]))
            c.scan["logic"]["conditionals"] += 1
            c.read(condition, at)
            c.predicate(condition, at, "{{else if}}", "show")
        elif head not in _HB_KEYWORDS:
            expression = _hb_condition(body)
            c.read(expression if not words or words[0] not in {"t", "i18n", "translate"} else " ".join(words[1:]), at)
            if words and words[0] in {"t", "i18n", "translate"} and len(words) > 1:
                c.i18n(words[1].strip("'\""), at)
    _assets(c)


_PEBBLE_TAG = re.compile(r"\{%-?\s*(\w+)\s*(.*?)\s*-?%\}", re.DOTALL)
_PEBBLE_INTERP = re.compile(r"\{\{\s*(.*?)\s*\}\}", re.DOTALL)


def _pebble(c: _Collector) -> None:
    for match in _PEBBLE_TAG.finditer(c.text):
        tag, rest, at = match.group(1), match.group(2), match.start()
        if tag in ("include", "extends", "import"):
            ref = re.match(r"""["']([^"']+)["']""", rest)
            if ref:
                c.child(ref.group(1), at)
        elif tag == "block":
            c.slot(rest.strip(), at)
        elif tag == "for":
            c.scan["logic"]["loops"] += 1
            loop = re.match(r"(\w+)(?:\s*,\s*(\w+))?\s+in\s+(.+)", rest)
            if loop:
                c.locals.update(g for g in loop.groups()[:2] if g)
                c.read(loop.group(3), at)
        elif tag in ("if", "elseif"):
            c.scan["logic"]["conditionals"] += 1
            c.read(rest, at)
            c.predicate(rest, at, f"{{% {tag} %}}", "show")
        elif tag == "set":
            name, _, value = rest.partition("=")
            c.locals.add(name.strip())
            c.read(value, at)
            if re.search(r"[-+*/%]", value):
                c.predicate(value, at, "set", "compute")
    for match in _PEBBLE_INTERP.finditer(c.text):
        body = match.group(1)
        key = re.match(r"""i18n\(\s*["']([^"']+)["']""", body)
        if key:
            c.i18n(key.group(1), match.start())
        elif "|" in body and re.search(r"\|\s*(?:numberformat|date|currency)", body):
            _formatting(c, body, match.start())
        c.read(body, match.start())
    _assets(c)


# ----------------------------------------------------- Angular and Vue

_TAG = re.compile(r"<([A-Za-z][\w-]*)\b([^<>]*?)/?>", re.DOTALL)
_NG_IF = re.compile(r"""\*ngIf\s*=\s*(["'])(.*?)\1""", re.DOTALL)
_NG_FOR = re.compile(r"""\*ngFor\s*=\s*(["'])\s*let\s+(\w+)\s+of\s+(.*?)\1""", re.DOTALL)
_NG_SWITCH = re.compile(r"""\[ngSwitch\]\s*=\s*(["'])(.*?)\1""")
_NG_BIND = re.compile(r"""\[((?:class|style|attr)\.[\w.-]+|disabled|hidden|ngClass|ngStyle)\]\s*=\s*(["'])(.*?)\2""", re.DOTALL)
_NG_EVENT = re.compile(r"""\(([\w.:-]+)\)\s*=""")
_NG_BLOCK_IF = re.compile(r"@if\s*\((.*?)\)\s*\{", re.DOTALL)
_NG_BLOCK_FOR = re.compile(r"@for\s*\(\s*(\w+)\s+of\s+(.*?);")
_NG_PIPE = re.compile(r"\|\s*(currency|date|percent|number|decimal|uppercase|lowercase|async|json|slice|\w+Pipe|[a-z][\w]*)\b(?::[^|}]*)?")
_NG_INTERP = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
_NG_TRANSLATE = re.compile(r"""['"]([\w.\-]+)['"]\s*\|\s*translate""")
_NG_PROP = re.compile(r"""\[(\w+)\]\s*=\s*(["'])(.*?)\2""", re.DOTALL)
_VUE_ATTR = re.compile(r"""(v-if|v-else-if|v-show|v-for|:[\w.-]+|v-bind:[\w.-]+|@[\w.:-]+|v-on:[\w.:-]+|v-model)\s*=\s*(["'])(.*?)\2""", re.DOTALL)
_VUE_T = re.compile(r"""\$t\(\s*['"]([^'"]+)['"]""")


def _custom_children(c: _Collector, engine: str) -> None:
    for match in _TAG.finditer(c.text):
        tag = match.group(1)
        if tag in HTML_TAGS or tag.lower() in HTML_TAGS:
            continue
        if engine == "angular" and "-" not in tag:
            continue
        if engine == "vue" and "-" not in tag and not tag[0].isupper():
            continue
        c.child(tag, match.start())


def _angular(c: _Collector) -> None:
    _custom_children(c, "angular")
    for match in _NG_FOR.finditer(c.text):
        c.scan["logic"]["loops"] += 1
        c.locals.add(match.group(2))
        c.read(match.group(3), match.start())
    for match in _NG_BLOCK_FOR.finditer(c.text):
        c.scan["logic"]["loops"] += 1
        c.locals.add(match.group(1))
        c.read(match.group(2), match.start())
    for match in _NG_IF.finditer(c.text):
        c.scan["logic"]["conditionals"] += 1
        condition = re.split(r";\s*else\b", match.group(2))[0]
        condition = re.sub(r"\s+as\s+\w+\s*$", "", condition)
        c.read(condition, match.start())
        c.predicate(condition, match.start(), "*ngIf", "show")
    for match in _NG_BLOCK_IF.finditer(c.text):
        c.scan["logic"]["conditionals"] += 1
        c.read(match.group(1), match.start())
        c.predicate(match.group(1), match.start(), "@if", "show")
    for match in _NG_SWITCH.finditer(c.text):
        c.scan["logic"]["conditionals"] += 1
        c.read(match.group(2), match.start())
        c.predicate(match.group(2), match.start(), "[ngSwitch]", "select")
    for match in _NG_BIND.finditer(c.text):
        c.read(match.group(3), match.start())
        c.predicate(match.group(3), match.start(), f"[{match.group(1)}]", "css")
    for match in _NG_PROP.finditer(c.text):
        if match.group(1) not in ("ngSwitch", "disabled", "hidden", "ngClass", "ngStyle"):
            c.read(match.group(3), match.start())
    for tag in _TAG.finditer(c.text):
        if tag.group(1).lower() in HTML_TAGS or "-" not in tag.group(1):
            continue
        for event in _NG_EVENT.finditer(tag.group(2)):
            c.output(event.group(1), tag.start())
    for match in re.finditer(r"<ng-content\b([^>]*)>", c.text):
        select = re.search(r"""select\s*=\s*["']([^"']+)""", match.group(1))
        c.slot(select.group(1) if select else "default", match.start())
    for match in _NG_INTERP.finditer(c.text):
        body = match.group(1)
        c.read(body.split("|")[0], match.start())
        pipe = _NG_PIPE.search(body)
        if pipe:
            c.predicate(body, match.start(), f"|{pipe.group(1)}", "format")
    for match in _NG_TRANSLATE.finditer(c.text):
        c.i18n(match.group(1), match.start())
    _assets(c)


def _vue(c: _Collector) -> None:
    _custom_children(c, "vue")
    for match in _VUE_ATTR.finditer(c.text):
        name, value, at = match.group(1), match.group(3), match.start()
        if name == "v-for":
            c.scan["logic"]["loops"] += 1
            loop = re.match(r"\(?\s*(\w+)(?:\s*,\s*(\w+))?\s*\)?\s+(?:in|of)\s+(.+)", value)
            if loop:
                c.locals.update(g for g in loop.groups()[:2] if g)
                c.read(loop.group(3), at)
        elif name in ("v-if", "v-else-if", "v-show"):
            c.scan["logic"]["conditionals"] += 1
            c.read(value, at)
            c.predicate(value, at, name, "show")
        elif name.startswith(("@", "v-on:")):
            tag = c.text.rfind("<", 0, at)
            tag_name = re.match(r"<([\w-]+)", c.text[tag:tag + 80])
            if tag_name and tag_name.group(1).lower() not in HTML_TAGS:
                c.output(re.split(r"[:@]", name)[-1].split(".")[0], at)
        elif name.startswith((":", "v-bind:")):
            prop = name.lstrip(":").replace("v-bind:", "")
            c.read(value, at)
            if prop.split(".")[0] in ("disabled", "class", "style", "hidden", "readonly"):
                c.predicate(value, at, f":{prop}", "css")
        else:
            c.read(value, at)
    for match in re.finditer(r"<slot\b([^>]*)>", c.text):
        named = re.search(r"""name\s*=\s*["']([^"']+)""", match.group(1))
        c.slot(named.group(1) if named else "default", match.start())
    for match in _NG_INTERP.finditer(c.text):
        c.read(match.group(1), match.start())
    for match in _VUE_T.finditer(c.text):
        c.i18n(match.group(1), match.start())
    _assets(c)


def scan(engine: str, text: str) -> dict:
    c = _Collector(text)
    if engine == "thymeleaf":
        _thymeleaf(c)
    elif engine == "freemarker":
        _freemarker(c)
    elif engine in ("mustache", "handlebars"):
        _mustache(c, engine)
    elif engine == "pebble":
        _pebble(c)
    elif engine == "angular":
        _angular(c)
    elif engine == "vue":
        _vue(c)
    else:
        _assets(c)
    return c.finish()
