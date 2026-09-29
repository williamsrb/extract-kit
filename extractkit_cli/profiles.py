"""`extractkit profile list|show` and `extractkit doctor`."""

from __future__ import annotations

import json
from argparse import Namespace

from . import manifest, registry, schema
from .common import load_kit_identity, load_yaml
from .errors import ExtractkitError


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
            validate_profile(name)
        except ExtractkitError as exc:
            line = f"{name}: {exc}"
            if exc.fix:
                line += f"\n    fix: {exc.fix}"
            problems.append(line)
    if not problems:
        print(f"doctor: clean ({checked} profile(s) checked).")
        return 0
    for problem in problems:
        print(f"  {problem}")
    print(f"\ndoctor: {len(problems)} problem(s).")
    return 1
