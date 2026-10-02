"""Paths, YAML/JSON helpers, and the Plan of recorded writes every command shares."""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from .errors import ExtractkitError

REPO_ROOT = Path(__file__).resolve().parent.parent

FILE_MODE = 0o644
DIR_MODE = 0o755


@dataclass
class Row:
    """One preflight line: a dependency or a target-readiness check.

    `state` is ok, MISSING, BROKEN, skipped or warn. Only a MISSING or BROKEN
    row with `required` set counts as a failure. `code` is the `--json` error
    id the row raises when it fails (`readiness_missing`, `resource_unreachable`).
    """

    name: str
    state: str
    detail: str = ""
    fix: str | None = None
    required: bool = True
    code: str | None = None

    @property
    def failed(self) -> bool:
        return self.required and self.state in ("MISSING", "BROKEN")


def ensure_dir(path: Path) -> None:
    created = [p for p in (path, *path.parents) if not p.exists()]
    path.mkdir(parents=True, exist_ok=True)
    for directory in created:
        try:
            directory.chmod(DIR_MODE)
        except OSError:
            pass


def kit_tree_of(path: Path) -> Path | None:
    """The kit tree `path` is in or under, found walking up; None outside every kit.

    A kit tree holds both `extractkit.yaml` and `extractkit_cli/cli.py`: a
    checkout of the kit repo and the installed copy look the same.
    """
    for folder in (path, *path.parents):
        if (folder / "extractkit.yaml").is_file() and (folder / "extractkit_cli" / "cli.py").is_file():
            return folder
    return None


def repo_file(name: str) -> Path:
    return REPO_ROOT / name


def load_yaml(path: Path, what: str) -> dict:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ExtractkitError(
            f"{what} not found at {path}",
            "check out the kit again, or pass an explicit path",
        ) from None
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ExtractkitError(f"{what} at {path} is not valid YAML: {exc}") from None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ExtractkitError(
            f"{what} at {path} must be a mapping, not {type(data).__name__}",
            "fix the YAML so the document is an object",
        )
    return data


def dump_yaml(payload: object) -> str:
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")
    try:
        path.chmod(FILE_MODE)
    except OSError:
        pass


def write_yaml(path: Path, payload: object) -> None:
    write_text(path, dump_yaml(payload))


def write_json(path: Path, payload: object) -> None:
    write_text(path, json.dumps(payload, indent=2, ensure_ascii=False))


def load_json(path: Path, what: str) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ExtractkitError(
            f"{what} not found at {path}",
            "run extractkit run first, or pass --out",
        ) from None
    except ValueError as exc:
        raise ExtractkitError(f"{what} at {path} is not valid JSON: {exc}") from None


def timestamp() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_kit_identity() -> dict:
    path = repo_file("extractkit.yaml")
    return load_yaml(path, "kit identity")


class Plan:
    """Records every write a command makes so its output can report them."""

    def __init__(self) -> None:
        self.step: str | None = None
        self.entries: list[tuple[str | None, str]] = []
        self.changed = False

    def record(self, action: str) -> None:
        self.entries.append((self.step, action))
        self.changed = True
