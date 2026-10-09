"""Hybrid step runner: `run` (--from / --until) and `step`. Every run writes."""

from __future__ import annotations

import time
from argparse import Namespace
from dataclasses import dataclass, field
from pathlib import Path

from . import context, guide, live, manifest, readiness, registry, result, schema, scope
from .common import Plan, load_yaml, timestamp, write_json, write_text, write_yaml
from .errors import ExtractkitError
from .hygiene import after_step
from .hygiene import flush as flush_hygiene
from .outtree import (
    build_manifest,
    carry_skips,
    ensure_self_ignore,
    out_inside_source,
    resolve_out,
    resolve_source,
    write_self_ignore,
)
from .profiles import validate_profile


@dataclass
class RunContext:
    source: Path
    out: Path
    profile: dict
    plan: Plan
    run_id: str
    skips: list[dict] = field(default_factory=list)
    map_pointers: dict[str, str | None] = field(default_factory=dict)
    hygiene_notes: list[str] = field(default_factory=list)
    cms: dict = field(default_factory=dict)
    tasks: bool = False
    out_existed: bool = False
    exclude: list[str] = field(default_factory=list)

    def rel(self, *parts: str) -> Path:
        return self.out.joinpath(*parts)

    def write_text(self, rel: str, text: str) -> None:
        path = self.rel(rel)
        self.plan.record(f"write {path}")
        write_text(path, text)

    def write_json(self, rel: str, payload: object) -> None:
        path = self.rel(rel)
        self.plan.record(f"write {path}")
        write_json(path, payload)

    def write_yaml(self, rel: str, payload: object) -> None:
        path = self.rel(rel)
        self.plan.record(f"write {path}")
        write_yaml(path, payload)

    def record_skip(self, step_id: str, reason: str, fix: str) -> None:
        self.skips.append({"step": step_id, "reason": reason, "fix": fix})
        self.plan.record(f"skip {step_id}: {reason} (fix: {fix})")


def _bound_pipeline(profile: dict) -> list[tuple[str, str]]:
    """Return (slot, plugin_id) for each pipeline entry that is bound."""
    rows: list[tuple[str, str]] = []
    unbound_required: list[str] = []
    optional = set(profile.get("optional_slots") or [])
    for slot in manifest.pipeline_ids(profile):
        plugin_id = manifest.adapter_for(profile, slot)
        if plugin_id is None:
            if slot in optional:
                continue
            step_cls = None
            try:
                # Slot name may itself be a plugin id (core binds map.code to itself).
                step_cls = registry.get(slot)
            except ExtractkitError:
                step_cls = None
            required = True if step_cls is None else getattr(step_cls, "required", True)
            if required:
                unbound_required.append(slot)
            continue
        rows.append((slot, plugin_id))
    if unbound_required:
        todo = manifest.unfinished_work(profile)
        lines = [f"profile {profile.get('name')!r} has unbound required adapters: "
                 + ", ".join(unbound_required)]
        if todo:
            lines.append("unfinished work:")
            lines.extend(f"  - {item}" for item in todo)
        raise ExtractkitError(
            "\n".join(lines),
            "bind the adapters in the stack profile, or use a profile that does",
        )
    return rows


def _slice_pipeline(
    rows: list[tuple[str, str]],
    from_id: str | None,
    until_id: str | None,
    only: str | None = None,
    profile: dict | None = None,
) -> list[tuple[str, str]]:
    ids = [slot for slot, _ in rows]
    known = f"pipeline: {', '.join(ids) or 'empty'}"
    if profile:
        slot_phases = [p for p in guide.phases(profile) if p.slots]
        if slot_phases:
            known += "; phases: " + ", ".join(f"{p.id} ({p.number})" for p in slot_phases)
    if only:
        matches = [(s, p) for s, p in rows if s == only or p == only]
        if matches:
            return matches
        phase = _slot_phase(profile, only, "step", known)
        matches = [(s, p) for s, p in rows if s in phase.slots]
        if not matches:
            raise ExtractkitError(
                f"phase {phase.id!r} has no bound slots in this profile",
                known,
            )
        return matches
    start = 0
    end = len(rows)
    if from_id:
        start = _index(rows, from_id)
        if start is None:
            phase = _slot_phase(profile, from_id, "--from", known)
            start = next((i for i, (s, _) in enumerate(rows) if s in phase.slots), None)
            if start is None:
                raise ExtractkitError(f"--from phase {phase.id!r} has no bound slots", known)
    if until_id:
        idx = _index(rows, until_id)
        if idx is None:
            phase = _slot_phase(profile, until_id, "--until", known)
            hits = [i for i, (s, _) in enumerate(rows) if s in phase.slots]
            if not hits:
                raise ExtractkitError(f"--until phase {phase.id!r} has no bound slots", known)
            idx = hits[-1]
        end = idx + 1
    return rows[start:end]


