"""Agent task registry: prompts stored as data that the CLI lists, renders and checks.

The kit never calls a model. A task is `agent-tasks/<id>/task.yaml` plus
`prompt.md`; a skill runs the prompt and the kit checks what it wrote.
"""

from __future__ import annotations

import re
import shlex
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path

from . import guide, manifest, progress, result, schema
from .common import REPO_ROOT, load_json, load_yaml
from .errors import ExtractkitError
from .outtree import resolve_source

TASKS_DIR = REPO_ROOT / "agent-tasks"
PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
SOURCE_UNKNOWN = "<legacy-checkout>"


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    after: str
    reads: tuple[str, ...]
    writes: tuple[str, ...]
    done: tuple[str, ...]
    done_check: str | None
    rerun: tuple[str, ...]
    promote: tuple[tuple[str, str], ...]
    checks: tuple[str, ...]
    optional: bool
    prompt: Path


def load(root: Path | None = None) -> list[Task]:
    base = root or TASKS_DIR
    tasks: list[Task] = []
    for path in sorted(base.glob("*/task.yaml")):
        raw = load_yaml(path, f"agent task {path.parent.name}")
        schema.validate(raw, "agent-task", what=f"agent-tasks/{path.parent.name}/task.yaml")
        if raw["id"] != path.parent.name:
            raise ExtractkitError(
                f"agent task id {raw['id']!r} does not match its folder {path.parent.name!r}",
                "rename the folder or fix id in task.yaml",
            )
        prompt = path.parent / "prompt.md"
        if not prompt.is_file():
            raise ExtractkitError(
                f"agent task {raw['id']} has no prompt.md",
                f"write {prompt}",
            )
        tasks.append(Task(
            id=raw["id"],
            title=raw["title"],
            after=raw["after"],
            reads=tuple(raw["reads"]),
            writes=tuple(raw["writes"]),
            done=tuple(raw.get("done") or ()),
            done_check=raw.get("done_check"),
            rerun=tuple(shlex.split(raw.get("rerun") or "")),
            promote=tuple((p["from"], p["to"]) for p in raw.get("promote") or ()),
            checks=tuple(raw.get("checks") or ()),
            optional=bool(raw.get("optional", False)),
            prompt=prompt,
        ))
    return tasks


def ordered(profile: dict | None = None, root: Path | None = None) -> list[Task]:
    """Tasks by the pipeline position of `after`, then by id."""
    pipeline = manifest.pipeline_ids(profile or manifest.load("core"))
    tasks = load(root)
    for task in tasks:
        if task.after not in pipeline:
            raise ExtractkitError(
                f"agent task {task.id} comes after {task.after!r}, which is not a pipeline slot",
                "set after to a slot in profiles/core.yaml",
            )
    return sorted(tasks, key=lambda t: (pipeline.index(t.after), t.id))


def get(task_id: str, profile: dict | None = None) -> Task:
    tasks = ordered(profile)
    for task in tasks:
        if task.id == task_id:
            return task
    raise ExtractkitError(
        f"no agent task named {task_id!r}",
        f"available: {', '.join(t.id for t in tasks)}",
    )


def _manifest(out: Path) -> dict:
    path = out / "MANIFEST.yaml"
    return load_yaml(path, "MANIFEST.yaml") if path.is_file() else {}


def profile_name(out: Path) -> str:
    return str((_manifest(out).get("source") or {}).get("profile") or "<profile>")


def source_path(out: Path) -> str:
    derived = guide.sidecar_source(out)
    if derived:
        return str(derived)
    return str((_manifest(out).get("source") or {}).get("path") or SOURCE_UNKNOWN)


def render(task: Task, out: Path, source: str | None = None, profile: str | None = None) -> str:
    values = {
        "sidecar": str(out),
        "source": source or source_path(out),
        "profile": profile if profile is not None else profile_name(out),
        "run_id": str(_manifest(out).get("run_id") or out.name),
    }
    text = task.prompt.read_text(encoding="utf-8")
    unknown = sorted({m for m in PLACEHOLDER.findall(text) if m not in values})
    if unknown:
        raise ExtractkitError(
            f"agent task {task.id} prompt uses unknown placeholder(s): "
            + ", ".join("{" + name + "}" for name in unknown),
            "use only {sidecar}, {source}, {profile} and {run_id}",
        )
    return PLACEHOLDER.sub(lambda m: values[m.group(1)], text)


