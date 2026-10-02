"""Build scope: which top-level source folders a default-branch build touches.

The kit reads the build entry points it can parse without running anything:
`.gitlab-ci.yml` jobs that run on the default branch, the Makefile targets the
default goal reaches, root `package.json` scripts, and root Gradle or Maven
files. A top-level folder no entry point names is reported, never excluded:
the operator decides with `--exclude` or the profile's `exclude:` list.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .common import Row
from .scope import SKIP_DIRS, is_excluded

CI_FILE = ".gitlab-ci.yml"
ROOT_BUILD_FILES = ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "pom.xml")
# Folders a root Gradle or Maven build compiles without naming them.
CONVENTIONAL_DIRS = frozenset({"src"})
CI_RESERVED = frozenset({
    "stages", "variables", "include", "default", "workflow", "image", "services",
    "before_script", "after_script", "cache", "pages",
})
CI_TEXT_KEYS = ("before_script", "script", "after_script", "variables")
_MAKE_RULE = re.compile(r"^([A-Za-z0-9_./-]+)\s*:(?![=:])\s*([^#]*)")
_MAKE_VAR = re.compile(r"^([A-Za-z0-9_]+)\s*[:+?]?=\s*(.*)$")
_MAKE_REF = re.compile(r"\$[({]([A-Za-z0-9_]+)[)}]")


@dataclass
class BuildScope:
    branch: str
    entry_points: list[str] = field(default_factory=list)
    in_scope: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)


def check(source: Path, exclude: list[str] | None = None) -> Row:
    """One doctor row. A folder outside every default-branch build only warns."""
    scope = analyze(source, exclude or [])
    if not scope.entry_points:
        return Row(
            "build scope", "skipped",
            "no .gitlab-ci.yml, Makefile, package.json scripts or root Gradle/Maven file",
            required=False,
        )
    read = ", ".join(scope.entry_points)
    if not scope.out_of_scope:
        return Row("build scope", "ok", f"every top-level folder is in a {scope.branch} build ({read})")
    flags = " ".join(f"--exclude {name}" for name in scope.out_of_scope)
    return Row(
        "build scope", "warn",
        f"not in any {scope.branch} build ({read}): {', '.join(scope.out_of_scope)}",
        f"if they are not part of the product, pass `{flags}` to run, "
        "or list them under `exclude:` in the profile",
        required=False,
    )


def analyze(source: Path, exclude: list[str]) -> BuildScope:
    branch = default_branch(source)
    scope = BuildScope(branch=branch)
    texts: list[str] = []
    for name, reader in (
        (CI_FILE, lambda: _ci_text(source / CI_FILE, branch)),
        ("Makefile", lambda: _make_text(source / "Makefile")),
        ("package.json", lambda: _package_text(source / "package.json")),
    ):
        if (source / name).is_file():
            scope.entry_points.append(name)
            texts.append(reader())
    root_builds = [n for n in ROOT_BUILD_FILES if (source / n).is_file()]
    for name in root_builds:
        scope.entry_points.append(name)
        texts.append((source / name).read_text(encoding="utf-8", errors="replace"))
    corpus = "\n".join(texts)
    for folder in _top_level_dirs(source):
        if is_excluded(folder, exclude):
            scope.excluded.append(folder)
        elif (root_builds and folder in CONVENTIONAL_DIRS) or _mentions(corpus, folder):
            scope.in_scope.append(folder)
        else:
            scope.out_of_scope.append(folder)
    return scope


def default_branch(source: Path) -> str:
    """origin/HEAD, else a local main or master, else the checked-out branch."""
    head = _git(source, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if head:
        return head.split("/", 1)[-1]
    for name in ("main", "master"):
        if _git(source, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}"):
            return name
    return _git(source, "branch", "--show-current") or "main"


def _git(source: Path, *args: str) -> str:
    try:
        done = subprocess.run(
            ["git", "-C", str(source), *args],
            capture_output=True, text=True, check=False, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def _top_level_dirs(source: Path) -> list[str]:
    return sorted(
        p.name for p in source.iterdir()
        if p.is_dir() and not p.is_symlink() and not p.name.startswith(".") and p.name not in SKIP_DIRS
    )


def _mentions(corpus: str, folder: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(folder)}(?![\w-])", corpus) is not None


class _CiLoader(yaml.SafeLoader):
    """GitLab tags such as `!reference` load as plain values."""


def _any_tag(loader: yaml.SafeLoader, _suffix: str, node: yaml.Node) -> object:
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


_CiLoader.add_multi_constructor("!", _any_tag)


def _ci_text(path: Path, branch: str) -> str:
    try:
        doc = yaml.load(path.read_text(encoding="utf-8"), Loader=_CiLoader)
    except (OSError, yaml.YAMLError):
        return ""
    if not isinstance(doc, dict):
        return ""
    jobs = {
        name: _resolve(doc, name, set())
        for name, body in doc.items()
        if isinstance(body, dict) and not name.startswith(".") and name not in CI_RESERVED
    }
    running = [job for job in jobs.values() if _runs_on(job, branch)]
    parts = [json.dumps({k: job.get(k) for k in CI_TEXT_KEYS}) for job in running]
    if running:
        default = doc.get("default") if isinstance(doc.get("default"), dict) else {}
        parts.append(json.dumps([doc.get("before_script"), doc.get("after_script"), default]))
    return "\n".join(parts)


def _resolve(doc: dict, name: str, seen: set[str]) -> dict:
    body = doc.get(name)
    if not isinstance(body, dict) or name in seen:
        return {}
    merged: dict = {}
    parents = body.get("extends") or []
    for parent in [parents] if isinstance(parents, str) else parents:
        merged.update(_resolve(doc, str(parent), seen | {name}))
    merged.update({k: v for k, v in body.items() if k != "extends"})
    return merged


def _runs_on(job: dict, branch: str) -> bool:
    """True unless only/except/rules keep the job off the default branch."""
    if "rules" in job and isinstance(job["rules"], list):
        for rule in job["rules"]:
            if not isinstance(rule, dict) or rule.get("when") == "never":
                continue
            cond = str(rule.get("if") or "")
            if not cond or "CI_DEFAULT_BRANCH" in cond or re.search(rf"[\"']{re.escape(branch)}[\"']", cond):
                return True
        return False
    if _matches(job.get("except"), branch):
        return False
    only = job.get("only")
    return only is None or _matches(only, branch)


def _matches(spec: object, branch: str) -> bool:
    refs = spec.get("refs") if isinstance(spec, dict) else spec
    if isinstance(refs, str):
        refs = [refs]
    for ref in refs or []:
        text = str(ref)
        if text in (branch, "branches", "pushes", "web", "schedules"):
            return True
        if len(text) > 2 and text.startswith("/") and text.rstrip("i").endswith("/"):
            try:
                if re.search(text.strip("/i"), branch):
                    return True
            except re.error:
                continue
    return False


def _make_text(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    rules: dict[str, tuple[list[str], list[str]]] = {}
    variables: dict[str, str] = {}
    order: list[str] = []
    current: str | None = None
    for line in lines:
        if line.startswith("\t"):
            if current:
                rules[current][1].append(line)
            continue
        current = None
        if (var := _MAKE_VAR.match(line)) and not _MAKE_RULE.match(line.replace(":=", "=")):
            variables[var.group(1)] = var.group(2)
            continue
        if rule := _MAKE_RULE.match(line):
            current = rule.group(1)
            rules.setdefault(current, ([], []))[0].extend(rule.group(2).split())
            if not current.startswith("."):
                order.append(current)
    if not order:
        return ""
    reached: list[str] = []
    pending = [order[0]]
    while pending:
        target = pending.pop()
        if target in reached or target not in rules:
            continue
        reached.append(target)
        pending.extend(rules[target][0])
    recipes = "\n".join(line for t in reached for line in rules[t][1])
    used = set(_MAKE_REF.findall(recipes))
    return recipes + "\n" + "\n".join(v for k, v in variables.items() if k in used)


def _package_text(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    scripts = data.get("scripts") if isinstance(data, dict) else None
    return "\n".join(str(v) for v in scripts.values()) if isinstance(scripts, dict) else ""
