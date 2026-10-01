"""Expression helpers shared by every view scanner and the rule normalizer.

Deterministic string work only: no evaluation, no inference about meaning.
"""

from __future__ import annotations

import re

KEYWORDS = {
    "true", "false", "null", "undefined", "nil", "and", "or", "not", "eq", "ne", "neq", "gt",
    "ge", "gte", "lt", "le", "lte", "empty", "is", "instanceof", "typeof", "new", "in", "of",
    "return", "this", "else", "if", "then", "as", "void", "default", "mod", "div", "NaN",
}
GLOBALS = {
    "Math", "Number", "Date", "String", "Object", "Array", "JSON", "Boolean", "parseInt",
    "parseFloat", "isNaN", "window", "document", "console", "Intl",
}
# Roots that carry no business meaning of their own: the wrapper is stripped, the leaf stays.
WRAPPER_ROOTS = {
    "this", "props", "state", "ctx", "context", "model", "vm", "$ctrl", "$scope", "scope",
    "item", "data", "content", "params", "config", "app", "site", "page", "input", "args",
}

_STRING = re.compile(r"""(['"])((?:\\.|(?!\1).)*)\1""", re.DOTALL)
_NUMBER = re.compile(r"(?<![\w.$#])\d+(?:\.\d+)?(?![\w.])")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T[\d:.]+Z?)?\b")
_PATH = re.compile(
    r"(?<![\w$.#@])[A-Za-z_$][\w$]*(?:\s*\?{0,2}\.\s*[A-Za-z_$][\w$]*|\s*\[\s*(?:'[^']*'|\"[^\"]*\"|\d+)\s*\])*"
    r"(?P<call>\s*\()?"
)
_WORD_OPS = (
    (r"\bgte\b|\bge\b|&gt;=", ">="), (r"\blte\b|\ble\b|&lt;=", "<="),
    (r"\bgt\b|&gt;", ">"), (r"\blt\b|&lt;", "<"),
    (r"\bneq\b|\bne\b|!==", "!="), (r"===", "=="), (r"\beq\b", "=="),
    (r"\band\b|&amp;&amp;", "&&"), (r"\bor\b", "||"), (r"\bnot\b", "!"),
)
LENGTH_TAIL = re.compile(r"(?:\.length|\.size\(\)|\.size|\?size|\.count\(\)|\.isEmpty\(\)|\.empty)(?!\w)")


_BUILTIN = re.compile(r"(?<=[\w)\]])\?(?=[A-Za-z_])[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*(?:\([^)]*\))?")


def strip_wrappers(expr: str) -> str:
    """Drop `${ }`, `{{ }}`, `#{ }` wrappers and surrounding whitespace."""
    text = expr.strip()
    for opener, closer in (("${", "}"), ("*{", "}"), ("{{", "}}"), ("{", "}"), ("(", ")")):
        if text.startswith(opener) and text.endswith(closer) and len(text) >= len(opener) + len(closer):
            inner = text[len(opener):-len(closer)]
            if _balanced(inner):
                text = inner.strip()
    return re.sub(r"\(\s+|\s+\)", lambda m: m.group(0).strip(), " ".join(text.split()))


def _balanced(text: str) -> bool:
    depth = 0
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def split_ternary(expr: str) -> tuple[str, str, str] | None:
    """`cond ? a : b` at the top level -> (cond, a, b). Elvis `a ?: b` -> (a, a, b)."""
    depth, quote = 0, ""
    question = -1
    for index, ch in enumerate(expr):
        if quote:
            if ch == quote and expr[index - 1] != "\\":
                quote = ""
        elif ch in "'\"`":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif depth == 0 and ch == "?" and question < 0:
            after = expr[index + 1:index + 2]
            before = expr[index - 1:index]
            if after in (".", "?") or before == "?" or after == "[":
                continue
            question = index
        elif depth == 0 and ch == ":" and question >= 0:
            if question + 1 == index:
                head = expr[:question].strip()
                return head, head, expr[index + 1:].strip()
            return expr[:question].strip(), expr[question + 1:index].strip(), expr[index + 1:].strip()
    return None


