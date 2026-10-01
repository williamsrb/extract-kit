"""Predicates in Enonic controllers that decide what a view renders.

Only branches over content data, app config or site config count, and only those
that sit at or before the last `render`/`resolve` of the controller.
"""

from __future__ import annotations

import re

from steps.core.viewscan import expr as ex
from steps.core.viewscan.base import Lines, balanced, strip_comments

_SOURCE = re.compile(
    r"\bcontent\.data\b|\bdata\.[A-Za-z_$]|\bapp\.config\b|\bconfig\.[A-Za-z_$]|getSiteConfig|\bsiteConfig\b|\bcomponent\.config\b",
)
_IF = re.compile(r"\bif\s*\(")
_TERNARY_ASSIGN = re.compile(r"\b(?:const|let|var)\s+[\w$]+\s*=\s*([^;\n]+)")


def scan(raw: str, last_view_line: int) -> list[dict]:
    text = strip_comments(raw)
    lines = Lines(text)
    found: list[dict] = []
    for match in _IF.finditer(text):
        end = balanced(text, match.end() - 1)
        if end is None:
            continue
        cond = text[match.end():end - 1]
        line = lines.at(match.start())
        if _SOURCE.search(cond) and line <= last_view_line:
            body = text[end:end + 200]
            effect = "show" if re.search(r"render|resolve|return", body) else "select"
            found.append({"expr": ex.strip_wrappers(cond), "line": line, "construct": "if", "effect": effect})
    for match in _TERNARY_ASSIGN.finditer(text):
        split = ex.split_ternary(match.group(1).strip())
        line = lines.at(match.start())
        if split and _SOURCE.search(split[0]) and line <= last_view_line:
            found.append({"expr": ex.strip_wrappers(split[0]), "line": line, "construct": "ternary", "effect": "select"})
    return sorted(found, key=lambda r: (r["line"], r["expr"]))