COMMAND_FIX = {
    "doctor": "extractkit doctor",
    "context": "extractkit context --source <legacy-checkout>",
    "agent": "extractkit agent next --out <sidecar>",
    "check": "extractkit check --out <sidecar>",
    "promote": "extractkit promote --source <legacy-checkout> --out <sidecar>",
}


def _index(rows: list[tuple[str, str]], token: str) -> int | None:
    return next((i for i, (s, p) in enumerate(rows) if token in (s, p)), None)


def _slot_phase(profile: dict | None, token: str, flag: str, known: str) -> guide.Phase:
    phase = guide.resolve_phase(profile or {}, token)
    label = f"step {token!r}" if flag == "step" else f"{flag} {token!r}"
    if phase is None:
        raise ExtractkitError(f"{label} is not in this profile's pipeline", known)
    if phase.command:
        raise ExtractkitError(
            f"{label} is the {phase.id} phase, which is a command, not pipeline slots",
            f"run {COMMAND_FIX.get(phase.command, 'extractkit ' + phase.command)}",
        )
    return phase


def _preflight(ctx: RunContext, rows: list[tuple[str, str]]) -> None:
    ctx.map_pointers["serena"] = readiness.serena_pointer(ctx.source)
    if any(plugin_id == "enonic.cms" for _, plugin_id in rows):
        from steps.enonic.cms import resolve_cms

        resolve_cms(ctx)


def _execute(ctx: RunContext, rows: list[tuple[str, str]]) -> None:
    _preflight(ctx, rows)
    if out_inside_source(ctx.source, ctx.out):
        ensure_self_ignore(ctx.source, ctx.plan.record)
        write_self_ignore(ctx.source)

    total = len(rows)
    for index, (slot, plugin_id) in enumerate(rows, 1):
        step = registry.instantiate(plugin_id)
        ctx.plan.step = plugin_id
        began, written = time.monotonic(), len(ctx.plan.entries)
        live.say(f"step {index}/{total} {slot} ({plugin_id}) ...", indent=1)
        try:
            planned = step.plan(ctx) or []
            for action in planned:
                ctx.plan.record(action)
            step.run(ctx)
        except NotImplementedError as exc:
            raise ExtractkitError(
                str(exc) or f"step {plugin_id} is not implemented",
                "bind a real adapter, or wait for that stack's placeholder to be filled",
            ) from None
        after_step(ctx, plugin_id)
        ctx.plan.step = None
        live.say(
            f"step {index}/{total} {slot} done in {live.duration(time.monotonic() - began)}, "
            f"{len(ctx.plan.entries) - written} action(s) recorded",
            indent=1,
        )

    flush_hygiene(ctx)
    recorded = ctx.out / "MANIFEST.yaml"
    earlier = (load_yaml(recorded, "MANIFEST.yaml").get("skips") or []) if recorded.is_file() else []
    payload = build_manifest(
        source=ctx.source,
        profile=ctx.profile,
        skips=carry_skips(earlier, ctx.skips, {plugin_id for _, plugin_id in rows}),
        run_id=ctx.run_id,
        maps=ctx.map_pointers,
        exclude=ctx.exclude,
    )
    schema.validate(payload, "manifest", what="MANIFEST.yaml")
    ctx.write_yaml("MANIFEST.yaml", payload)


