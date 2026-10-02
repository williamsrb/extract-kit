"""`extractkit profile list|show` and `extractkit doctor`."""

from __future__ import annotations

import json
from argparse import Namespace

from . import (
    buildscope,
    deps,
    guide,
    install,
    manifest,
    readiness,
    registry,
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


def validate_profile(name: str) -> dict:
    composed = manifest.load(name)
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
    profile = validate_profile(args.name)
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
        buildscope.check(source, exclude),
    ]
