"""Guided output: phases, the compact run body, tips, and the `next` footer.

Every command that reports progress renders through here, so phase lookup,
argv rewriting, glyphs and the next-command transitions change together.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import sys
from argparse import Namespace
from dataclasses import dataclass, field
from pathlib import Path

from . import manifest
from .errors import ExtractkitError

MAX_ARTIFACTS = 3
MAX_TIPS = 2
STORAGE_PLACEHOLDER = "<playwright-state.json>"
SOURCE_PLACEHOLDER = "<legacy-checkout>"
CMS_SLOT = "inventory.runtime"

# Flags that take no value, alone or clustered (`-vq`). Every other flag
# consumes the next token.
BOOLEAN_FLAGS = frozenset({
    "-v", "--verbose", "-q", "--quiet", "--force",
    "--allow-production", "--tasks", "-h", "--help",
})
CARRY_FLAGS = (
    "--branch", "--xp-host", "--guillotine", "--project", "--storage-state",
    "--cms-key", "--round2", "--configenv", "--tasks",
)
OUTPUT_FLAGS = ("-v", "--verbose", "-q", "--quiet")
PLACEHOLDER = re.compile(r"^<[A-Za-z0-9._-]+>$")


# --- phases ------------------------------------------------------------------


@dataclass(frozen=True)
class Phase:
    number: int
    id: str
    title: str
    slots: tuple[str, ...] = ()
    command: str | None = None


def phases(profile: dict) -> list[Phase]:
    rows: list[Phase] = []
    for index, raw in enumerate(profile.get("phases") or [], start=1):
        if not isinstance(raw, dict):
            continue
        rows.append(Phase(
            number=index,
            id=str(raw.get("id") or ""),
            title=str(raw.get("title") or raw.get("id") or ""),
            slots=tuple(str(s) for s in raw.get("slots") or ()),
            command=raw.get("command"),
        ))
    return rows


def resolve_phase(profile: dict, token: str | None) -> Phase | None:
    if not token:
        return None
    for phase in phases(profile):
        if token == phase.id or token == str(phase.number):
            return phase
    return None


def phase_of(profile: dict, slot: str) -> Phase | None:
    return next((p for p in phases(profile) if slot in p.slots), None)


def phase_for_command(profile: dict, command: str) -> Phase | None:
    return next((p for p in phases(profile) if p.command == command), None)


def phase_problems(profile: dict) -> list[str]:
    """Coverage problems `doctor` reports for a composed profile."""
    problems: list[str] = []
    pipeline = manifest.pipeline_ids(profile)
    seen_ids: set[str] = set()
    owner: dict[str, list[str]] = {}
    for phase in phases(profile):
        if phase.id in seen_ids:
            problems.append(f"phase id {phase.id!r} is declared twice")
        seen_ids.add(phase.id)
        for slot in phase.slots:
            if slot not in pipeline:
                problems.append(f"phase {phase.id!r} names unknown slot {slot!r}")
            owner.setdefault(slot, []).append(phase.id)
    for slot in pipeline:
        homes = owner.get(slot, [])
        if not homes:
            problems.append(f"pipeline slot {slot!r} is in no phase")
        elif len(homes) > 1:
            problems.append(
                f"pipeline slot {slot!r} is in more than one phase: {', '.join(homes)}"
            )
    return problems


# --- paths and program name --------------------------------------------------


def rel_to_cwd(path: Path | str) -> str:
    target = Path(path)
    try:
        rel = target.relative_to(Path.cwd())
    except ValueError:
        return str(target)
    return rel.as_posix()


def prog_display(argv0: str | None = None) -> str:
    raw = argv0 if argv0 is not None else sys.argv[0]
    path = Path(raw)
    if not raw or not path.is_file():
        return "extractkit"
    if path.is_absolute():
        found = shutil.which("extractkit")
        if found and Path(found).resolve() == path.resolve():
            return "extractkit"
    absolute = path.absolute()
    try:
        return "./" + absolute.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return str(absolute)


# --- argv rewrite ------------------------------------------------------------


@dataclass
class _Flag:
    name: str
    value: str | None
    inline: bool = False


def _parse(tokens: list[str]) -> tuple[str | None, list[str], list[_Flag]]:
    if not tokens:
        return None, [], []
    command, rest = tokens[0], tokens[1:]
    positionals: list[str] = []
    flags: list[_Flag] = []
    index = 0
    while index < len(rest):
        token = rest[index]
        if token.startswith("-") and token != "-":
            if "=" in token:
                name, value = token.split("=", 1)
                flags.append(_Flag(name, value, inline=True))
            elif token in BOOLEAN_FLAGS or all(f"-{c}" in BOOLEAN_FLAGS for c in token[1:]):
                flags.append(_Flag(token, None))
            else:
                value = rest[index + 1] if index + 1 < len(rest) else None
                flags.append(_Flag(token, value))
                index += 1
        else:
            positionals.append(token)
        index += 1
    return command, positionals, flags


def _path_value(value: str | None) -> str | None:
    if value is None or PLACEHOLDER.match(value):
        return value
    path = Path(value)
    if path.is_absolute():
        return rel_to_cwd(path)
    return value


def has_flag(argv: list[str], name: str) -> bool:
    return any(f.name == name for f in _parse(argv)[2])


def flag_value(argv: list[str], name: str) -> str | None:
    return next((f.value for f in _parse(argv)[2] if f.name == name), None)


def rewrite(
    argv: list[str],
    *,
    command: str | None = None,
    set: dict[str, str | None] | None = None,
    default: dict[str, str | None] | None = None,
    drop: tuple[str, ...] = (),
    keep: tuple[str, ...] | None = None,
) -> list[str]:
    """Return argv tokens with the subcommand swapped and flags edited.

    `set` replaces or adds a flag (`None` = boolean). `default` adds a flag only
    when absent. `drop` removes flags. `keep`, when given, drops every other
    flag. A changed subcommand drops positionals (only `step` has one).
    """
    old_command, positionals, flags = _parse(list(argv))
    new_command = command or old_command or ""
    if command and command != old_command:
        positionals = []
    wanted = dict(set or {})
    out: list[str] = [new_command, *positionals]
    placed: list[str] = []
    present: list[str] = []
    for flag in flags:
        if flag.name in drop or (keep is not None and flag.name not in keep
                                 and flag.name not in wanted):
            continue
        if flag.name in wanted:
            if flag.name in placed:
                continue
            placed.append(flag.name)
            value = _path_value(wanted[flag.name])
            flag = _Flag(flag.name, value, inline=flag.inline and value is not None)
        present.append(flag.name)
        out.extend(_flag_tokens(flag))
    for name, value in wanted.items():
        if name not in placed:
            out.extend(_flag_tokens(_Flag(name, _path_value(value))))
    head = 1 + len(positionals)
    added: list[str] = []
    for name, value in (default or {}).items():
        if name not in present and name not in wanted:
            added.extend(_flag_tokens(_Flag(name, _path_value(value))))
    return [*out[:head], *added, *out[head:]]


def _flag_tokens(flag: _Flag) -> list[str]:
    if flag.value is None:
        return [flag.name]
    if flag.inline:
        return [f"{flag.name}={flag.value}"]
    return [flag.name, flag.value]


def join(tokens: list[str]) -> str:
    """shlex.join, except placeholder tokens stay bare so they read as blanks."""
    return " ".join(t if PLACEHOLDER.match(t) else shlex.quote(t) for t in tokens)


# --- glyphs and colour -------------------------------------------------------

GLYPHS = {"done": "✓", "skip": "–", "current": "→", "pending": "·"}
ASCII_GLYPHS = {"done": "ok", "skip": "skip", "current": ">", "pending": "."}
COLOURS = {
    "done": "32", "skip": "33", "current": "36", "pending": "2",
    "next": "1", "tip": "36", "error": "31",
}


@dataclass
class Style:
    colour: bool
    unicode: bool

    def glyph(self, kind: str) -> str:
        table = GLYPHS if self.unicode else ASCII_GLYPHS
        width = max(len(g) for g in table.values())
        return self.paint(kind, table[kind]) + " " * (width - len(table[kind]))

    def blank(self) -> str:
        table = GLYPHS if self.unicode else ASCII_GLYPHS
        return " " * max(len(g) for g in table.values())

    def paint(self, kind: str, text: str) -> str:
        if not self.colour:
            return text
        return f"\033[{COLOURS[kind]}m{text}\033[0m"


def style_for(stream=None) -> Style:
    stream = stream or sys.stdout
    isatty = getattr(stream, "isatty", lambda: False)()
    colour = bool(isatty) and not os.environ.get("NO_COLOR")
    encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
    return Style(colour=colour, unicode=encoding == "utf8")


# --- recorded actions --------------------------------------------------------


@dataclass
class Action:
    step: str | None
    text: str

    @property
    def verb(self) -> str:
        return self.text.split(" ", 1)[0]

    def written_path(self) -> str | None:
        """Absolute path of a real write, or None for skips and summaries."""
        if self.verb == "write":
            target = _strip_note(self.text[len("write "):])
            return target if target.startswith("/") else None
        if self.verb == "promote" and " -> " in self.text:
            return _strip_note(self.text.split(" -> ", 1)[1])
        return None


def _strip_note(text: str) -> str:
    if text.endswith(")") and " (" in text:
        return text.rsplit(" (", 1)[0]
    return text


def _relativize_text(text: str) -> str:
    return " ".join(
        rel_to_cwd(tok) + ("/" if tok.endswith("/") and tok != "/" else "")
        if tok.startswith("/") else tok
        for tok in text.split(" ")
    )


def _artifact(path: str, out: Path) -> str:
    trailing = "/" if path.endswith("/") else ""
    target = Path(path.rstrip("/"))
    try:
        return target.relative_to(out).as_posix() + trailing
    except ValueError:
        return rel_to_cwd(target) + trailing


# --- run body ----------------------------------------------------------------


@dataclass
class Report:
    """What a pipeline command did, in the shape the renderer needs."""

    profile: dict
    out: Path
    out_existed: bool
    rows: list[tuple[str, str]]
    actions: list[Action]
    skips: list[dict] = field(default_factory=list)


def write_count(actions: list[Action]) -> int:
    return sum(1 for a in actions if a.written_path() is not None)


def render_body(report: Report, *, verbose: bool, style: Style) -> tuple[list[str], bool]:
    """Return the body lines and whether any artifact row was truncated."""
    state = "existing" if report.out_existed else "new"
    lines = [
        f"extractkit · {report.profile.get('name')} · sidecar {rel_to_cwd(report.out)} ({state})",
    ]
    total = len(phases(report.profile))
    skipped = {s.get("step"): s for s in report.skips}
    width = max((len(slot) for slot, _ in report.rows), default=0) + 2
    truncated = False
    groups: list[tuple[Phase | None, list[tuple[str, str]]]] = []
    for slot, plugin_id in report.rows:
        phase = phase_of(report.profile, slot)
        if groups and groups[-1][0] == phase:
            groups[-1][1].append((slot, plugin_id))
        else:
            groups.append((phase, [(slot, plugin_id)]))
    for phase, members in groups:
        lines.append("")
        lines.append(f"[{phase.number}/{total}] {phase.title}" if phase else "[?] unphased")
        for slot, plugin_id in members:
            mine = [a for a in report.actions if a.step == plugin_id]
            skip = skipped.get(plugin_id) or skipped.get(slot)
            if skip:
                lines.append(
                    f"  {style.glyph('skip')} {slot:<{width}}skipped: {skip.get('reason')}"
                )
            else:
                cells = _row_cells(mine, report.out)
                if verbose:
                    cells = []
                elif len(cells) > MAX_ARTIFACTS:
                    cells = [*cells[:MAX_ARTIFACTS], f"+{len(cells) - MAX_ARTIFACTS} more"]
                    truncated = True
                lines.append(
                    f"  {style.glyph('done')} {slot:<{width}}{', '.join(cells)}".rstrip()
                )
            if verbose:
                lines.extend(f"      {_relativize_text(a.text)}" for a in mine)
    if verbose:
        setup = [a for a in report.actions if a.step is None]
        if setup:
            lines.append("")
            lines.append("setup")
            lines.extend(f"      {_relativize_text(a.text)}" for a in setup)
    count = write_count(report.actions)
    lines.append(f"  {count} file{'' if count == 1 else 's'} written")
    return lines, truncated


def _row_cells(actions: list[Action], out: Path) -> list[str]:
    cells = [_artifact(p, out) for a in actions if (p := a.written_path())]
    if cells:
        return cells
    reused = [a for a in actions if a.verb == "reuse"]
    return [f"reused {rel_to_cwd(a.text.rsplit(' ', 1)[-1])}" for a in reused]


def render_promote(
    actions: list[Action], source: Path, *, verbose: bool, style: Style,
) -> list[str]:
    profile = manifest.load("core")
    phase = phase_for_command(profile, "promote")
    total = len(phases(profile))
    lines = [f"extractkit · promote · into {rel_to_cwd(source)}", ""]
    lines.append(f"[{phase.number}/{total}] {phase.title}" if phase else "promote")
    for action in actions:
        if verbose:
            lines.append(f"  {style.glyph('done')} {_relativize_text(action.text)}")
            continue
        dest = action.written_path()
        if dest:
            lines.append(f"  {style.glyph('done')} {_artifact(dest, source)}")
    count = write_count(actions)
    lines.append(f"  {count} file{'' if count == 1 else 's'} written")
    return lines


def tips(report: Report, truncated: bool) -> list[str]:
    found: list[str] = []
    order = {plugin: i for i, (_, plugin) in enumerate(report.rows)}
    for skip in sorted(report.skips, key=lambda s: order.get(s.get("step"), len(order))):
        if skip.get("fix"):
            found.append(f"{skip.get('step')}: {skip['fix']}")
    if truncated:
        found.append("Add -v to list every path.")
    return found[:MAX_TIPS]


def render_tips(found: list[str], style: Style) -> list[str]:
    return [f"{style.paint('tip', 'tip')}   {text}" for text in found]


# --- next-command transitions ------------------------------------------------


@dataclass
class Suggestion:
    reason: str
    argv: list[str]
    alt_reason: str | None = None
    alt_argv: list[str] | None = None


def emit(*sections: list[str]) -> None:
    """Print non-empty sections separated by one blank line."""
    print("\n\n".join("\n".join(s) for s in sections if s))


def render_next(suggestion: Suggestion | None, style: Style) -> list[str]:
    if suggestion is None:
        return []
    lines = [
        f"{style.paint('next', 'next')}  {suggestion.reason}",
        f"  $ {join(suggestion.argv)}",
    ]
    if suggestion.alt_argv:
        lines.append(f"  or {suggestion.alt_reason}:")
        lines.append(f"  $ {join(suggestion.alt_argv)}")
    return lines


def sidecar_source(out: Path) -> Path | None:
    """The checkout that owns a sidecar at `<source>/.extract/<run-id>`."""
    return out.parent.parent if out.parent.name == ".extract" else None


def _argv(args: Namespace) -> list[str]:
    return list(getattr(args, "argv", None) or [])


def _prog(args: Namespace) -> str:
    return getattr(args, "prog_display", None) or "extractkit"


def _cms_defaults(argv: list[str]) -> dict[str, str | None]:
    """--branch / --storage-state values the CMS route needs but lacks."""
    fixes: dict[str, str | None] = {}
    if not has_flag(argv, "--branch"):
        fixes["--branch"] = "draft"
    state = flag_value(argv, "--storage-state")
    if state is None or not Path(state).expanduser().is_file():
        fixes["--storage-state"] = STORAGE_PLACEHOLDER
    return fixes


def next_for(
    command: str,
    state: str | None,
    args: Namespace,
    profile: dict | None = None,
    out: Path | None = None,
    source: Path | None = None,
) -> Suggestion | None:
    """The `next` block for `command` in `state` (see the transitions table).

    Pipeline states: `cms`, `other:<slot>`, `offline`, `complete`. `check`:
    `clean`, `problems`. `promote`: `done`. `doctor` / `deps`: `clean`; any
    other state gets no block.
    """
    argv = _argv(args)
    prog = _prog(args)
    if command in ("run", "step", "resume", "status"):
        return _pipeline_next(state, argv, prog, profile or {}, out)
    if command == "check" and out is not None:
        if state == "problems":
            return Suggestion(
                "re-run after fixing the problems above",
                [prog, *rewrite(argv, command="check", keep=OUTPUT_FLAGS,
                                set={"--out": str(out)})],
            )
        source = sidecar_source(out)
        return Suggestion(
            "Copy the extract into the legacy checkout:",
            [prog, *rewrite(
                argv, command="promote", keep=OUTPUT_FLAGS, set={"--out": str(out)},
                default={"--source": str(source) if source else SOURCE_PLACEHOLDER},
            )],
        )
    if command == "promote" and source is not None:
        return Suggestion(
            "review the promoted files", ["git", "-C", rel_to_cwd(source), "status"],
        )
    if command in ("doctor", "deps") and state == "clean":
        return Suggestion(
            "start with the static inventory:",
            [prog, *rewrite(argv, command="run", keep=OUTPUT_FLAGS, set={
                "--profile": _runnable_profile(getattr(args, "profile", None)),
                "--source": SOURCE_PLACEHOLDER,
                "--until": _phase_id(manifest.load("core"), "inventory.descriptors"),
            })],
        )
    return None


def _runnable_profile(name: str | None) -> str:
    if name:
        from .runner import _bound_pipeline

        try:
            _bound_pipeline(manifest.load(name))
            return name
        except ExtractkitError:
            pass
    return "enonic"


def _phase_id(profile: dict, slot: str) -> str:
    phase = phase_of(profile, slot)
    return phase.id if phase else slot


def _pipeline_next(
    state: str | None,
    argv: list[str],
    prog: str,
    profile: dict,
    out: Path | None,
) -> Suggestion | None:
    if out is None:
        return None
    derived = sidecar_source(out)
    base_default = {
        "--profile": str(profile.get("name") or "enonic"),
        "--source": str(derived) if derived else SOURCE_PLACEHOLDER,
    }
    total = len(phases(profile))
    cms_phase = phase_of(profile, CMS_SLOT)
    merge_id = _phase_id(profile, "maps.merge")
    synthesis_id = _phase_id(profile, "spec.kit")
    check_phase = phase_for_command(profile, "check")
    check_tag = f"[{check_phase.number}/{total}] " if check_phase else ""

    def resume(extra: dict[str, str | None] | None = None) -> list[str]:
        return [prog, *rewrite(
            argv, command="resume", drop=("--from", "--until"),
            set={"--out": str(out), **(extra or {})}, default=base_default,
        )]

    def run_route(start: str, end: str, carry: bool, extra=None) -> list[str]:
        drop = ("--from", "--until") + (() if carry else CARRY_FLAGS)
        return [prog, *rewrite(
            argv, command="run", drop=drop,
            set={"--out": str(out), "--from": start, "--until": end, **(extra or {})},
            default=base_default,
        )]

    check = [prog, *rewrite(argv, command="check", keep=OUTPUT_FLAGS, set={"--out": str(out)})]

    if state == "cms":
        tag = f"[{cms_phase.number}/{total}] " if cms_phase else ""
        return Suggestion(
            f"{tag}CMS needs a local XP and a saved login:",
            resume(_cms_defaults(argv)),
            "continue without CMS",
            run_route(merge_id, synthesis_id, carry=False),
        )
    if state == "offline":
        cms_id = cms_phase.id if cms_phase else CMS_SLOT
        return Suggestion(
            f"{check_tag}Check the extract tree (CMS was not captured):",
            check,
            "add CMS data and rebuild merge and synthesis",
            run_route(cms_id, synthesis_id, carry=True, extra=_cms_defaults(argv)),
        )
    if state == "complete":
        return Suggestion(f"{check_tag}Pipeline complete. Check the extract tree:", check)
    if state and state.startswith("other:"):
        phase = phase_of(profile, state.split(":", 1)[1])
        tag = f"[{phase.number}/{total}] {phase.title} is next:" if phase else "continue:"
        return Suggestion(tag, resume())
    return None
