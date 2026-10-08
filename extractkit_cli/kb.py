"""List and print the How-tos bundled in `kb/`.

The layout is the devkit KB's: `kb/<bucket>/How-to-*.md` with frontmatter (`id`,
`when_skills`, `read`) and a thin `llm-index.md` per bucket. The kit never loads a
How-to by itself; an agent opens one when a step needs it.
"""

from __future__ import annotations

import re
from argparse import Namespace
from pathlib import Path

from .common import REPO_ROOT
from .errors import ExtractkitError

KB_ROOT = REPO_ROOT / "kb"
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
TITLE = re.compile(r"^# (.+)$", re.MULTILINE)


def split(text: str) -> tuple[dict[str, str], str]:
    match = FRONTMATTER.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip()
    return meta, text[match.end():]


def entries(root: Path = KB_ROOT) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(root.glob("*/How-to-*.md")) if root.is_dir() else []:
        text = path.read_text(encoding="utf-8")
        meta, body = split(text)
        title = TITLE.search(body)
        skills = meta.get("when_skills", "").strip("[]")
        rows.append({
            "id": meta.get("id") or path.stem.lower(),
            "title": title.group(1) if title else path.stem,
            "path": path,
            "tokens": max(len(text) // 4, 1),
            "skills": [s.strip() for s in skills.split(",") if s.strip()],
        })
    return rows


def find(name: str, rows: list[dict]) -> dict:
    needle = name.strip().lower()
    exact = [r for r in rows if r["id"] == needle or r["path"].stem.lower() == needle]
    partial = [r for r in rows if needle and needle in r["id"]]
    hits = exact or partial
    if len(hits) == 1:
        return hits[0]
    ids = ", ".join(r["id"] for r in (hits or rows)) or "none bundled"
    problem = "no single how-to matches" if hits else "no how-to"
    raise ExtractkitError(
        f"{problem} {name!r} ({ids})", "pick an id from `extractkit kb list`", code="kb_unknown",
    )


def cmd_list(_args: Namespace) -> int:
    rows = entries()
    if not rows:
        print("no how-tos.")
        return 0
    width = max(len(r["id"]) for r in rows)
    print(f"{'ID':{width}s} {'TOKENS':>6s} PATH")
    for row in rows:
        print(f"{row['id']:{width}s} {row['tokens']:6d} {row['path']}")
    return 0


def cmd_show(args: Namespace) -> int:
    row = find(args.name, entries())
    print(split(row["path"].read_text(encoding="utf-8"))[1].lstrip("\n").rstrip("\n"))
    return 0
