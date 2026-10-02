"""The `--json` result envelope: one machine-readable document per command.

Commands keep printing their text. In JSON mode `cli.main` swallows that text
and prints one envelope instead, built from the same data the text branch
used: rows from `deps.render_row`, the suggestion from `guide.render_next`,
writes and skips from `runner.report_run`, problems from `check` and `doctor`.
Each of those calls records into the collector that is current for the run.

Schema: `schemas/result.schema.json`. Exit codes are unchanged by `--json`.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from argparse import Namespace
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ExtractkitError

SCHEMA_ID = "99x.extract.result/v1"
SECRET_WORDS = ("token", "key", "secret", "password")
# `--cms-key` names a content path, not a credential.
NOT_SECRET = frozenset({"--cms-key"})
REDACTED = "<redacted>"


@dataclass
class Collector:
    command: str
    rows: list[Any] = field(default_factory=list)
    wrote: list[dict] = field(default_factory=list)
    skips: list[dict] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    suggestion: Any = None
    phase: str | None = None
    sidecar: str | None = None
    source: str | None = None
    error: dict | None = None
    extra: dict = field(default_factory=dict)
    emitted: bool = False


_current: Collector | None = None
_last: Collector | None = None
_real_stdout: Any = None


def reset() -> None:
    """Forget the previous run's collector (in-process callers run `main` repeatedly)."""
    global _current, _last
    _current = _last = None


def current() -> Collector | None:
    return _current


def json_requested(raw: list[str]) -> bool:
    """`--json` in raw argv or `EXTRACTKIT_JSON`, for errors raised before parsing finishes."""
    if "--json" in raw:
        return True
    return os.environ.get("EXTRACTKIT_JSON", "").strip().lower() in ("1", "true", "yes")


def command_label(args: Namespace | None, raw: list[str]) -> str:
    if args is not None and getattr(args, "group", None):
        action = getattr(args, "action", None)
        return f"{args.group} {action}" if action else str(args.group)
    return next((t for t in raw if not t.startswith("-")), "extractkit")


@contextlib.contextmanager
def capture(args: Namespace, raw: list[str]) -> Iterator[Collector]:
    """Make a collector current and send the command's printed text to a buffer."""
    global _current, _last, _real_stdout
    collector = Collector(command_label(args, raw))
    _current, _last, _real_stdout = collector, collector, sys.stdout
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            yield collector
    finally:
        _current = None


# --- recorders (no-ops outside JSON mode) --------------------------------------


def note_row(row: Any) -> None:
    if _current is not None and all(row is not seen for seen in _current.rows):
        _current.rows.append(row)


def note_next(suggestion: Any) -> None:
    if _current is not None and suggestion is not None:
        _current.suggestion = suggestion


def note_problems(problems: list[str]) -> None:
    if _current is not None:
        _current.problems = list(problems)


def note_run(
    *, sidecar: Path | str | None = None, source: Path | str | None = None,
    phase: str | None = None, wrote: list[tuple[str | None, str]] | None = None,
    skips: list[dict] | None = None,
) -> None:
    c = _current
    if c is None:
        return
    if sidecar is not None:
        c.sidecar = str(sidecar)
    if source is not None:
        c.source = str(source)
    if phase is not None:
        c.phase = phase
    if wrote is not None:
        c.wrote = [{"step": step, "action": action} for step, action in wrote]
    if skips is not None:
        c.skips = [dict(s) for s in skips]


def note_error(code: str, message: str, fix: str | None = None) -> None:
    if _current is not None:
        _current.error = {"code": code, "message": message, "fix": fix, "fix_command": None}


def note_extra(**values: Any) -> None:
    if _current is not None:
        _current.extra.update(values)


# --- building ----------------------------------------------------------------


def _row_json(row: Any) -> dict:
    return {
        "name": row.name, "state": row.state, "detail": row.detail,
        "fix": row.fix, "required": row.required,
    }


def _suggestion_json(s: Any) -> dict | None:
    from . import guide

    if s is None:
        return None
    alternatives = []
    if s.alt_argv:
        alternatives.append({
            "command": guide.join(s.alt_argv), "argv": list(s.alt_argv), "reason": s.alt_reason,
        })
    return {
        "command": guide.join(s.argv), "argv": list(s.argv), "reason": s.reason,
        "alternatives": alternatives,
    }


def error_json(exc: ExtractkitError, args: Namespace | None, raw: list[str]) -> dict:
    from . import guide

    fix_command = None
    if exc.fix_args:
        prog = getattr(args, "prog_display", None) or guide.prog_display()
        fix_command = guide.join([prog, *guide.rewrite(raw, set=exc.fix_args)])
    return {"code": exc.code, "message": str(exc), "fix": exc.fix, "fix_command": fix_command}


def _implied_error(c: Collector, exit_code: int) -> dict:
    failed = next((r for r in c.rows if getattr(r, "failed", False)), None)
    if failed is not None:
        return {
            "code": failed.code or "preflight_failed",
            "message": f"{failed.name}: {failed.detail}".rstrip(": "),
            "fix": failed.fix, "fix_command": None,
        }
    message = c.problems[0] if c.problems else f"{c.command} exited {exit_code}"
    return {"code": "failed", "message": message, "fix": None, "fix_command": None}


def config_json(args: Namespace | None) -> list[dict]:
    from . import envflags

    return envflags.config_rows(args) if args is not None else []


def build(c: Collector, exit_code: int, args: Namespace | None, error: dict | None = None) -> dict:
    ok = exit_code == 0 and error is None
    err = error or c.error
    if not ok and err is None:
        err = _implied_error(c, exit_code)
    doc = {
        "schema": SCHEMA_ID,
        "ok": ok,
        "command": c.command,
        "exit": exit_code,
        "phase": c.phase,
        "sidecar": c.sidecar,
        "source": c.source,
        "rows": [_row_json(r) for r in c.rows],
        "wrote": c.wrote,
        "skips": c.skips,
        "problems": c.problems,
        "error": err,
        "next_command": _suggestion_json(c.suggestion),
        "config": config_json(args),
    }
    doc.update(c.extra)
    return doc


def print_json(doc: dict) -> None:
    out = _real_stdout or sys.stdout
    out.write(json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n")
    out.flush()


def finish(c: Collector, exit_code: int, args: Namespace | None) -> int:
    if not c.emitted:
        print_json(build(c, exit_code, args))
        c.emitted = True
    return exit_code


def fail(exc: ExtractkitError, args: Namespace | None, raw: list[str], c: Collector | None = None) -> int:
    """Print the error envelope for `exc` and return exit 1."""
    global _real_stdout
    collector = c or _current or _last or Collector(command_label(args, raw))
    if _real_stdout is None:
        _real_stdout = sys.stdout
    doc = build(collector, 1, args, error=error_json(exc, args, raw))
    print_json(doc)
    collector.emitted = True
    return 1


def emit_payload(payload: dict, args: Namespace | None = None) -> None:
    """Print an `agent *` payload: its own keys plus the envelope keys it lacks."""
    c = _current
    if c is None:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    doc = build(c, 0, args)
    doc["sidecar"] = payload.get("sidecar", doc["sidecar"])
    for key, value in payload.items():
        doc[key] = value
    print_json(doc)
    c.emitted = True
