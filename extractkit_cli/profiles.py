"""`extractkit profile list|show` and `extractkit doctor`."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from . import (
    buildscope,
    context,
    deps,
    guide,
    install,
    manifest,
    readiness,
    registry,
    resources,
    result,
    schema,
    scope,
)
from .common import Row, load_kit_identity, load_yaml
from .errors import ExtractkitError
from .outtree import resolve_source


def _assert_known_adapters(profile: dict) -> None:
    adapters = profile.get("adapters") or {}
    if not isinstance(adapters, dict):
        return
    known = set(registry.all_steps())
    for slot, step_id in adapters.items():
        if step_id in (None, ""):
            continue
        if step_id not in known:
            raise ExtractkitError(
                f"profile {profile.get('name')!r} binds {slot!r} to unknown "
                f"step {step_id!r}",
                f"registered plugins: {', '.join(sorted(known)) or 'none'}",
            )


def validate_profile(name: str, out: Path | None = None, source: Path | None = None) -> dict:
    """The stack profile `name`, with the overlay layers of `out` / `source` composed in.

    `overlays` on the result lists the layer files that took part.
    """
    composed = manifest.load(name)
    if out is not None or source is not None:
        composed, layers = manifest.compose_overlays(composed, out, source)
        composed["overlays"] = layers
    schema.validate(composed, "profile", what=f"profile {name}")
    _assert_known_adapters(composed)
    return composed


def cmd_list(_args: Namespace) -> int:
    names = manifest.available()
    if not names:
        print("no profiles.")
        return 0
    print(f"{'NAME':16s} {'EXTENDS':16s} PIPELINE")
    for name in names:
        raw = load_yaml(manifest.profile_path(name), f"profile {name}")
        extends = raw.get("extends") or "—"
        composed = manifest.load(name)
        pipeline = " ".join(manifest.pipeline_ids(composed)) or "(none)"
        print(f"{name:16s} {extends!s:16s} {pipeline}")
    return 0


def cmd_show(args: Namespace) -> int:
    out = getattr(args, "out", None)
    sidecar = Path(out).expanduser().resolve() if out else None
    profile = validate_profile(args.name, sidecar, context.source_of(sidecar) if sidecar else None)
    required = manifest.provided_binaries(profile, include_optional=False)
    summary = {
        "name": profile["name"],
        "lineage": profile.get("lineage"),
        "pipeline": manifest.pipeline_ids(profile),
        "adapters": profile.get("adapters") or {},
        "todo": manifest.unfinished_work(profile),
        "required_binaries": required,
        "optional_binaries": [
            b for b in manifest.provided_binaries(profile) if b not in required
        ],
        "deps": profile.get("deps") or [],
    }
    if sidecar is not None:
        summary["overlays"] = profile.get("overlays") or []
        summary["exclude"] = profile.get("exclude") or []
        summary["live_config"] = profile.get("live_config") or {}
    print(json.dumps(summary, indent=2))
    return 0


def cmd_doctor(args: Namespace) -> int:
    load_kit_identity()
    names = [args.profile] if getattr(args, "profile", None) else manifest.available()
    if args.profile and not manifest.profile_path(args.profile).is_file():
        raise ExtractkitError(
            f"no profile named {args.profile!r}",
            f"available: {', '.join(manifest.available()) or 'none'}",
        )
    problems: list[str] = []
    checked = 0
    for name in names:
        checked += 1
        try:
            composed = validate_profile(name)
        except ExtractkitError as exc:
            line = f"{name}: {exc}"
            if exc.fix:
                line += f"\n    fix: {exc.fix}"
            problems.append(line)
            continue
        problems.extend(f"{name}: {problem}" for problem in guide.phase_problems(composed))
    rows = _preflight_rows(args)
    failed = [r for r in rows if r.failed]
    result.note_problems(problems)
    if getattr(args, "source", None):
        result.note_run(source=resolve_source(args.source))
    lines = [line for r in rows for line in deps.render_row(r)]
    if not problems and not failed:
        suggestion = guide.next_for("doctor", "clean", args)
        guide.emit(
            [f"doctor: clean ({checked} profile(s) checked).", *lines],
            guide.render_next(suggestion, guide.style_for()),
        )
        return 0
    for problem in problems:
        print(f"  {problem}")
    if lines:
        if problems:
            print()
        print("\n".join(lines))
    print(f"\ndoctor: {len(problems) + len(failed)} problem(s).")
    first_fix = next((r.fix for r in failed if r.fix), None)
    suggestion = guide.next_for("doctor", "problems", args, fix=first_fix)
    if suggestion:
        print()
        guide.emit(guide.render_next(suggestion, guide.style_for()))
    return 1


def _preflight_rows(args: Namespace) -> list[Row]:
    """Dependency and target-readiness rows; empty unless --source is given."""
    raw = getattr(args, "source", None)
    if not raw:
        return []
    source = resolve_source(raw)
    profile = manifest.load(getattr(args, "profile", None) or "core")
    exclude = scope.normalize(profile.get("exclude") or [])
    return [
        *install.install(), *deps.check_deps(profile), *readiness.check_source(source),
        _stack_row(source, exclude, getattr(args, "profile", None)),
        buildscope.check(source, exclude),
        *resources.probe_rows(args),
    ]


def _stack_row(source: Path, exclude: list[str], explicit: str | None) -> Row:
    """What `run` would pick for this checkout without `--profile`."""
    if explicit:
        return Row("stack", "ok", f"{explicit} (from --profile)", required=False)
    found = context.stack_markers(source, exclude)
    if len(found) == 1:
        name, marker = next(iter(found.items()))
        return Row("stack", "ok", f"{name} (detected from {marker})", required=False)
    detail = (
        "markers for more than one stack: " + ", ".join(f"{n} ({m})" for n, m in found.items())
        if found else "no src/main/resources/application.xml, site/site.xml or root composer.json"
    )
    return Row("stack", "warn", detail, "pass --profile enonic (or php) to run", required=False)
