"""`extractkit next` and `resume` — first incomplete pipeline slot."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from . import registry, runner
from .common import load_yaml
from .errors import ExtractkitError
from .outtree import EXTRACT_DIRNAME, latest_run, resolve_source
from .profiles import validate_profile

# Distinctive artifacts so overlapping produces (e.g. project-map.json) do not
# mark a later step complete.
DISTINCTIVE: dict[str, tuple[str, ...]] = {
    "maps.merge": ("map/bounded-contexts.json", "inventory/merge-report.md"),
    "enonic.docs": ("docs/harvest/INDEX.md",),
    "product.impeccable": ("product/PRODUCT.md", "design/DESIGN.md"),
    "docs.synthesize": ("docs/technical/overview.md", "docs/guide/overview.md"),
    "use_cases": ("use-cases/",),
    "spec.kit": ("spec-kit/constitution.md",),
    "enonic.cms": ("inventory/runtime.json",),
}

SKILL_FOR: dict[str, str] = {
    "product.impeccable": "impeccable",
    "spec.kit": "extract-legacy",
    "enonic.docs": "extract-legacy",
    "enonic.cms": "extract-legacy",
    "use_cases": "extract-legacy",
    "docs.synthesize": "extract-legacy",
    "maps.merge": "extract-legacy",
}


def _produced(out: Path, rel: str) -> bool:
    path = out / rel
    if rel.endswith("/"):
        return path.is_dir() and any(path.iterdir())
    return path.is_file()


def step_complete(out: Path, plugin_id: str) -> bool:
    marks = DISTINCTIVE.get(plugin_id)
    if marks is None:
        step = registry.instantiate(plugin_id)
        marks = tuple(p for p in step.produces if p)
    if not marks:
        return True
    return all(_produced(out, rel) for rel in marks)


def resolve_out_dir(args: Namespace, source: Path | None) -> Path:
    raw = getattr(args, "out", None)
    if raw:
        path = Path(raw).expanduser().resolve()
        if not path.is_dir():
            raise ExtractkitError(
                f"--out {path} is not a directory",
                "pass an extract sidecar (the run directory, not .extract/ itself)",
            )
        return path
    if source is None:
        raise ExtractkitError(
            "no --out or --source given",
            "pass --out <sidecar> or --source so the latest .extract/<run-id> can be used",
        )
    latest = latest_run(source)
    if latest is None:
        raise ExtractkitError(
            f"no extract run under {source / EXTRACT_DIRNAME}",
            "run extractkit run --apply first, or pass --out",
        )
    return latest


def first_incomplete(
    profile: dict,
    out: Path,
) -> tuple[str, str] | None:
    rows = runner._bound_pipeline(profile)
    for slot, plugin_id in rows:
        if not step_complete(out, plugin_id):
            return slot, plugin_id
    return None


def _profile_from_args(args: Namespace, out: Path) -> dict:
    name = getattr(args, "profile", None)
    if name:
        return validate_profile(name)
    manifest_path = out / "MANIFEST.yaml"
    if manifest_path.is_file():
        payload = load_yaml(manifest_path, "MANIFEST.yaml")
        recorded = (payload.get("source") or {}).get("profile")
        if recorded:
            return validate_profile(str(recorded))
    raise ExtractkitError(
        "no --profile and MANIFEST.yaml has no source.profile",
        "pass --profile enonic (or php)",
    )


def cmd_next(args: Namespace) -> int:
    source = None
    if getattr(args, "source", None):
        source = resolve_source(args.source)
    out = resolve_out_dir(args, source)
    profile = _profile_from_args(args, out)
    pending = first_incomplete(profile, out)
    if pending is None:
        print(f"next: done ({out})")
        return 0
    slot, plugin_id = pending
    skill = SKILL_FOR.get(plugin_id)
    step = registry.instantiate(plugin_id)
    print(f"next: {plugin_id}")
    print(f"slot: {slot}")
    if skill:
        print(f"skill: {skill}")
    print("artifacts:")
    marks = DISTINCTIVE.get(plugin_id) or step.produces
    for rel in marks:
        print(f"  {out / rel}")
    print(
        f"run: extractkit step {plugin_id} --profile {profile.get('name')} "
        f"--source {source or '<source>'} --out {out} --apply"
    )
    return 0


def cmd_resume(args: Namespace) -> int:
    source = resolve_source(getattr(args, "source", None))
    if not getattr(args, "out", None):
        latest = latest_run(source)
        if latest is not None:
            args.out = str(latest)
    ctx = runner._context_from_args(args)
    pending = first_incomplete(ctx.profile, ctx.out)
    if pending is None:
        print(f"resume: already complete ({ctx.out})")
        return 0
    slot, plugin_id = pending
    rows = runner._slice_pipeline(
        runner._bound_pipeline(ctx.profile),
        from_id=slot,
        until_id=getattr(args, "until", None),
    )
    runner._execute(ctx, rows)
    return ctx.plan.report(f"resume {plugin_id} -> {ctx.out}")
