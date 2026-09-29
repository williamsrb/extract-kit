"""Hybrid step runner: `run` (--from / --until, --apply) and `step`."""

from __future__ import annotations

from argparse import Namespace
from dataclasses import dataclass, field
from pathlib import Path

from . import manifest, registry, schema
from .common import Plan, timestamp, write_json, write_text, write_yaml
from .errors import ExtractkitError
from .hygiene import after_step
from .hygiene import flush as flush_hygiene
from .outtree import (
    build_manifest,
    ensure_self_ignore,
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
    apply: bool
    plan: Plan
    run_id: str
    skips: list[dict] = field(default_factory=list)
    map_pointers: dict[str, str | None] = field(default_factory=dict)
    hygiene_notes: list[str] = field(default_factory=list)
    cms: dict = field(default_factory=dict)
    tasks: bool = False

    def rel(self, *parts: str) -> Path:
        return self.out.joinpath(*parts)

    def write_text(self, rel: str, text: str) -> None:
        path = self.rel(rel)
        self.plan.record(f"write {path}")
        if self.apply:
            write_text(path, text)

    def write_json(self, rel: str, payload: object) -> None:
        path = self.rel(rel)
        self.plan.record(f"write {path}")
        if self.apply:
            write_json(path, payload)

    def write_yaml(self, rel: str, payload: object) -> None:
        path = self.rel(rel)
        self.plan.record(f"write {path}")
        if self.apply:
            write_yaml(path, payload)

    def record_skip(self, step_id: str, reason: str, fix: str) -> None:
        self.skips.append({"step": step_id, "reason": reason, "fix": fix})
        self.plan.record(f"skip {step_id}: {reason} (fix: {fix})")


def _bound_pipeline(profile: dict) -> list[tuple[str, str]]:
    """Return (slot, plugin_id) for each pipeline entry that is bound."""
    rows: list[tuple[str, str]] = []
    unbound_required: list[str] = []
    for slot in manifest.pipeline_ids(profile):
        plugin_id = manifest.adapter_for(profile, slot)
        if plugin_id is None:
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
) -> list[tuple[str, str]]:
    ids = [slot for slot, _ in rows]
    if only:
        matches = [(s, p) for s, p in rows if s == only or p == only]
        if not matches:
            raise ExtractkitError(
                f"step {only!r} is not in this profile's pipeline",
                f"pipeline: {', '.join(ids) or 'empty'}",
            )
        return matches
    start = 0
    end = len(rows)
    if from_id:
        start = next((i for i, (s, p) in enumerate(rows) if s == from_id or p == from_id), None)
        if start is None:
            raise ExtractkitError(
                f"--from {from_id!r} is not in this pipeline",
                f"pipeline: {', '.join(ids) or 'empty'}",
            )
    if until_id:
        idx = next((i for i, (s, p) in enumerate(rows) if s == until_id or p == until_id), None)
        if idx is None:
            raise ExtractkitError(
                f"--until {until_id!r} is not in this pipeline",
                f"pipeline: {', '.join(ids) or 'empty'}",
            )
        end = idx + 1
    return rows[start:end]


def _preflight(ctx: RunContext, rows: list[tuple[str, str]]) -> None:
    if any(plugin_id == "enonic.cms" for _, plugin_id in rows):
        from steps.enonic.cms import resolve_cms

        resolve_cms(ctx)


def _execute(ctx: RunContext, rows: list[tuple[str, str]]) -> None:
    _preflight(ctx, rows)
    ensure_self_ignore(ctx.source, ctx.plan.record)
    if ctx.apply:
        write_self_ignore(ctx.source)

    for slot, plugin_id in rows:
        step = registry.instantiate(plugin_id)
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

    flush_hygiene(ctx)
    payload = build_manifest(
        source=ctx.source,
        profile=ctx.profile,
        skips=ctx.skips,
        run_id=ctx.run_id,
        maps=ctx.map_pointers,
    )
    schema.validate(payload, "manifest", what="MANIFEST.yaml")
    ctx.write_yaml("MANIFEST.yaml", payload)


def _context_from_args(args: Namespace) -> RunContext:
    profile = validate_profile(args.profile)
    source = resolve_source(getattr(args, "source", None))
    run_id = timestamp()
    out = resolve_out(source, getattr(args, "out", None))
    if getattr(args, "out", None) is None:
        # default_out already embeds run_id via timestamp(); keep them aligned.
        run_id = out.name
    return RunContext(
        source=source,
        out=out,
        profile=profile,
        apply=bool(getattr(args, "apply", False)),
        plan=Plan(bool(getattr(args, "apply", False))),
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
            "allow_production": bool(getattr(args, "allow_production", False)),
        },
        tasks=bool(getattr(args, "tasks", False)),
    )


def cmd_run(args: Namespace) -> int:
    ctx = _context_from_args(args)
    rows = _slice_pipeline(
        _bound_pipeline(ctx.profile),
        getattr(args, "from_step", None),
        getattr(args, "until", None),
    )
    _execute(ctx, rows)
    return ctx.plan.report(f"extract {ctx.profile['name']} -> {ctx.out}")


def cmd_step(args: Namespace) -> int:
    ctx = _context_from_args(args)
    rows = _slice_pipeline(_bound_pipeline(ctx.profile), None, None, only=args.step_id)
    _execute(ctx, rows)
    return ctx.plan.report(f"step {args.step_id} -> {ctx.out}")
