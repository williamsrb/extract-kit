"""The resources file: what a pipeline supplies to extractkit, and the probes that check it.

`--resources FILE` (or `EXTRACTKIT_RESOURCES`) points at an operator-owned YAML
file validated against `schemas/resources.schema.json`. It has three sections:
`xp` (the CMS instance), `auth` (the Playwright storage state) and `agent` (the
agent CLI headless runs). A value in the file fills the matching CLI option at
the `file` precedence level: below a flag and below an env var, above the
default. No step reads a file or a database beyond the source checkout and the
storage state, so there is no section for them. Agents never write this file.

`doctor --source DIR --resources FILE` adds one row per declared resource. Each
probe has a 5 second timeout and no retries. Only the presence of an API key
variable is checked; its value is never read into output.
"""

from __future__ import annotations

import json
import os
import shutil
from argparse import Namespace
from pathlib import Path
from urllib.parse import urlparse

from . import cms_target, schema
from .common import Row, load_yaml
from .errors import ExtractkitError

PROBE_TIMEOUT = 5
CODE = "resource_unreachable"

# resources key -> option dest. The one place the file maps onto flags.
FIELDS: tuple[tuple[str, str, str], ...] = (
    ("xp", "host", "xp_host"),
    ("xp", "project", "project"),
    ("xp", "branch", "branch"),
    ("xp", "guillotine", "guillotine"),
    ("xp", "configenv", "configenv"),
    ("xp", "site_url", "site_url"),
    ("xp", "cms_keys", "cms_keys"),
    ("auth", "storage_state", "storage_state"),
    ("agent", "cli", "agent"),
    ("agent", "permissions", "agent_permissions"),
    ("agent", "allowed_tools", "allowed_tools"),
    ("agent", "timeout_seconds", "task_timeout"),
)
PATH_FIELDS = frozenset({("auth", "storage_state")})


def load(path: str | Path) -> dict:
    file = Path(path).expanduser()
    data = load_yaml(file, "resources file")
    if data is None:
        data = {}
    schema.validate(data, "resources", what=f"resources file {file}")
    return data


def apply(args: Namespace, raw: list[str]) -> None:
    """Fill options that are still at their default from the resources file."""
    path = getattr(args, "resources", None)
    if not path:
        return
    data = load(path)
    args._resources = data
    base = Path(path).expanduser().resolve().parent
    origins = getattr(args, "_origins", {})
    for section, key, dest in FIELDS:
        value = (data.get(section) or {}).get(key)
        if value is None or not hasattr(args, dest) or origins.get(dest, "default") != "default":
            continue
        if (section, key) in PATH_FIELDS:
            value = str((base / Path(value).expanduser()).resolve()) if not Path(value).expanduser().is_absolute() else str(Path(value).expanduser())
        setattr(args, dest, list(value) if isinstance(value, list) else value)
        origins[dest] = "file"
    args._origins = origins


def probe_rows(args: Namespace) -> list[Row]:
    """One row per declared resource, for `doctor --source ... --resources ...`."""
    data = getattr(args, "_resources", None)
    if data is None:
        return []
    rows: list[Row] = []
    xp = data.get("xp") or {}
    host = xp.get("host")
    state = getattr(args, "storage_state", None)
    if not host:
        detail = "offline run: CMS phase will be skipped"
        rows += [Row(name, "skipped", detail, required=False) for name in ("xp host", "guillotine", "storage state")]
    else:
        cms_target.assert_allowed(host, allow_production=False, what="resources xp.host")
        if xp.get("guillotine"):
            cms_target.assert_allowed(xp["guillotine"], allow_production=False, what="resources xp.guillotine")
        rows.append(_probe_host(host))
        rows.append(_probe_state(state, host))
        rows.append(_probe_guillotine(xp, host, state))
    rows += _agent_rows(data.get("agent") or {})
    return rows


def _row(name: str, state: str, detail: str, fix: str | None = None) -> Row:
    return Row(name, state, detail, fix, code=CODE if state != "ok" else None)


