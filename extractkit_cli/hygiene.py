"""Hygiene hook: report only. Never deletes source files."""

from __future__ import annotations

from typing import Any

HYGIENE_REL = "hygiene/dead-code.md"

HEADER = """# Dead code (report only)

The kit does not delete source. Review and delete yourself.

"""


def after_step(ctx: Any, step_id: str) -> None:
    ctx.hygiene_notes.append(
        f"- after `{step_id}`: no deletions; static-only unused detection waits "
        "for a graft index or runtime inventory."
    )


def flush(ctx: Any) -> None:
    notes: list[str] = ctx.hygiene_notes
    body = HEADER
    if notes:
        body += "\n".join(notes) + "\n"
    else:
        body += "- No dead-code findings in this static-only pass.\n"
    ctx.write_text(HYGIENE_REL, body)
