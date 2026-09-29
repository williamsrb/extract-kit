"""JSON Schema load + validate for extract artifacts and profile YAML."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from .common import REPO_ROOT
from .errors import ExtractkitError

SCHEMA_DIR = REPO_ROOT / "schemas"


def schema_path(stem: str) -> Path:
    return SCHEMA_DIR / f"{stem}.schema.json"


def load_schema(stem: str) -> dict:
    path = schema_path(stem)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ExtractkitError(
            f"schema {stem!r} not found at {path}",
            "the kit checkout is incomplete; check out schemas/",
        ) from None
    except ValueError as exc:
        raise ExtractkitError(f"schema {path} is not valid JSON: {exc}") from None


def validate(instance: object, stem: str, *, what: str | None = None) -> None:
    label = what or stem
    schema = load_schema(stem)
    try:
        jsonschema.validate(instance, schema)
    except jsonschema.ValidationError as exc:
        path = ".".join(str(p) for p in exc.absolute_path) or "<root>"
        raise ExtractkitError(
            f"{label} failed schema {stem}: {exc.message} (at {path})",
            f"fix the document so it matches schemas/{stem}.schema.json",
        ) from None
