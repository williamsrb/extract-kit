"""`extractkit status` (alias `next`) and `resume` — phase state of a sidecar."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from . import guide, registry, runner
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
            "run extractkit run first, or pass --out",
        )
    return latest


def optional_slots(profile: dict) -> set[str]:
    return set(profile.get("optional_slots") or [])


def optional_pending(profile: dict, out: Path) -> list[tuple[str, str]]:
    """Bound optional slots whose artifacts are absent (skipped or never run)."""
    optional = optional_slots(profile)
    return [
        (slot, plugin_id) for slot, plugin_id in runner._bound_pipeline(profile)
        if slot in optional and not step_complete(out, plugin_id)
    ]


def first_incomplete(
    profile: dict,
    out: Path,
) -> tuple[str, str] | None:
    optional = optional_slots(profile)
    rows = runner._bound_pipeline(profile)
    for slot, plugin_id in rows:
        if slot not in optional and not step_complete(out, plugin_id):
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
        fix_args={"--profile": "enonic"},
    )


def pipeline_state(profile: dict, out: Path) -> str:
    """`complete`, `cms`, `offline` (only CMS missing) or `other:<slot>`."""
    optional = optional_slots(profile)
    incomplete = [
        slot for slot, plugin_id in runner._bound_pipeline(profile)
        if slot not in optional and not step_complete(out, plugin_id)
    ]
    if not incomplete:
        return "complete"
    if incomplete[0] == guide.CMS_SLOT:
        return "offline" if len(incomplete) == 1 else "cms"
    return f"other:{incomplete[0]}"


def _missing(out: Path, plugin_id: str) -> list[str]:
    marks = DISTINCTIVE.get(plugin_id) or registry.instantiate(plugin_id).produces
    return [rel for rel in marks if rel and not _produced(out, rel)]


def status_rows(profile: dict, out: Path, style: guide.Style) -> list[str]:
    bound = dict(runner._bound_pipeline(profile))
    optional = optional_slots(profile)
    state = pipeline_state(profile, out)
    all_phases = guide.phases(profile)
    width = max((len(p.id) for p in all_phases), default=0) + 2
    current_seen = False
    lines: list[str] = []
    for phase in all_phases:
        plugins = [bound[s] for s in phase.slots if s in bound and s not in optional]
        extras = [s for s in phase.slots if s in bound and s in optional]
        skills = list(dict.fromkeys(SKILL_FOR[p] for p in plugins if p in SKILL_FOR))
        label = f"{phase.number} {phase.id:<{width}}"
        note = ""
        if phase.command == "doctor":
            mark = style.blank()
        elif phase.command:
            is_current = not current_seen and state in ("complete", "offline") \
                and phase.command == "check"
            mark = style.glyph("current" if is_current else "pending")
            current_seen = current_seen or is_current
        elif state == "offline" and guide.CMS_SLOT in phase.slots:
            mark, note = style.glyph("skip"), "not captured (optional)"
        elif all(step_complete(out, p) for p in plugins):
            mark = style.glyph("done")
        elif not current_seen:
            current_seen = True
            mark = style.glyph("current")
            missing = [rel for p in plugins for rel in _missing(out, p)]
            parts = []
            if missing:
                shown = missing[:guide.MAX_ARTIFACTS]
                extra = len(missing) - len(shown)
                parts.append("missing " + ", ".join(shown) + (f" +{extra} more" if extra else ""))
            if skills:
                parts.append("skills: " + ", ".join(skills))
            note = " · ".join(parts)
        else:
            mark = style.glyph("pending")
            note = f"skills: {', '.join(skills)}" if skills else ""
        pending = [s for s in extras if not step_complete(out, bound[s])]
        if pending and not phase.command:
            note = (note + " · " if note else "") + "optional, not captured: " + ", ".join(pending)
        lines.append(f"  {mark} {label}{note}".rstrip())
    return lines


def optional_tips(profile: dict, out: Path, args: Namespace) -> list[str]:
    """One pasteable `step` command per optional slot that has no artifacts."""
    argv = list(getattr(args, "argv", None) or [])
    prog = getattr(args, "prog_display", None) or "extractkit"
    derived = guide.sidecar_source(out)
    default = {
        "--profile": str(profile.get("name") or "enonic"),
        "--source": str(derived) if derived else guide.SOURCE_PLACEHOLDER,
    }
    tips: list[str] = []
    for slot, _plugin in optional_pending(profile, out):
        extra = guide._cms_defaults(argv) if slot == "inventory.baseline" else {}
        tokens = guide.rewrite(
            argv, command="step", keep=guide.OUTPUT_FLAGS + guide.CARRY_FLAGS,
            set={"--out": str(out), **extra}, default=default,
        )
        command = guide.join([prog, tokens[0], slot, *tokens[1:]])
        tips.append(f"{slot} not captured (optional): {command}")
    return tips[:guide.MAX_TIPS]


def cmd_status(args: Namespace) -> int:
    source = None
    if getattr(args, "source", None):
        source = resolve_source(args.source)
    out = resolve_out_dir(args, source)
    profile = _profile_from_args(args, out)
    style = guide.style_for()
    header = [f"extractkit status · {profile.get('name')} · sidecar {guide.rel_to_cwd(out)}"]
    suggestion = guide.next_for("status", pipeline_state(profile, out), args, profile, out)
    found = [] if getattr(args, "quiet", False) else optional_tips(profile, out, args)
    guide.emit(
        header + status_rows(profile, out, style),
        guide.render_tips(found, style),
        guide.render_next(suggestion, style),
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
        style = guide.style_for()
        suggestion = guide.next_for("resume", "complete", args, ctx.profile, ctx.out)
        guide.emit(
            [f"resume: nothing left to run ({guide.rel_to_cwd(ctx.out)})"],
            guide.render_next(suggestion, style),
        )
        return 0
    slot, _plugin_id = pending
    rows = runner._slice_pipeline(
        runner._bound_pipeline(ctx.profile),
        from_id=slot,
        until_id=getattr(args, "until", None),
        profile=ctx.profile,
    )
    runner._execute(ctx, rows)
    return runner.report_run(ctx, rows, args)