def rules_named(out: Path) -> bool:
    """`rules/view-rules.json` exists and no business rule is still `extracted`."""
    path = out / "rules" / "view-rules.json"
    if not path.is_file():
        return False
    rules = load_json(path, "rules/view-rules.json").get("rules") or []
    return not any(r.get("bucket") == "business" and r.get("status") == "extracted" for r in rules)


def _overlay(out: Path) -> dict | None:
    path = out / "context" / "profile.yaml"
    return load_yaml(path, "context/profile.yaml") if path.is_file() else None


def exclude_decided(out: Path) -> bool:
    """The context overlay has an `exclude` key (an empty list counts)."""
    overlay = _overlay(out)
    return overlay is not None and "exclude" in overlay


def live_config_written(out: Path) -> bool:
    """The overlay has a `live_config` key, or no live harvest ran so there is nothing to ground."""
    if not (out / "inventory" / "live-config-candidates.json").is_file():
        return True
    overlay = _overlay(out)
    return overlay is not None and "live_config" in overlay


ENRICH_COMPLETE = "Status: complete"


def specs_enriched(out: Path) -> bool:
    """`reports/spec-enrich.md` says `Status: complete` and is newer than every spec, so no `spec.kit` run undid it.

    The report is also the progress ledger of a run that stopped midway (an exhausted credential, a timeout):
    without the status line the task is not done, and the next run skips the files it lists.
    """
    report = out / "reports" / "spec-enrich.md"
    if not report.is_file():
        return False
    if ENRICH_COMPLETE not in (line.strip() for line in report.read_text(encoding="utf-8", errors="replace").splitlines()):
        return False
    specs = list((out / "spec-kit" / "specs").rglob("spec.md")) if (out / "spec-kit" / "specs").is_dir() else []
    return all(spec.stat().st_mtime <= report.stat().st_mtime for spec in specs)


DONE_CHECKS = {
    "rules_named": rules_named,
    "exclude_decided": exclude_decided,
    "live_config_written": live_config_written,
    "specs_enriched": specs_enriched,
}


def is_done(task: Task, out: Path) -> bool:
    if task.done_check:
        return DONE_CHECKS[task.done_check](out)
    if not task.done:
        return False
    return all(progress._produced(out, rel) for rel in task.done)


def missing_reads(task: Task, out: Path) -> list[str]:
    return [rel for rel in task.reads if not progress._produced(out, rel)]


def pending(out: Path, profile: dict | None = None) -> list[Task]:
    """Required tasks that are not done, in order."""
    return [t for t in ordered(profile) if not t.optional and not is_done(t, out)]


def next_task(out: Path, profile: dict | None = None) -> Task | None:
    """The first required pending task whose inputs exist."""
    return next((t for t in pending(out, profile) if not missing_reads(t, out)), None)


def promotions(out: Path, profile: dict | None = None) -> list[tuple[Path, Path]]:
    rows: list[tuple[Path, Path]] = []
    for task in ordered(profile):
        for src_rel, dest_rel in task.promote:
            src = out / src_rel
            if src.is_file():
                rows.append((src, Path(dest_rel)))
    return rows


# --- `extractkit agent list|show|next` ------------------------------------------


def _out(args: Namespace) -> Path:
    source = resolve_source(args.source) if getattr(args, "source", None) else None
    return progress.resolve_out_dir(args, source)


def _profile(out: Path) -> dict | None:
    name = profile_name(out)
    return manifest.load(name) if name in manifest.available() else None


def _row(task: Task, out: Path) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "after": task.after,
        "state": "done" if is_done(task, out) else "pending",
        "optional": task.optional,
        "reads": list(task.reads),
        "missing_reads": missing_reads(task, out),
        "writes": list(task.writes),
        "rerun": list(task.rerun),
        "promote": [{"from": a, "to": b} for a, b in task.promote],
        "checks": list(task.checks),
    }


