"""Environment variables as an alternative to inline options.

Every long option `--foo-bar` has an env form `EXTRACTKIT_FOO_BAR`. Precedence:
CLI flag, then env, then the resources file (`resources.py`), then the profile
default. The layer is written once and runs in two passes around argparse:

1. `apply_defaults(parser)` walks the parser tree before parsing and sets each
   action's default from its env var. An option that is `required` and has an
   env value stops being required, so `EXTRACTKIT_SOURCE` satisfies `--source`.
2. `finish(args, raw)` runs after parsing. It drops env items from `append`
   options that raw argv also sets (argparse appends CLI values to the default
   list), refuses the forbidden variables, turns `EXTRACTKIT_STORAGE_STATE_JSON`
   into a private temp file, and records where every option came from.

No command has its own env handling. `--allow-production` and `--force` have no
env form: setting their variable is an error, never a silent no-op.
"""

from __future__ import annotations

import argparse
import atexit
import os
import shutil
import tempfile
from argparse import Namespace
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import result
from .errors import ExtractkitError

PREFIX = "EXTRACTKIT_"
FORBIDDEN = {
    "--allow-production": "EXTRACTKIT_ALLOW_PRODUCTION",
    "--force": "EXTRACTKIT_FORCE",
}
STORAGE_STATE_JSON = "EXTRACTKIT_STORAGE_STATE_JSON"
TRUE = {"1", "true", "yes"}
FALSE = {"0", "false", "no"}

# action id -> (env var, parsed default), for the parse in progress
_applied: dict[int, tuple[str, Any]] = {}


def env_name(action: argparse.Action) -> str | None:
    longs = [o for o in action.option_strings if o.startswith("--")]
    if not longs or longs[0] in ("--help", *FORBIDDEN):
        return None
    return PREFIX + longs[0][2:].upper().replace("-", "_")


def _leaves(parser: argparse.ArgumentParser) -> list[argparse.ArgumentParser]:
    """Every parser in the tree, once each (aliases share a parser)."""
    seen: dict[int, argparse.ArgumentParser] = {}

    def walk(p: argparse.ArgumentParser) -> None:
        if id(p) in seen:
            return
        seen[id(p)] = p
        for action in p._actions:
            if isinstance(action, argparse._SubParsersAction):
                for child in action.choices.values():
                    walk(child)

    walk(parser)
    return list(seen.values())


def _parse(action: argparse.Action, name: str, raw: str) -> Any:
    if isinstance(action, argparse._StoreTrueAction):
        lowered = raw.strip().lower()
        if lowered in TRUE:
            return True
        if lowered in FALSE:
            return False
        raise ExtractkitError(
            f"{name} must be 1, true, yes, 0, false or no, got {raw!r}",
            f"set {name} to one of those values, or unset it",
            code="bad_env",
        )
    if isinstance(action, argparse._AppendAction):
        return [item.strip() for item in raw.split(",") if item.strip()]
    value: Any = raw
    if action.type is not None:
        try:
            value = action.type(raw)
        except (TypeError, ValueError):
            raise ExtractkitError(
                f"{name} must be a valid value for {action.option_strings[0]}, got {raw!r}",
                f"fix or unset {name}", code="bad_env",
            ) from None
    if action.choices is not None and value not in action.choices:
        raise ExtractkitError(
            f"{name} must be one of {', '.join(map(str, action.choices))}, got {raw!r}",
            f"fix or unset {name}", code="bad_env",
        )
    return value


def apply_defaults(parser: argparse.ArgumentParser, environ: Mapping[str, str] | None = None) -> None:
    environ = os.environ if environ is None else environ
    _applied.clear()
    for leaf in _leaves(parser):
        leaf.set_defaults(_leaf=leaf)
        for action in leaf._actions:
            name = env_name(action)
            raw = environ.get(name, "").strip() if name else ""
            if not raw:
                continue
            value = _parse(action, name, raw)
            action.default = list(value) if isinstance(value, list) else value
            action.required = False
            _applied[id(action)] = (name, value)


def _in_raw(action: argparse.Action, raw: list[str]) -> bool:
    return any(
        token == option or token.startswith(option + "=")
        for token in raw for option in action.option_strings
    )


def finish(args: Namespace, raw: list[str], environ: Mapping[str, str] | None = None) -> None:
    environ = os.environ if environ is None else environ
    for option, name in FORBIDDEN.items():
        if environ.get(name, "").strip():
            raise ExtractkitError(
                f"{name} is not supported: {option} cannot be set from the environment",
                f"unset {name}; pass {option} on the command line if you mean it",
                code="env_forbidden",
            )
    leaf = getattr(args, "_leaf", None)
    origins: dict[str, str] = {}
    if leaf is not None:
        for action in leaf._actions:
            if not action.option_strings or action.dest == "help":
                continue
            applied = _applied.get(id(action))
            if _in_raw(action, raw):
                origins[action.dest] = "cli"
                if applied and isinstance(applied[1], list):
                    items = getattr(args, action.dest, None) or []
                    setattr(args, action.dest, items[len(applied[1]):])
            elif applied:
                origins[action.dest] = "env"
            else:
                origins[action.dest] = "default"
    args._origins = origins
    args._secret_dests = set()
    _storage_state_json(args, origins, environ)


def _storage_state_json(args: Namespace, origins: dict[str, str], environ: Mapping[str, str]) -> None:
    contents = environ.get(STORAGE_STATE_JSON, "")
    if not contents.strip() or not hasattr(args, "storage_state"):
        return
    if origins.get("storage_state") in ("cli", "env"):
        raise ExtractkitError(
            f"{STORAGE_STATE_JSON} conflicts with --storage-state / EXTRACTKIT_STORAGE_STATE",
            f"set only one of {STORAGE_STATE_JSON}, EXTRACTKIT_STORAGE_STATE and --storage-state",
            code="bad_env",
        )
    folder = Path(tempfile.mkdtemp(prefix="extractkit-state-"))
    atexit.register(shutil.rmtree, folder, ignore_errors=True)
    path = folder / "storage-state.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(contents)
    args.storage_state = str(path)
    origins["storage_state"] = "env"
    args._secret_dests.add("storage_state")


def _is_secret(option: str, dest: str, secret_dests: set[str]) -> bool:
    if dest in secret_dests:
        return True
    if option in result.NOT_SECRET:
        return False
    return any(word in option for word in result.SECRET_WORDS)


def config_rows(args: Namespace) -> list[dict]:
    """Every resolved option of the command as `{name, origin, value}`; secrets redacted."""
    leaf = getattr(args, "_leaf", None)
    if leaf is None:
        return []
    origins = getattr(args, "_origins", {})
    secrets = getattr(args, "_secret_dests", set())
    rows: list[dict] = []
    for action in leaf._actions:
        if not action.option_strings or action.dest == "help":
            continue
        option = next((o for o in action.option_strings if o.startswith("--")), action.option_strings[0])
        value = getattr(args, action.dest, None)
        if value is not None and _is_secret(option, action.dest, secrets):
            value = result.REDACTED
        rows.append({
            "name": option, "origin": origins.get(action.dest, "default"),
            "value": value if isinstance(value, (str, int, float, bool, list, type(None))) else str(value),
        })
    return rows
