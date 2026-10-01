"""Text helpers shared by the controller and view scanners.

Comments are blanked, never removed, so every offset keeps its line.
"""

from __future__ import annotations

import bisect
import re


def strip_comments(text: str) -> str:
    """Blank `//` and `/* */` comments, keep strings and every newline."""
    out: list[str] = []
    i, n = 0, len(text)
    quote = ""
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(nxt)
                i += 2
                continue
            if ch == quote or (ch == "\n" and quote != "`"):
                quote = ""
            i += 1
            continue
        if ch in "'\"`":
            quote = ch
            out.append(ch)
        elif ch == "/" and nxt == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif ch == "/" and nxt == "*":
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            out.append("".join("\n" if c == "\n" else " " for c in text[i:end]))
            i = end
            continue
        else:
            out.append(ch)
        i += 1
    return "".join(out)


class Lines:
    """Offset to 1-based line number."""

    def __init__(self, text: str) -> None:
        self._breaks = [m.start() for m in re.finditer("\n", text)]

    def at(self, offset: int) -> int:
        return bisect.bisect_left(self._breaks, offset) + 1


def brace_block(text: str, start: int) -> tuple[int, int] | None:
    """Span of the first `{...}` at or after `start`, balanced."""
    open_at = text.find("{", start)
    if open_at < 0:
        return None
    depth = 0
    for index in range(open_at, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return open_at, index + 1
    return None


def balanced(text: str, open_at: int) -> int | None:
    """Index just past the bracket closing the one at `open_at` (`(`, `[` or `{`)."""
    closer = {"(": ")", "[": "]", "{": "}"}[text[open_at]]
    opener = text[open_at]
    depth, quote, escaped = 0, "", False
    for index in range(open_at, len(text)):
        ch = text[index]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = ""
            continue
        if ch in "'\"`":
            quote = ch
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return index + 1
    return None