def literals(expr: str) -> list[str]:
    """Quoted strings, ISO dates and numbers, in source order, duplicates kept once."""
    found: list[tuple[int, str]] = []
    masked = expr
    for match in _STRING.finditer(expr):
        found.append((match.start(), f'"{match.group(2)}"'))
        masked = masked[:match.start()] + " " * (match.end() - match.start()) + masked[match.end():]
    for match in _DATE.finditer(masked):
        found.append((match.start(), match.group(0)))
        masked = masked[:match.start()] + " " * (match.end() - match.start()) + masked[match.end():]
    for match in _NUMBER.finditer(masked):
        value = match.group(0)
        if "." in value:
            value = value.rstrip("0").rstrip(".") or "0"
        found.append((match.start(), value))
    out: list[str] = []
    for _, value in sorted(found):
        if value not in out:
            out.append(value)
    return out


def _mask_strings(expr: str) -> str:
    return _STRING.sub(lambda m: " " * len(m.group(0)), expr)


def operands(expr: str) -> list[str]:
    """Identifier paths read by the expression: no keywords, strings or called functions."""
    text = _BUILTIN.sub("", _mask_strings(strip_wrappers(expr)))
    found: list[str] = []
    for match in _PATH.finditer(text):
        path = re.sub(r"\s+", "", match.group(0))
        path = re.sub(r"\?+\.", ".", path)
        path = re.sub(r"\.(?:length|size|count|empty)$", "", path) if not match.group("call") else path
        if match.group("call"):
            path = path.rsplit(".", 1)[0] if "." in path else ""
        root = re.split(r"[.\[]", path, maxsplit=1)[0] if path else ""
        if not path or root in KEYWORDS or root in GLOBALS:
            continue
        if path not in found:
            found.append(path)
    return found


def leaf(path: str) -> str:
    """Last segment of an operand path, without wrapper roots: `item.price` -> `price`."""
    clean = re.sub(r"\[\s*(?:'([^']*)'|\"([^\"]*)\"|\d+)\s*\]", lambda m: "." + (m.group(1) or m.group(2) or "#"), path)
    parts = [p for p in clean.split(".") if p]
    while len(parts) > 1 and parts[0] in WRAPPER_ROOTS:
        parts.pop(0)
    return parts[-1] if parts else path


def shape(expr: str) -> str:
    """Canonical form: operators unified, operands reduced to `$leaf`, literals normalized."""
    text = strip_wrappers(expr)
    strings: list[str] = []

    def keep(match: re.Match[str]) -> str:
        strings.append(match.group(2))
        return f"\x00{len(strings) - 1}\x00"

    text = _STRING.sub(keep, text)
    for pattern, replacement in _WORD_OPS:
        text = re.sub(pattern, f" {replacement} ", text)
    text = LENGTH_TAIL.sub(".#len", text)
    text = _BUILTIN.sub("", text)
    text = re.sub(r"\?+\.", ".", text)

    def operand(match: re.Match[str]) -> str:
        path = re.sub(r"\s+", "", match.group(0))
        if match.group("call"):
            return match.group(0)
        root = re.split(r"[.\[]", path, maxsplit=1)[0]
        if root in KEYWORDS or root in GLOBALS:
            return match.group(0)
        name = leaf(path.replace(".#len", ""))
        return f"${name}" + (".#len" if path.endswith(".#len") else "")

    text = _PATH.sub(operand, text)
    text = _NUMBER.sub(lambda m: m.group(0).rstrip("0").rstrip(".") if "." in m.group(0) else m.group(0), text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: f'"{strings[int(m.group(1))]}"', text)
    text = re.sub(r"\s*(==|!=|>=|<=|&&|\|\||[<>+\-*/%!])\s*", r" \1 ", text)
    return " ".join(text.split())
