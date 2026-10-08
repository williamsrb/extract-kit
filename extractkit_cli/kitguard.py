"""Refuse to run an extract from the kit workspace.

Serena, Graphify and graft act on the folder an agent session is opened in, so
an extract driven from the kit repo would onboard and index the kit. The rule
was prose in `docs/llm.md`; this makes the CLI enforce it.

A kit tree is the install root (`REPO_ROOT`) or any folder, found walking up
from a path, that holds both `extractkit.yaml` and `extractkit_cli/cli.py`. The
last test also catches a kit checkout when the CLI runs from the installed
copy. Paths are resolved first, so a symlink into a kit tree counts.
"""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from .common import REPO_ROOT, kit_tree_of
from .errors import ExtractkitError

# None of these reads a source or writes a sidecar. `kb` only prints kit files. `deps` is
# the tool half of `doctor`, and `doctor` is exempt until it is given a `--source`.
EXEMPT_COMMANDS = frozenset({"install", "deps", "profile", "kb"})


def cwd() -> Path:
    return Path.cwd()


def kit_tree(path: Path) -> Path | None:
    resolved = path.expanduser().resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        return REPO_ROOT
    return kit_tree_of(resolved)


def is_exempt(args: Namespace) -> bool:
    group = getattr(args, "group", None)
    if group in EXEMPT_COMMANDS:
        return True
    return group == "doctor" and not getattr(args, "source", None)


def refuse_kit(args: Namespace) -> None:
    """Raise `kit_workspace` when cwd, `--source` or `--out` is inside a kit tree."""
    if is_exempt(args):
        return
    candidates = [cwd(), *(Path(v) for v in (getattr(args, "source", None), getattr(args, "out", None)) if v)]
    for path in candidates:
        found = kit_tree(path)
        if found is not None:
            raise ExtractkitError(
                f"extractkit runs from the legacy checkout, not from the kit repo ({found})",
                "cd into the legacy checkout and run extractkit there; ./extractkit install puts it on PATH",
                code="kit_workspace",
            )