def _argv(args: Namespace, tail: list[str], out: Path) -> list[str]:
    prog = getattr(args, "prog_display", None) or "extractkit"
    return [prog, *guide.rewrite(["agent", *tail], keep=guide.OUTPUT_FLAGS, set={"--out": str(out)})]


def _dump(payload: dict, args: Namespace | None = None) -> None:
    result.emit_payload(payload, args)


def cmd_list(args: Namespace) -> int:
    out = _out(args)
    profile = _profile(out)
    tasks = ordered(profile)
    first = next_task(out, profile)
    rows = [_row(t, out) for t in tasks]
    if getattr(args, "json", False):
        _dump({"sidecar": str(out), "next": first.id if first else None, "tasks": rows}, args)
        return 0
    style = guide.style_for()
    width = max((len(t.id) for t in tasks), default=0) + 2
    lines = [f"extractkit agent · sidecar {guide.rel_to_cwd(out)}"]
    for task, row in zip(tasks, rows):
        if row["state"] == "done":
            mark, note = style.glyph("done"), "done"
        elif task.optional:
            mark, note = style.glyph("skip"), "optional, not done"
        elif first is not None and task.id == first.id:
            mark, note = style.glyph("current"), "pending, next"
        elif row["missing_reads"]:
            mark = style.glyph("pending")
            note = "pending, waiting on " + ", ".join(row["missing_reads"])
        else:
            mark, note = style.glyph("pending"), "pending"
        lines.append(f"  {mark} {task.id:<{width}}{note}")
    guide.emit(lines)
    return 0


def cmd_show(args: Namespace) -> int:
    out = _out(args)
    task = get(args.task_id, _profile(out))
    prompt = render(task, out)
    inputs = [
        {"path": str(out / rel), "exists": progress._produced(out, rel)} for rel in task.reads
    ]
    if getattr(args, "json", False):
        _dump({**_row(task, out), "prompt": prompt, "inputs": inputs}, args)
        return 0
    print(prompt.rstrip("\n"))
    print("\n## Input files\n")
    for item in inputs:
        print(f"- {item['path']}" + ("" if item["exists"] else "  (missing)"))
    print("\n## Output files\n")
    for rel in task.writes:
        print(f"- {out / rel}")
    if task.rerun:
        print("\n## After writing\n")
        print(f"Re-run: extractkit {' '.join(task.rerun)}")
    return 0


def cmd_next(args: Namespace) -> int:
    out = _out(args)
    profile = _profile(out)
    waiting = pending(out, profile)
    missing = {t.id: missing_reads(t, out) for t in waiting}
    task = next((t for t in waiting if not missing[t.id]), None)
    blocked = [{"id": t.id, "missing_reads": missing[t.id]} for t in waiting if missing[t.id]]
    prog = getattr(args, "prog_display", None) or "extractkit"
    if task:
        suggestion = guide.Suggestion("Read the task and do it:", _argv(args, ["show", task.id], out))
    elif blocked:
        suggestion = guide.Suggestion(
            "Finish the pipeline first:", [prog, "status", "--out", guide.rel_to_cwd(out)],
        )
    else:
        suggestion = guide.Suggestion(
            "Check the extract tree:", [prog, "check", "--out", guide.rel_to_cwd(out)],
        )
    result.note_next(suggestion)
    if getattr(args, "json", False):
        _dump({
            "sidecar": str(out),
            "next": _row(task, out) if task else None,
            "pending": [t.id for t in waiting],
            "blocked": blocked,
        }, args)
        return 0
    style = guide.style_for()
    if task:
        guide.emit(
            [f"extractkit agent · next task {task.id}: {task.title}"],
            guide.render_next(suggestion, style),
        )
        return 0
    if blocked:
        lines = ["extractkit agent · no required task can run"]
        lines.extend(f"  {b['id']} is waiting on {', '.join(b['missing_reads'])}" for b in blocked)
    else:
        lines = ["extractkit agent · no required task is pending"]
    guide.emit(lines, guide.render_next(suggestion, style))
    return 0
