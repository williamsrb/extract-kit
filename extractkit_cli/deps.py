"""`extractkit deps` — every dependency a profile declares is present and runs.

A tool is `ok` when it is on PATH and its probe (if any) exits 0 within
`PROBE_TIMEOUT` seconds. `BROKEN` means on PATH but the probe fails, e.g. a
shim whose Python environment is gone. `MISSING` and `BROKEN` on a required
tool fail the run; an optional tool that is absent is `skipped`, and one that
is `BROKEN` is still shown but does not change the exit code.
"""

from __future__ import annotations

import importlib.util
import operator
import re
import shutil
import subprocess
import sys
from argparse import Namespace

from . import guide, manifest
from .common import Row

PROBE_TIMEOUT = 5

_OPERATORS = {
    ">=": operator.ge, ">": operator.gt, "<=": operator.le, "<": operator.lt,
    "==": operator.eq,
}
_BOUND = re.compile(r"^(>=|>|<=|<|==)(\d+(?:\.\d+)*)$")


def check_deps(profile: dict) -> list[Row]:
    """One Row per binary, then the Python version and module rows."""
    rows: list[Row] = []
    for dep in manifest.dependency_rows(profile):
        required = dep["required"]
        rows.append(_check_tool(dep, required))
        if dep["python"]:
            rows.append(_check_python(dep["python"], required))
        rows.extend(_check_module(m, required) for m in dep["python_modules"])
    return rows


def _check_tool(dep: dict, required: bool) -> Row:
    name = dep["name"]
    found = shutil.which(name)
    if not found:
        if not required:
            return Row(name, "skipped", "(optional)", required=False)
        return Row(name, "MISSING", fix=_install_fix(dep))
    probe = dep["probe"]
    if not probe:
        return Row(name, "ok", found, required=required)
    problem = _run_probe(probe)
    if problem:
        fix = f"reinstall {name}; check with: {' '.join(probe)}"
        return Row(name, "BROKEN", problem, fix, required)
    return Row(name, "ok", found, required=required)


def _run_probe(probe: list[str]) -> str | None:
    """None when the probe exits 0, else one line saying why it did not."""
    try:
        result = subprocess.run(
            probe, timeout=PROBE_TIMEOUT, capture_output=True, text=True, check=False,
        )
    except subprocess.TimeoutExpired:
        return f"probe timed out after {PROBE_TIMEOUT}s"
    except OSError as exc:
        return str(exc)
    if result.returncode == 0:
        return None
    return _first_error_line(result.stderr) or f"probe exited {result.returncode}"


def _first_error_line(stderr: str) -> str:
    """First non-empty stderr line; a Python traceback reports its last line."""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    if not lines:
        return ""
    return lines[-1] if lines[0].startswith("Traceback") else lines[0]


def _install_fix(dep: dict) -> str | None:
    hints = dep["install"]
    if not hints:
        return None
    return f"install {dep['name']} ({', '.join(f'{k}: {v}' for k, v in hints.items())})"


def _check_python(bound: str, required: bool) -> Row:
    match = _BOUND.match(bound)
    version = ".".join(str(n) for n in sys.version_info[:3])
    if not match:
        return Row("python", "BROKEN", f"unreadable version bound {bound!r}", required=required)
    wanted = tuple(int(n) for n in match.group(2).split("."))
    if _OPERATORS[match.group(1)](sys.version_info[: len(wanted)], wanted):
        return Row("python", "ok", f"{version} ({bound})", required=required)
    return Row(
        "python", "BROKEN", f"{version}, need {bound}",
        f"run extractkit with a python {bound}", required,
    )


def _check_module(module: str, required: bool) -> Row:
    name = f"python:{module}"
    if importlib.util.find_spec(module) is not None:
        return Row(name, "ok", sys.executable, required=required)
    return Row(
        name, "MISSING", f"not importable by {sys.executable}",
        f"install the {module} Python module into that interpreter", required,
    )


def render_row(row: Row) -> list[str]:
    lines = [f"  {row.state:8s} {row.name:22s} {row.detail}".rstrip()]
    if row.fix and row.state != "ok":
        lines.append(f"{'':11s}fix: {row.fix}")
    return lines


def cmd_deps(args: Namespace) -> int:
    profile = manifest.load(args.profile)
    rows = check_deps(profile)
    print(f"deps: profile {profile['name']}")
    for row in rows:
        for line in render_row(row):
            print(line)
    failed = [r.name for r in rows if r.failed]
    soft = [r.name for r in rows if r.state == "BROKEN" and not r.required]
    if soft:
        print(f"\nnote: optional tool(s) BROKEN, not counted as failures: {', '.join(soft)}")
    if failed:
        print(f"\n{len(failed)} required check(s) failed: {', '.join(failed)}")
        return 1
    suggestion = guide.next_for("deps", "clean", args)
    print()
    guide.emit(guide.render_next(suggestion, guide.style_for()))
    return 0
