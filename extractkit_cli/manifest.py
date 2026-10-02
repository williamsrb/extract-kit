"""YAML profile loading and composition.

Port of 99x-dev-kit `devkit_cli/manifest.py` `load()` for YAML: `_seen` loop
detection, parent-first lists, child replace for adapter slots and the
unfinished-work field. `@allowlist:` is not ported (no consumer).

After the stack chain, `compose_overlays` layers the facts extractkit works
out for a project on top: the sidecar's `context/profile.yaml`, then the
operator's `<source>/.extractkit/profile.yaml`. An overlay sets only
`exclude` and `live_config`.
"""

from __future__ import annotations

from pathlib import Path

from .common import REPO_ROOT, load_yaml
from .errors import ExtractkitError

# Keys a child REPLACES rather than extends. `adapters` is the stack binding
# (core leaves slots null; enonic fills them). `todo` is the unfinished-work
# list: a PHP profile that declares work items means exactly those items.
OVERRIDE_KEYS = ("todo", "adapters")

# The only keys an overlay layer may set. `_comment`, `extends` and `name` are
# ignored; anything else (adapters, pipeline, phases) is the stack's business.
OVERLAY_KEYS = ("exclude", "live_config")
OVERLAY_IGNORED = ("_comment", "extends", "name")
GENERATED_OVERLAY = Path("context") / "profile.yaml"
OPERATOR_OVERLAY = Path(".extractkit") / "profile.yaml"


def profile_path(name: str, kit_root: Path | None = None) -> Path:
    return (kit_root or REPO_ROOT) / "profiles" / f"{name}.yaml"


def load(name: str, _seen: set[str] | None = None,
         kit_root: Path | None = None) -> dict:
    """Load a profile with its ancestors composed in."""
    root = kit_root or REPO_ROOT
    seen = _seen or set()
    if name in seen:
        chain = " -> ".join([*sorted(seen), name])
        raise ExtractkitError(
            f"profile inheritance loops: {chain}",
            "break the cycle by setting one profile's 'extends' to null",
        )
    seen = seen | {name}

    path = profile_path(name, root)
    if not path.is_file():
        available = sorted(p.stem for p in (root / "profiles").glob("*.yaml"))
        raise ExtractkitError(
            f"no profile named {name!r}",
            f"available: {', '.join(available) or 'none'}",
        )
    profile = load_yaml(path, f"profile {name}")

    parent_name = profile.get("extends")
    composed: dict = load(parent_name, seen, root) if parent_name else {}

    _merge(composed, profile, ("_comment", "extends"))

    if "name" not in profile:
        raise ExtractkitError(
            f"profile {name!r} has no 'name' field",
            f"set name: {name} in {path}",
        )
    composed["name"] = profile["name"]
    composed["lineage"] = [*composed.get("lineage", []), profile["name"]]
    return composed


def _merge(composed: dict, layer: dict, ignored: tuple[str, ...]) -> None:
    """Fold one layer into `composed`: child replace, parent-first lists, shallow dicts."""
    for key, value in layer.items():
        if key in ignored:
            continue
        if key in OVERRIDE_KEYS:
            composed[key] = value
        elif isinstance(value, list) and isinstance(composed.get(key), list):
            merged = list(composed[key])
            merged += [item for item in value if item not in merged]
            composed[key] = merged
        elif isinstance(value, dict) and isinstance(composed.get(key), dict):
            composed[key] = {**composed[key], **value}
        else:
            composed[key] = value


def overlay_paths(out: Path | None, source: Path | None) -> list[Path]:
    """Overlay files that exist, lowest layer first."""
    candidates = [
        out / GENERATED_OVERLAY if out else None,
        source / OPERATOR_OVERLAY if source else None,
    ]
    return [p for p in candidates if p is not None and p.is_file()]


def compose_overlays(
    composed: dict, out: Path | None, source: Path | None,
) -> tuple[dict, list[str]]:
    """Fold the sidecar overlay, then the operator override, into a stack profile.

    Returns a new profile and the layer paths that took part. Same merge rules
    as `load`. A key outside `OVERLAY_KEYS` is an error naming layer and key.
    """
    result = {**composed}
    layers: list[str] = []
    for path in overlay_paths(out, source):
        layer = load_yaml(path, "profile overlay")
        stray = [k for k in layer if k not in OVERLAY_KEYS and k not in OVERLAY_IGNORED]
        if stray:
            raise ExtractkitError(
                f"profile overlay {path} sets {', '.join(repr(k) for k in stray)}; "
                f"an overlay may set only {', '.join(OVERLAY_KEYS)}",
                "move the stack bindings to profiles/, or drop the key from the overlay",
            )
        _merge(result, layer, OVERLAY_IGNORED)
        layers.append(str(path))
    return result, layers


def available(kit_root: Path | None = None) -> list[str]:
    directory = (kit_root or REPO_ROOT) / "profiles"
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.yaml"))


def dependencies(profile: dict, include_optional: bool = True) -> list[dict]:
    deps = profile.get("deps") or []
    if not isinstance(deps, list):
        return []
    if include_optional:
        return deps
    return [d for d in deps if isinstance(d, dict) and not d.get("optional")]


def provided_binaries(profile: dict, include_optional: bool = True) -> list[str]:
    """Every binary the profile expects on PATH. `provides` is authoritative."""
    names: list[str] = []
    for dep in dependencies(profile, include_optional):
        if not isinstance(dep, dict):
            continue
        for binary in dep.get("provides") or []:
            if binary not in names:
                names.append(binary)
    return names


def dependency_rows(profile: dict) -> list[dict]:
    """One normalized row per provided binary, in declaration order.

    Keys: name, required, probe, python_modules, python, install. The probe,
    modules and Python bound belong to the dep's first binary.
    """
    rows: list[dict] = []
    seen: set[str] = set()
    for dep in dependencies(profile):
        if not isinstance(dep, dict):
            continue
        install = {k: dep[k] for k in ("apt", "dnf", "pacman") if dep.get(k)}
        for index, name in enumerate(dep.get("provides") or []):
            if name in seen:
                continue
            seen.add(name)
            first = index == 0
            rows.append({
                "name": name,
                "required": not dep.get("optional"),
                "probe": list(dep["probe"]) if first and dep.get("probe") else None,
                "python_modules": list(dep.get("python_modules") or []) if first else [],
                "python": dep.get("python") if first else None,
                "install": install,
            })
    return rows


def pipeline_ids(profile: dict) -> list[str]:
    raw = profile.get("pipeline") or []
    ids: list[str] = []
    for item in raw:
        if isinstance(item, str):
            ids.append(item)
        elif isinstance(item, dict) and item.get("id"):
            ids.append(str(item["id"]))
    return ids


def adapter_for(profile: dict, slot: str) -> str | None:
    adapters = profile.get("adapters") or {}
    if not isinstance(adapters, dict):
        return None
    value = adapters.get(slot)
    if value is None or value == "":
        return None
    return str(value)


def unfinished_work(profile: dict) -> list[str]:
    todo = profile.get("todo") or []
    if not isinstance(todo, list):
        return []
    return [str(item) for item in todo]
