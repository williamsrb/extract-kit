"""`extractkit install` — put the kit on PATH and its skills where agents load them.

The kit runs from the checkout being extracted, not from the kit repo: Serena,
Graphify and graft act on the agent session's working directory. So the CLI
must be on PATH and the skills must be user-level. Preflight (`deps`,
`doctor --source`) runs the same install, so the first command of a run
installs the kit.

Every target is a symlink back into this repo, so a `git pull` in the kit
updates the installed copy. An existing symlink that points elsewhere is
replaced only with `--force`; a link that reaches the same endpoint by
another path counts as installed; a real file or directory is never touched.
"""

from __future__ import annotations

import os
from argparse import Namespace
from pathlib import Path

from . import deps
from .common import REPO_ROOT, Row

CLI_NAME = "extractkit"


def targets(home: Path | None = None) -> list[tuple[str, Path, Path]]:
    """(row name, link path, link target) for the CLI and every kit skill.

    Claude Code reads `~/.claude/skills/<name>`, which points at
    `~/.agents/skills/<name>` like every other user skill on the box. Codex
    and Cursor read `~/.agents/skills/` directly.
    """
    home = home or Path.home()
    agents = home / ".agents" / "skills"
    claude = home / ".claude" / "skills"
    rows = [(f"link {CLI_NAME}", home / ".local" / "bin" / CLI_NAME, REPO_ROOT / CLI_NAME)]
    for skill in sorted(p for p in (REPO_ROOT / "skills").iterdir() if (p / "SKILL.md").is_file()):
        rows.append((f"skill {skill.name}", agents / skill.name, skill))
        rows.append((f"claude {skill.name}", claude / skill.name, agents / skill.name))
    return rows


def install(*, force: bool = False, home: Path | None = None) -> list[Row]:
    """Create or repair every link; one Row each, plus a PATH row."""
    links = targets(home)
    rows = [_link(name, link, target, force) for name, link, target in links]
    rows.append(_on_path(links[0][1]))
    return rows


def _link(name: str, link: Path, target: Path, force: bool) -> Row:
    # Compare endpoints: a skill sync script may link straight to the kit, and
    # `~/.claude/skills` may itself be a link to `~/.agents/skills`.
    if link.is_symlink():
        if link.resolve() == target.resolve():
            return Row(name, "ok", str(link))
        if not force:
            return Row(
                name, "BROKEN", f"{link} points at {os.readlink(link)}",
                f"{CLI_NAME} install --force replaces the link",
            )
        link.unlink()
    elif link.exists():
        return Row(
            name, "BROKEN", f"{link} exists and is not a symlink",
            f"move {link} away, then run {CLI_NAME} install",
        )
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)
    return Row(name, "ok", f"{link} (linked)")


def _on_path(link: Path) -> Row:
    entries = [Path(p).expanduser() for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    if link.parent in entries:
        return Row("extractkit on PATH", "ok", str(link.parent))
    return Row(
        "extractkit on PATH", "MISSING", f"{link.parent} is not on PATH",
        f'add {link.parent} to PATH (export PATH="{link.parent}:$PATH")',
    )


def cmd_install(args: Namespace) -> int:
    rows = install(force=bool(getattr(args, "force", False)))
    print("install: kit at", REPO_ROOT)
    for row in rows:
        for line in deps.render_row(row):
            print(line)
    failed = [r.name for r in rows if r.failed]
    if failed:
        print(f"\n{len(failed)} install check(s) failed: {', '.join(failed)}")
        return 1
    print("\nnext  open the legacy checkout in your agent, then run from there:")
    print("  $ extractkit doctor --profile enonic --source .")
    return 0
