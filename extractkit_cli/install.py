"""`extractkit install` — copy the kit out of its checkout and put it where agents find it.

The kit runs from the checkout being extracted, not from the kit repo: Serena,
Graphify and graft act on the agent session's working directory. So the CLI
must be on PATH and the skills must be user-level. Preflight (`deps`,
`doctor --source`) runs the same install, so the first command of a run
installs the kit.

The install is detached: it copies the runtime into `~/.local/share/extractkit/`,
writes a launcher into `~/.local/bin/extractkit` and copies each skill into
`~/.agents/skills/<name>/`. Deleting the checkout afterwards breaks nothing.
`~/.claude/skills/<name>` stays a link to `~/.agents/skills/<name>`, which is
how every other user skill on the box is wired; it never points into the
checkout. Updating means running `./extractkit install` from a fresh checkout.

Ownership is proven by a marker (`.extractkit-install.json` in a folder, a
tag line in the launcher), never by the name. A folder or file the install did
not create is never touched. A symlink that resolves into a kit checkout is the
old install; it is replaced. Any other symlink is replaced only with `--force`.
Run from the installed copy, `install` copies nothing and only checks it.
"""

from __future__ import annotations

import ast
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import subprocess
from argparse import Namespace
from pathlib import Path

from . import deps, guide
from .common import REPO_ROOT, Row, kit_tree_of

CLI_NAME = "extractkit"
MARKER = ".extractkit-install.json"
LAUNCHER_TAG = "# extractkit-launcher"

# What the installed copy needs at run time. A missing entry is skipped
# (`headless/` exists only once the headless prompts do).
ROOT_FILES = ("extractkit", "extractkit.yaml")
ROOT_TREES = (
    "extractkit_cli", "steps", "profiles", "schemas", "agent-tasks",
    "templates", "headless", "skills", "kb",
)
DOCS_GLOB = "docs/*.md"
SKIP_PARTS = frozenset({"__pycache__", ".git", "tests", "graft"})


def install_root(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".local" / "share" / CLI_NAME


def launcher_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".local" / "bin" / CLI_NAME


def skill_names(repo: Path = REPO_ROOT) -> list[str]:
    return sorted(p.name for p in (repo / "skills").iterdir() if (p / "SKILL.md").is_file())


def install(*, force: bool = False, home: Path | None = None) -> list[Row]:
    """Install or check the kit; one Row each, plus a PATH row."""
    home = home or Path.home()
    if (REPO_ROOT / MARKER).is_file():
        rows = _check_installed(home)
    else:
        rows = _install_from_checkout(home, force)
    rows.append(_on_path(launcher_path(home)))
    return rows


# --- install from a checkout ------------------------------------------------


def _install_from_checkout(home: Path, force: bool) -> list[Row]:
    repo = REPO_ROOT
    rels = _runtime_files(repo)
    commit = _kit_commit(repo)
    rows = [_install_root(home, repo, rels, commit, force)]
    rows.append(_launcher(home, force))
    for name in skill_names(repo):
        agents = home / ".agents" / "skills" / name
        rows.append(_skill(name, agents, repo / "skills" / name, commit, force))
        rows.append(_claude_link(name, home / ".claude" / "skills" / name, agents, force))
    return rows


def _runtime_files(repo: Path) -> list[str]:
    found: list[str] = []
    for name in ROOT_FILES:
        if (repo / name).is_file():
            found.append(name)
    for tree in ROOT_TREES:
        if (repo / tree).is_dir():
            found.extend(_walk(repo, repo / tree))
    found.extend(sorted(p.relative_to(repo).as_posix() for p in repo.glob(DOCS_GLOB) if p.is_file()))
    ignored = _git_ignored(repo, found)
    return sorted(rel for rel in found if rel not in ignored)


def _walk(repo: Path, folder: Path) -> list[str]:
    out: list[str] = []
    for current, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_PARTS)
        for file in sorted(files):
            if file.endswith(".pyc"):
                continue
            out.append((Path(current) / file).relative_to(repo).as_posix())
    return out


def _git_ignored(repo: Path, rels: list[str]) -> set[str]:
    """Paths `git check-ignore` reports. Empty when the folder is not a git work tree."""
    if not rels:
        return set()
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "check-ignore", "-z", "--stdin"],
            input="\0".join(rels) + "\0", capture_output=True, text=True, check=False, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if result.returncode not in (0, 1):
        return set()
    return {p for p in result.stdout.split("\0") if p}