def _probe_host(host: str) -> Row:
    from steps.enonic import cms

    url = cms_target.normalize_url(host) or host
    try:
        status, _body = cms.http_get(url, "", timeout=PROBE_TIMEOUT)
    except ExtractkitError as exc:
        return _row("xp host", "MISSING", f"{url} did not answer: {exc}", "start the XP instance, or fix xp.host in the resources file")
    kind = cms_target.classify(host)
    return _row("xp host", "ok", f"{url} answered HTTP {status} ({kind})")


def _cookie_domains(path: Path) -> list[str] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    cookies = payload.get("cookies") if isinstance(payload, dict) else None
    if not isinstance(cookies, list):
        return None
    return [str(c.get("domain", "")) for c in cookies if isinstance(c, dict)]


def _probe_state(state: str | None, host: str) -> Row:
    fix = "mint a Playwright storage state for the XP host and set auth.storage_state"
    if not state:
        return _row("storage state", "MISSING", "no auth.storage_state in the resources file", fix)
    path = Path(state).expanduser()
    if not path.is_file():
        return _row("storage state", "MISSING", f"{path} does not exist", fix)
    domains = _cookie_domains(path)
    if domains is None:
        return _row("storage state", "BROKEN", f"{path} is not a Playwright storage state with a cookies array", fix)
    name = (urlparse(cms_target.normalize_url(host) or host).hostname or "").lower()
    if not any(d.lstrip(".").lower() == name or name.endswith("." + d.lstrip(".").lower()) for d in domains if d):
        return _row("storage state", "MISSING", f"{path} holds no cookie for {name}", fix)
    return _row("storage state", "ok", str(path))


def _guillotine_url(xp: dict, host: str) -> str | None:
    if xp.get("guillotine"):
        return str(xp["guillotine"])
    if xp.get("project") and xp.get("branch"):
        base = (cms_target.normalize_url(host) or host).rstrip("/")
        return f"{base}/admin/site/preview/{xp['project']}/{xp['branch']}"
    return None


def _probe_guillotine(xp: dict, host: str, state: str | None) -> Row:
    from steps.enonic import cms

    url = _guillotine_url(xp, host)
    if url is None:
        return Row("guillotine", "skipped", "set xp.guillotine, or xp.project and xp.branch", required=False)
    cookies = ""
    if state and Path(state).expanduser().is_file():
        try:
            cookies = cms.cookies_from_storage_state(Path(state).expanduser())
        except ExtractkitError:
            cookies = ""
    try:
        payload = cms.post_graphql(url, "{ __typename }", cookies, timeout=PROBE_TIMEOUT)
    except ExtractkitError as exc:
        return _row("guillotine", "MISSING", f"{url}: {exc}", "fix xp.guillotine (or xp.project and xp.branch) and the storage state")
    if payload.get("errors"):
        return _row("guillotine", "MISSING", f"{url} answered with GraphQL errors", "fix xp.guillotine")
    return _row("guillotine", "ok", url)


def _agent_rows(agent: dict) -> list[Row]:
    from . import headless

    rows: list[Row] = []
    if agent.get("cli"):
        table = headless.agent_table()
        entry = table.get(agent["cli"])
        if entry is None:
            rows.append(_row("agent cli", "MISSING", f"unknown agent {agent['cli']!r}", f"use one of: {', '.join(sorted(table))}"))
        else:
            binary = entry["argv"][0]
            found = shutil.which(binary)
            rows.append(_row("agent cli", "ok", found) if found else
                        _row("agent cli", "MISSING", f"{binary} is not on PATH", f"install {binary} or use the container image"))
    if agent.get("api_key_env"):
        name = agent["api_key_env"]
        if os.environ.get(name):
            rows.append(_row("agent api key", "ok", f"{name} is set"))
        else:
            rows.append(_row("agent api key", "MISSING", f"{name} is empty or unset", f"export {name} in the job environment (masked variable)"))
    return rows