def _context_from_args(args: Namespace) -> RunContext:
    source = resolve_source(getattr(args, "source", None))
    run_id = timestamp()
    out = resolve_out(source, getattr(args, "out", None))
    profile = context.resolve_profile(args, source, out)
    if getattr(args, "out", None) is None:
        # default_out already embeds run_id via timestamp(); keep them aligned.
        run_id = out.name
    return RunContext(
        source=source,
        out=out,
        out_existed=out.is_dir(),
        exclude=_excludes(profile, args, out),
        profile=profile,
        plan=Plan(),
        run_id=run_id,
        cms={
            "branch": getattr(args, "branch", None),
            "xp_host": getattr(args, "xp_host", None),
            "guillotine": getattr(args, "guillotine", None),
            "project": getattr(args, "project", None),
            "storage_state": getattr(args, "storage_state", None),
            "cms_keys": list(getattr(args, "cms_keys", None) or []),
            "round2": list(getattr(args, "round2", None) or []),
            "configenv": getattr(args, "configenv", None),
            "site_url": getattr(args, "site_url", None),
            "allow_production": bool(getattr(args, "allow_production", False)),
        },
        tasks=bool(getattr(args, "tasks", False)),
    )


def _ensure_context(ctx: RunContext, args: Namespace) -> None:
    """Write the context overlay when the sidecar has none, then recompose the profile."""
    if context.overlay_path(ctx.out).is_file():
        return
    if out_inside_source(ctx.source, ctx.out):
        ensure_self_ignore(ctx.source, ctx.plan.record)
        write_self_ignore(ctx.source)
    stack = str(ctx.profile["name"])
    context.write_overlay(ctx.out, ctx.source, stack, ctx.exclude, ctx.plan.record)
    ctx.profile = validate_profile(stack, ctx.out, ctx.source)
    ctx.exclude = _excludes(ctx.profile, args, ctx.out)


def _excludes(profile: dict, args: Namespace, out: Path) -> list[str]:
    """Profile `exclude:`, `--exclude`, and what the continued sidecar already excluded."""
    recorded: list = []
    previous = out / "MANIFEST.yaml"
    if previous.is_file():
        recorded = list((load_yaml(previous, "MANIFEST.yaml") or {}).get("exclude") or [])
    return scope.normalize([
        *(profile.get("exclude") or []),
        *(getattr(args, "exclude", None) or []),
        *recorded,
    ])


def report_run(ctx: RunContext, rows: list[tuple[str, str]], args: Namespace) -> int:
    from . import progress

    style = guide.style_for()
    report = guide.Report(
        profile=ctx.profile,
        out=ctx.out,
        out_existed=ctx.out_existed,
        rows=rows,
        actions=[guide.Action(step, text) for step, text in ctx.plan.entries],
        skips=ctx.skips,
    )
    body, truncated = guide.render_body(
        report, verbose=bool(getattr(args, "verbose", False)), style=style,
    )
    found = [] if getattr(args, "quiet", False) else guide.tips(report, truncated)
    state = progress.pipeline_state(ctx.profile, ctx.out)
    suggestion = guide.next_for("run", state, args, ctx.profile, ctx.out)
    result.note_run(
        sidecar=ctx.out, source=ctx.source, phase=progress.current_phase(ctx.profile, ctx.out),
        wrote=ctx.plan.entries, skips=ctx.skips,
    )
    guide.emit(body, guide.render_tips(found, style), guide.render_next(suggestion, style))
    return 0


def cmd_run(args: Namespace) -> int:
    live.enable(args)
    ctx = _context_from_args(args)
    _ensure_context(ctx, args)
    rows = _slice_pipeline(
        _bound_pipeline(ctx.profile),
        getattr(args, "from_step", None),
        getattr(args, "until", None),
        profile=ctx.profile,
    )
    _execute(ctx, rows)
    return report_run(ctx, rows, args)


def cmd_step(args: Namespace) -> int:
    live.enable(args)
    ctx = _context_from_args(args)
    rows = _slice_pipeline(
        _bound_pipeline(ctx.profile), None, None, only=args.step_id, profile=ctx.profile,
    )
    _execute(ctx, rows)
    return report_run(ctx, rows, args)
