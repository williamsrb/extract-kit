"""Dead regions of a view or script file: code that can never run, with the line that gates it.

A region is dead when it sits inside a comment, behind a `th:if="false"`, or in a JS
branch gated by a module-level constant. Nothing is evaluated beyond a literal
`true`/`false`. Every span carries the 1-based line of the gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from steps.core.viewscan.base import Lines, balanced, strip_comments


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    gate: int
    reason: str
    gate_expr: str = ""

    def covers(self, line: int) -> bool:
        return self.start <= line <= self.end


# `<!--/*/ ... /*/-->` is Thymeleaf prototype-only markup: it runs, so it is not a comment.
_HTML_COMMENT = re.compile(r"<!--(?!/\*/)(?P<body>.*?)-->", re.DOTALL)
_FTL_COMMENT = re.compile(r"<#--.*?-->", re.DOTALL)
_HBS_COMMENT = re.compile(r"\{\{!--.*?--\}\}|\{\{![^}]*\}\}", re.DOTALL)
_TH_IF = re.compile(
    r"""(?:\bth:|\bdata-th-)(?P<attr>if|unless)\s*=\s*(?P<q>["'])\s*(?:\$\{\s*)?(?P<v>true|false)\s*(?:\})?\s*(?P=q)""",
)
_TAG = re.compile(r"<(?P<close>/?)(?P<name>[A-Za-z][\w:-]*)(?P<rest>[^>]*?)(?P<self>/?)>", re.DOTALL)
_VOID = {"br", "hr", "img", "input", "link", "meta", "source", "area", "base", "col", "embed", "wbr"}


def _element_end(text: str, tag: re.Match[str]) -> int:
    """Offset just past the element opened by `tag`; the tag itself when it has no body."""
    name = tag.group("name")
    if tag.group("self") or name.lower() in _VOID:
        return tag.end()
    depth = 1
    for nxt in _TAG.finditer(text, tag.end()):
        if nxt.group("name") != name or nxt.group("self"):
            continue
        depth += -1 if nxt.group("close") else 1
        if depth == 0:
            return nxt.end()
    return tag.end()


def markup_spans(text: str) -> list[Span]:
    lines = Lines(text)
    spans: list[Span] = []
    for pattern, reason in (
        (_HTML_COMMENT, "html-comment"), (_FTL_COMMENT, "freemarker-comment"), (_HBS_COMMENT, "handlebars-comment"),
    ):
        for match in pattern.finditer(text):
            spans.append(Span(lines.at(match.start()), lines.at(match.end() - 1), lines.at(match.start()), reason))
    for gate in _TH_IF.finditer(text):
        always = gate.group("v") == "true"
        dead = gate.group("attr") == "unless" if always else gate.group("attr") == "if"
        if not dead:
            continue
        opener = None
        for tag in _TAG.finditer(text):
            if tag.start() <= gate.start() < tag.end():
                opener = tag
                break
        if opener is None or opener.group("close"):
            continue
        spans.append(Span(
            lines.at(opener.start()), lines.at(_element_end(text, opener) - 1), lines.at(gate.start()),
            f"th:{gate.group('attr')}=\"{gate.group('v')}\"",
        ))
    return sorted(spans, key=lambda s: (s.start, s.end))


_CONST = re.compile(r"^(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?P<v>true|false)\s*;?[ \t]*$", re.MULTILINE)
_IF_CONST = re.compile(r"\bif\s*\(\s*(?P<neg>!?)\s*(?P<name>[A-Za-z_$][\w$]*)\s*\)")
_EXITS = re.compile(r"^\s*(?:return|throw|continue|break)\b")


def _enclosing_end(text: str, start: int) -> int:
    """Offset of the `}` that closes the block holding `start`, or the end of the text."""
    depth, quote, escaped = 0, "", False
    for index in range(start, len(text)):
        ch = text[index]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = ""
        elif ch in "'\"`":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return index
    return len(text)


def _statement_end(text: str, start: int) -> int:
    newline = text.find("\n", start)
    semicolon = text.find(";", start)
    ends = [i for i in (newline, semicolon) if i >= 0]
    return (min(ends) + 1) if ends else len(text)


def _branch_end(text: str, start: int) -> int:
    """Offset past the statement at `start`; an `if` takes its whole `else if` / `else` chain."""
    if text[start:start + 1] == "{":
        return balanced(text, start) or len(text)
    head = re.match(r"if\s*\(", text[start:])
    if not head:
        return _statement_end(text, start)
    cursor = balanced(text, start + head.end() - 1) or len(text)
    while cursor < len(text) and text[cursor] in " \t\r\n":
        cursor += 1
    end = _branch_end(text, cursor)
    tail = re.match(r"\s*else\b\s*", text[end:])
    return _branch_end(text, end + tail.end()) if tail else end


def _ends_in_exit(body: str) -> bool:
    """True when the last statement of `body` is a `return`/`throw` that always runs."""
    last = None
    for last in re.finditer(r"\b(?:return|throw)\b[^;\n]*;?\s*$", body):
        pass
    if last is None:
        return False
    before = body[:last.start()]
    if before.count("{") != before.count("}"):
        return False
    before = before.rstrip()
    return not before or before[-1] in ";}"


def js_spans(raw: str) -> list[Span]:
    """Branches gated by a module-level `const X = true|false`."""
    text = strip_comments(raw)
    consts = {
        m.group("name"): m.group("v") == "true" for m in _CONST.finditer(text)
        if not re.search(rf"^\s*{re.escape(m.group('name'))}\s*=(?!=)", text[m.end():], re.MULTILINE)
    }
    if not consts:
        return []
    lines = Lines(text)
    spans: list[Span] = []
    for gate in _IF_CONST.finditer(text):
        name = gate.group("name")
        if name not in consts:
            continue
        truth = consts[name] != bool(gate.group("neg"))
        condition = name
        reason = f"{gate.group('neg')}{name} is always {'true' if truth else 'false'}"
        cursor = gate.end()
        while cursor < len(text) and text[cursor] in " \t\r\n":
            cursor += 1
        braced = cursor < len(text) and text[cursor] == "{"
        body_end = (balanced(text, cursor) if braced else _statement_end(text, cursor)) or len(text)
        gate_line = lines.at(gate.start())
        if not truth:
            spans.append(Span(gate_line, lines.at(body_end - 1), gate_line, reason, condition))
            continue
        body = text[cursor + 1:body_end - 1] if braced else text[cursor:body_end]
        tail = re.match(r"\s*else\b\s*", text[body_end:])
        if tail:
            else_at = body_end + tail.end()
            else_end = _branch_end(text, else_at)
            spans.append(Span(lines.at(body_end), lines.at(else_end - 1), gate_line, reason, condition))
        elif _EXITS.match(body.lstrip("\n")) or _ends_in_exit(body):
            rest_end = _enclosing_end(text, body_end)
            if rest_end > body_end and text[body_end:rest_end].strip():
                spans.append(Span(lines.at(body_end), lines.at(rest_end - 1), gate_line, reason, condition))
    return sorted(spans, key=lambda s: (s.start, s.end))


def mark(rows: list[dict], spans: list[Span], path: str) -> None:
    """Set `dead`, `deadAt` and `deadReason` on every row inside a dead span, except the gate itself."""
    for row in rows:
        line = row.get("line")
        if not isinstance(line, int):
            continue
        for span in spans:
            if span.covers(line) and re.sub(r"[^\w$]", "", str(row.get("expr") or "")) != span.gate_expr:
                row["dead"] = True
                row["deadAt"] = f"{path}:{span.gate}"
                row["deadReason"] = span.reason
                break