def _kit_commit(repo: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else "unknown"


def _digest(base: Path, rels: list[str]) -> str:
    h = hashlib.sha256()
    for rel in rels:
        h.update(rel.encode())
        h.update(b"\0")
        h.update((base / rel).read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _marker(commit: str, source: Path, rels: list[str], digest: str) -> str:
    payload = {
        "kit_commit": commit,
        "installed_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_path": str(source),
        "digest": digest,
        "files": rels,
    }
    return json.dumps(payload, indent=2) + "\n"


def _read_marker(folder: Path) -> dict | None:
    try:
        data = json.loads((folder / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _claim(path: Path, name: str, force: bool, *, owned: bool) -> Row | None:
    """None when `path` is free or ours to replace (after clearing it); else the BROKEN row."""
    if path.is_symlink():
        into_kit = kit_tree_of(path.resolve()) is not None
        if into_kit or force:
            path.unlink()
            return None
        return Row(
            name, "BROKEN", f"{path} points at {os.readlink(path)}",
            f"{CLI_NAME} install --force replaces the link",
        )
    if not path.exists():
        return None
    if owned:
        return None
    return Row(
        name, "BROKEN", f"{path} exists and was not created by {CLI_NAME} install",
        f"move {path} away, then run {CLI_NAME} install",
    )


def _swap(staged: Path, final: Path) -> None:
    """Move `staged` to `final`. A failure leaves the previous `final` in place."""
    old = final.with_name(f".{final.name}.old-{os.getpid()}")
    had_old = final.exists() or final.is_symlink()
    if had_old:
        final.rename(old)
    try:
        staged.rename(final)
    except OSError:
        if had_old:
            old.rename(final)
        raise
    if had_old:
        shutil.rmtree(old, ignore_errors=True)


def _stage_dir(final: Path) -> Path:
    final.parent.mkdir(parents=True, exist_ok=True)
    staged = final.with_name(f".{final.name}.new-{os.getpid()}")
    shutil.rmtree(staged, ignore_errors=True)
    staged.mkdir()
    return staged


def _copy_files(base: Path, rels: list[str], dest: Path) -> None:
    for rel in rels:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base / rel, target)


def _install_root(home: Path, repo: Path, rels: list[str], commit: str, force: bool) -> Row:
    root = install_root(home)
    digest = _digest(repo, rels)
    marker = _read_marker(root) if root.is_dir() and not root.is_symlink() else None
    refused = _claim(root, "install", force, owned=marker is not None)
    if refused:
        return refused
    if marker and marker.get("digest") == digest and marker.get("kit_commit") == commit:
        return Row("install", "ok", _install_detail(root, marker))
    staged = _stage_dir(root)
    try:
        _copy_files(repo, rels, staged)
        (staged / MARKER).write_text(_marker(commit, repo, rels, digest), encoding="utf-8")
        _swap(staged, root)
    except OSError as exc:
        shutil.rmtree(staged, ignore_errors=True)
        return Row("install", "BROKEN", f"copy to {root} failed: {exc}", "free disk space or fix permissions, then run extractkit install")
    return Row("install", "ok", _install_detail(root, _read_marker(root) or {}) + " (installed)")


def _install_detail(root: Path, marker: dict) -> str:
    return f"{root} (commit {str(marker.get('kit_commit', 'unknown'))[:12]}, installed {marker.get('installed_at', '?')})"


def _launcher_text(root: Path) -> str:
    return (
        "#!/usr/bin/env python3\n"
        f"{LAUNCHER_TAG}: written by `extractkit install`; do not edit.\n"
        "import runpy\n"
        "import sys\n"
        f"ROOT = {str(root)!r}\n"
        "sys.argv[0] = ROOT + '/extractkit'\n"
        "runpy.run_path(ROOT + '/extractkit', run_name='__main__')\n"
    )


def _is_launcher(path: Path) -> bool:
    try:
        return path.is_file() and not path.is_symlink() and LAUNCHER_TAG in path.read_text(encoding="utf-8")[:200]
    except (OSError, UnicodeDecodeError):
        return False


def launcher_root(path: Path) -> Path | None:
    """The install root a launcher file runs, or None when `path` is not a launcher."""
    if not _is_launcher(path):
        return None
    match = re.search(r"^ROOT = (.+)$", path.read_text(encoding="utf-8"), re.MULTILINE)
    try:
        return Path(ast.literal_eval(match.group(1))) if match else None
    except (ValueError, SyntaxError):
        return None


def _launcher(home: Path, force: bool) -> Row:
    path = launcher_path(home)
    name = f"launcher {CLI_NAME}"
    refused = _claim(path, name, force, owned=_is_launcher(path))
    if refused:
        return refused
    text = _launcher_text(install_root(home))
    if path.is_file() and path.read_text(encoding="utf-8") == text and os.access(path, os.X_OK):
        return Row(name, "ok", str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.new-{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    tmp.chmod(0o755)
    tmp.replace(path)
    return Row(name, "ok", f"{path} (installed)")


def _skill(name: str, agents: Path, source: Path, commit: str, force: bool) -> Row:
    row_name = f"skill {name}"
    marker = _read_marker(agents) if agents.is_dir() and not agents.is_symlink() else None
    refused = _claim(agents, row_name, force, owned=marker is not None)
    if refused:
        return refused
    rels = sorted(p.relative_to(source).as_posix() for p in source.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    digest = _digest(source, rels)
    if marker and marker.get("digest") == digest and marker.get("kit_commit") == commit:
        return Row(row_name, "ok", str(agents))
    staged = _stage_dir(agents)
    try:
        _copy_files(source, rels, staged)
        (staged / MARKER).write_text(_marker(commit, source, rels, digest), encoding="utf-8")
        _swap(staged, agents)
    except OSError as exc:
        shutil.rmtree(staged, ignore_errors=True)
        return Row(row_name, "BROKEN", f"copy to {agents} failed: {exc}", "free disk space or fix permissions, then run extractkit install")
    return Row(row_name, "ok", f"{agents} (installed)")


def _claude_link(name: str, link: Path, agents: Path, force: bool) -> Row:
    row_name = f"claude {name}"
    # Compare endpoints: `~/.claude/skills` may itself be a link to `~/.agents/skills`,
    # and a link to a skill folder that is gone still points at the right place.
    if link.resolve() == agents.resolve():
        return Row(row_name, "ok", str(link))
    refused = _claim(link, row_name, force, owned=False)
    if refused:
        return refused
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(agents)
    return Row(row_name, "ok", f"{link} (linked)")


# --- check the installed copy -----------------------------------------------


def _check_installed(home: Path) -> list[Row]:
    root = REPO_ROOT
    marker = _read_marker(root) or {}
    commit = marker.get("kit_commit", "unknown")
    fix = f"run ./{CLI_NAME} install from a kit checkout"
    rows = [Row("install", "ok", _install_detail(root, marker))]

    path = launcher_path(home)
    if launcher_root(path) == root:
        rows.append(Row(f"launcher {CLI_NAME}", "ok", str(path)))
    else:
        rows.append(Row(f"launcher {CLI_NAME}", "BROKEN", f"{path} is missing or does not run {root}", fix))
    for name in skill_names(root):
        agents = home / ".agents" / "skills" / name
        found = _read_marker(agents) if agents.is_dir() else None
        if found and found.get("kit_commit") == commit:
            rows.append(Row(f"skill {name}", "ok", str(agents)))
        elif found:
            rows.append(Row(f"skill {name}", "BROKEN", f"{agents} is from commit {str(found.get('kit_commit'))[:12]}, the kit is {str(commit)[:12]}", fix))
        else:
            rows.append(Row(f"skill {name}", "BROKEN", f"{agents} is missing or was not installed by {CLI_NAME}", fix))
        link = home / ".claude" / "skills" / name
        if link.resolve() == agents.resolve():
            rows.append(Row(f"claude {name}", "ok", str(link)))
        else:
            rows.append(Row(f"claude {name}", "BROKEN", f"{link} does not point at {agents}", fix))
    return rows


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
    guide.render_next(guide.Suggestion(
        "Open the legacy checkout in your agent, then run from there:",
        ["extractkit", "doctor", "--profile", "enonic", "--source", "."],
    ), guide.style_for())
    print("\nnext  open the legacy checkout in your agent, then run from there:")
    print("  $ extractkit doctor --profile enonic --source .")
    return 0
