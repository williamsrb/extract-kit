"""Business conditions in server-side JS: status comparisons, amount arithmetic, date math, role checks.

The view scanners read templates and frontend code. Behavior also lives in `lib/**`,
`services/**`, `tasks/**` and `cron/**`: a booking moves between states, a price is
worked out, a job compares dates, a service checks a role. Each match is recorded
verbatim with its line, like every other predicate, for `core.view_rules` to score.
"""

from __future__ import annotations

import re

from steps.core.viewscan import expr as ex
from steps.core.viewscan.base import Lines, balanced, strip_comments

_IF = re.compile(r"\b(?:if|while)\s*\(")
_TERNARY = re.compile(r"\b(?:const|let|var)\s+[\w$]+\s*=\s*([^;\n]+)")
_RETURN = re.compile(r"\breturn\s+(?P<v>[^;\n]+)")
_ASSIGN = re.compile(
    r"(?:\b(?:const|let|var)\s+)?(?P<name>[\w$.]+)\s*(?P<op>[-+*/]?=)(?!=)\s*(?P<rhs>[^;\n]+)",
)

_STATUS = re.compile(r"\b[\w$.]*[Ss]tatus\b|\bSTATUS\b|\bstate\b")
_ROLE = re.compile(r"\bhasRole\s*\(|\bisAdmin\b|\bisUnauthori[sz]ed\w*\b|\bgetMemberships\s*\(")
_DATE = re.compile(
    r"\bnew\s+Date\b|\bDate\.(?:now|parse|UTC)\b|\.getTime\s*\(|\.(?:set|get)(?:Date|Month|FullYear|Hours)\s*\(|"
    r"\bmoment\s*\(|\.(?:isBefore|isAfter|diff|add|subtract)\s*\(|\*\s*1000\b|\b(?:expire\w*|deadline|dueDate|"
    r"departure\w*|checkin|checkout|cutoff)\b",
    re.IGNORECASE,
)
_AMOUNT = re.compile(
    r"\b[\w$.]*(?:amount|price|total|fee|vat|tax|discount|deposit|payment|balance|currency|commission|rate|"
    r"markup|margin|cost)\w*\b",
    re.IGNORECASE,
)
_DATE_MATH = re.compile(r"\.(?:setDate|setMonth|setFullYear|add|subtract)\s*\(|\*\s*1000\b|\bdiff\w*", re.IGNORECASE)
_COMPARE = re.compile(r"[<>]=?|[!=]==?|\.includes\(|\.indexOf\(")
_ARITH = re.compile(r"[\w)\]]\s*[-+*/%]\s*[\w($]")
# Timing and text templating are arithmetic on a clock or a string, not business logic.
_NOISE = re.compile(r"\bDate\.now\s*\(\)\s*-|\.getTime\s*\(\)\s*-\s*\w*(?:start|began)\w*|\.(?:replace|replaceAll)\s*\(|\bMillis\b", re.IGNORECASE)
_NOT_ARITH_ONLY_STRING = re.compile(r"""^\s*(['"`]).*\1\s*$""", re.DOTALL)


def _effect(cond: str, assign: bool) -> str | None:
    """The rule effect for a condition or computed value, or None when it is not business logic."""
    masked = re.sub(r"""(['"`])(?:\\.|(?!\1).)*\1""", '""', cond)
    if _ROLE.search(masked):
        return "authorize"
    if assign:
        if _NOISE.search(masked):
            return None
        worked = _ARITH.search(masked) and (_AMOUNT.search(masked) or _DATE.search(masked))
        if (worked or _DATE_MATH.search(masked)) and not _NOT_ARITH_ONLY_STRING.match(cond):
            return "compute"
        return None
    if _STATUS.search(masked) and _COMPARE.search(cond):
        return "transition"
    if (_DATE.search(masked) or _AMOUNT.search(masked)) and (_COMPARE.search(masked) or _ARITH.search(masked)):
        return "validate"
    return None


def _closed(text: str) -> bool:
    """False for a fragment cut mid-expression: an odd backtick or unbalanced brackets."""
    return text.count("`") % 2 == 0 and all(
        text.count(open_) == text.count(close) for open_, close in ("()", "[]", "{}")
    )


def scan(raw: str) -> list[dict]:
    text = strip_comments(raw)
    lines = Lines(text)
    found: list[dict] = []
    for match in _IF.finditer(text):
        end = balanced(text, match.end() - 1)
        if end is None:
            continue
        cond = " ".join(text[match.end():end - 1].split())
        effect = _effect(cond, assign=False)
        if effect:
            found.append({
                "expr": ex.strip_wrappers(cond), "line": lines.at(match.start()),
                "construct": match.group(0).split("(")[0].strip(), "effect": effect,
            })
    for match in _TERNARY.finditer(text):
        split = ex.split_ternary(match.group(1).strip())
        if split:
            effect = _effect(split[0], assign=False)
            if effect:
                found.append({
                    "expr": ex.strip_wrappers(split[0]), "line": lines.at(match.start()),
                    "construct": "ternary", "effect": effect,
                })
    for match in _RETURN.finditer(text):
        value = match.group("v").strip()
        effect = _effect(value, assign=False) if _closed(value) and re.search(r"&&|\|\||[<>=!]=", value) else None
        if effect:
            found.append({
                "expr": ex.strip_wrappers(value), "line": lines.at(match.start()),
                "construct": "return", "effect": effect,
            })
    for match in _ASSIGN.finditer(text):
        rhs = match.group("rhs").strip().rstrip(",")
        if match.group("op") != "=":
            rhs = f"{match.group('name')} {match.group('op')[0]} {rhs}"
        if _closed(rhs) and _effect(f"{match.group('name')} {rhs}", assign=True):
            found.append({
                "expr": ex.strip_wrappers(rhs), "line": lines.at(match.start()),
                "construct": "assign", "effect": "compute",
            })
    return sorted(found, key=lambda r: (r["line"], r["construct"], r["expr"]))
