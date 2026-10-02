"""Live Site Config and Config Env harvest.

Site Config is Content Studio REST (Guillotine dataAsJson omits it on XP7 CS 5.2).
Config Env is an admin-tool HTML table (no list JSON API) at the profile's
`live_config.configenv_path`.
Secrets are dropped. URLs are metadata only — never fetched.

Every client rule (which config keys hold endpoints, which provider they belong
to, how an environment value maps to an origin) comes from the profile key
`live_config`; this module names no client.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from html import unescape
from typing import Any
from urllib.parse import quote

from extractkit_cli.common import load_yaml
from extractkit_cli.errors import ExtractkitError

SECRET_MARKERS = (
    "password",
    "token",
    "secret",
    "apikey",
)
CONFIG_URL_SUFFIXES = ("endpoint",)


@dataclass(frozen=True)
class EnvRule:
    """A site-config leaf key whose value picks an origin; `urls` are appended to it."""

    provider: str
    key: str
    path: str = ""
    origins: dict[str, str] = field(default_factory=dict)
    default: str = ""
    urls: tuple[str, ...] = ("",)

    def matches(self, path: str) -> bool:
        return _leaf(path).casefold() == self.key.casefold() and (
            not self.path or self.path.casefold() in path.casefold()
        )

    def origin_for(self, value: str) -> str:
        return self.origins.get(value.strip().casefold(), self.default)


@dataclass(frozen=True)
class Rules:
    site_url_keys: frozenset[str] = frozenset()
    hostmap_keys: frozenset[str] = frozenset()
    providers: tuple[tuple[str, str], ...] = ()
    env_endpoints: tuple[EnvRule, ...] = ()
    configenv_path: str = ""


def _shape_error(detail: str) -> ExtractkitError:
    return ExtractkitError(
        f"profile live_config {detail}",
        "see docs/profiles.md 'live_config' for the table shape",
    )


def _str_list(table: dict, name: str) -> list[str]:
    value = table.get(name, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise _shape_error(f"{name} must be a list of strings")
    return value


def _env_rule(raw: object) -> EnvRule:
    if not isinstance(raw, dict) or not raw.get("provider") or not raw.get("key"):
        raise _shape_error("env_endpoints entries need provider and key")
    origins = raw.get("origins") or {}
    urls = raw.get("urls") or [""]
    if not isinstance(origins, dict) or not isinstance(urls, list):
        raise _shape_error("env_endpoints origins must be a mapping and urls a list")
    return EnvRule(
        provider=str(raw["provider"]),
        key=str(raw["key"]),
        path=str(raw.get("path") or ""),
        origins={str(k).casefold(): str(v) for k, v in origins.items()},
        default=str(raw.get("default") or ""),
        urls=tuple(str(u) for u in urls),
    )


def rules_from_profile(profile: object) -> Rules:
    """Validate and normalise `profile['live_config']`. Missing or empty means no rules."""
    table = profile.get("live_config") if isinstance(profile, dict) else None
    if not table:
        return Rules()
    if not isinstance(table, dict):
        raise _shape_error("must be a mapping")
    providers = table.get("providers") or {}
    env = table.get("env_endpoints") or []
    if not isinstance(providers, dict) or not isinstance(env, list):
        raise _shape_error("providers must be a mapping and env_endpoints a list")
    return Rules(
        site_url_keys=frozenset(k.casefold() for k in _str_list(table, "site_url_keys")),
        hostmap_keys=frozenset(k.casefold() for k in _str_list(table, "hostmap_keys")),
        providers=tuple((str(k).casefold(), str(v)) for k, v in providers.items()),
        env_endpoints=tuple(_env_rule(item) for item in env),
        configenv_path=str(table.get("configenv_path") or ""),
    )


CONFIGENV_ROW = re.compile(
    r'id="key-([^"]+)">([^<]*)</td>\s*<td id="value-\1">([^<]*)</td>',
    re.IGNORECASE,
)


def is_secret(name: str) -> bool:
    leaf = name.rsplit(".", 1)[-1].casefold().replace("_", "").replace("-", "")
    if leaf.endswith(("key", "token", "password", "user")):
        return True
    return any(marker.replace("-", "") in leaf for marker in SECRET_MARKERS)


def flatten_properties(node: object, prefix: str = "") -> list[tuple[str, object]]:
    rows: list[tuple[str, object]] = []
    if isinstance(node, dict):
        name = node.get("name")
        values = node.get("values")
        if isinstance(name, str) and isinstance(values, list):
            path = f"{prefix}.{name}" if prefix else name
            for val in values:
                if not isinstance(val, dict):
                    continue
                if "v" in val:
                    rows.append((path, val.get("v")))
                nested = val.get("set")
                if nested is not None:
                    rows.extend(flatten_properties(nested, path))
            return rows
        for child in node.values():
            rows.extend(flatten_properties(child, prefix))
        return rows
    if isinstance(node, list):
        for item in node:
            rows.extend(flatten_properties(item, prefix))
    return rows


def public_fields(rows: list[tuple[str, object]]) -> tuple[dict[str, object], list[str]]:
    fields: dict[str, object] = {}
    redacted: list[str] = []
    for path, value in rows:
        if is_secret(path):
            if path not in redacted:
                redacted.append(path)
            continue
        fields[path] = value
    return fields, redacted


def parse_configenv_html(html: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in CONFIGENV_ROW.finditer(html):
        key = unescape(match.group(2)).strip()
        value = unescape(match.group(3))
        if not key or key in seen:
            continue
        seen.add(key)
        if is_secret(key):
            items.append({"key": key, "redacted": "true"})
        else:
            items.append({"key": key, "value": value})
    return items


def _http_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.startswith(("http://", "https://")):
        return text
    return None


def _leaf(path: str) -> str:
    return path.rsplit(".", 1)[-1]


def _provider(path: str, rules: Rules) -> str:
    leaf = _leaf(path).casefold()
    for needle, name in rules.providers:
        if needle in leaf:
            return name
    return _leaf(path)


def _endpoint(
    provider: str,
    url: str,
    source: str,
    direction: str = "outbound",
) -> dict[str, str]:
    return {
        "provider": provider,
        "direction": direction,
        "url": url,
        "source": source,
    }


def endpoints_from_site_fields(
    fields: dict[str, object],
    *,
    content_key: str,
    rules: Rules,
) -> list[dict[str, str]]:
    endpoints: list[dict[str, str]] = []
    for path, value in fields.items():
        url = _http_url(value)
        if _leaf(path).casefold() in rules.site_url_keys and url:
            endpoints.append(_endpoint(
                _provider(path, rules), url, f"siteConfig:{content_key}:{path}",
            ))
    for rule in rules.env_endpoints:
        for path, value in fields.items():
            if not rule.matches(path) or not isinstance(value, str) or not value.strip():
                continue
            # Source names the full config path when the rule scopes by path, else the key.
            label = path if rule.path else rule.key
            origin = rule.origin_for(value)
            for suffix in rule.urls:
                endpoints.append(_endpoint(
                    rule.provider,
                    origin + suffix,
                    f"siteConfig:{content_key}:{label}={value.strip()}",
                ))
            break
    return endpoints


def endpoints_from_config_env(items: list[dict[str, str]], rules: Rules) -> list[dict[str, str]]:
    endpoints: list[dict[str, str]] = []
    for item in items:
        key = item.get("key") or ""
        if item.get("redacted") == "true":
            continue
        value = item.get("value") or ""
        folded = key.casefold()
        if folded in rules.hostmap_keys or any(folded.endswith(k) for k in rules.hostmap_keys):
            for part in value.replace(" ", "").split(","):
                if "=" not in part:
                    continue
                _path, host = part.split("=", 1)
                host = host.strip()
                if not host:
                    continue
                url = host if host.startswith(("http://", "https://")) else f"https://{host}"
                endpoints.append(_endpoint(
                    "hostMap", url, f"configEnv:{key}", "inbound",
                ))
            continue
        url = _http_url(value)
        if url and folded.endswith(CONFIG_URL_SUFFIXES):
            endpoints.append(_endpoint(_provider(key, rules), url, f"configEnv:{key}"))
    return endpoints


def dedupe_endpoints(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, str]] = []
    for row in rows:
        stamp = (row.get("provider") or "", row.get("url") or "", row.get("source") or "")
        if stamp in seen or not stamp[1]:
            continue
        seen.add(stamp)
        out.append(row)
    return out


_HOSTMAP_PAIR = re.compile(r"^[^=,\s]+=(?:https?://)?[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?::\d+)?(?:/\S*)?$")


def _is_hostmap(value: object) -> bool:
    """A mapping, a JSON object string, or a comma list of `<key>=<host-or-url>` pairs."""
    if isinstance(value, dict):
        return bool(value)
    if not isinstance(value, str):
        return False
    text = value.strip()
    if text.startswith("{"):
        try:
            return isinstance(json.loads(text), dict)
        except ValueError:
            return False
    parts = text.replace(" ", "").split(",")
    return bool(parts) and all(_HOSTMAP_PAIR.match(part) for part in parts)


def _candidate_kind(value: object) -> str | None:
    if _is_hostmap(value):
        return "hostmap"
    return "url" if _http_url(value) else None


def _site_covered(path: str, kind: str, rules: Rules) -> bool:
    if kind != "url":
        return False
    return _leaf(path).casefold() in rules.site_url_keys or any(
        rule.matches(path) for rule in rules.env_endpoints
    )


def _env_covered(key: str, kind: str, rules: Rules) -> bool:
    folded = key.casefold()
    if kind == "hostmap":
        return folded in rules.hostmap_keys or any(folded.endswith(k) for k in rules.hostmap_keys)
    return folded.endswith(CONFIG_URL_SUFFIXES)


def config_candidates(
    site_rows: list[dict[str, object]],
    configenv_items: list[dict[str, str]],
    rules: Rules,
) -> list[dict[str, object]]:
    """Every public Site Config and Config Env key whose value is a URL or a host map.

    `covered` says whether the current rules already turn the key into endpoints.
    The agent task that writes `live_config` reads this list; secrets never appear.
    """
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()

    def add(origin: str, key: str, value: object, covered: Callable[[str, str], bool]) -> None:
        kind = _candidate_kind(value)
        if kind is None or is_secret(key) or (origin, key) in seen:
            return
        seen.add((origin, key))
        rows.append({"origin": origin, "key": key, "kind": kind, "covered": covered(key, kind)})

    for fields in site_rows:
        for path, value in fields.items():
            add("siteConfig", path, value, lambda k, kind: _site_covered(k, kind, rules))
    for item in configenv_items:
        if item.get("redacted") == "true":
            continue
        add("configEnv", item.get("key") or "", item.get("value"),
            lambda k, kind: _env_covered(k, kind, rules))
    return rows


def cs_content_url(host: str, project: str, content_id: str) -> str:
    return (
        f"{host}/admin/rest-v2/cs/cms/{quote(project, safe='')}"
        f"/content/content?id={quote(str(content_id), safe='')}"
    )


def default_configenv_url(host: str, rules: Rules) -> str:
    """The Config Env tool URL, or "" when the profile names no tool path."""
    return f"{host}{rules.configenv_path}" if rules.configenv_path else ""


def slim_integration_fields(fields: dict[str, object], rules: Rules) -> dict[str, object]:
    keep: dict[str, object] = {}
    for path, value in fields.items():
        leaf = _leaf(path).casefold()
        keep_it = (
            leaf in rules.site_url_keys
            or leaf.endswith(CONFIG_URL_SUFFIXES)
            or any(rule.matches(path) for rule in rules.env_endpoints)
        )
        if keep_it:
            keep[path] = value
    return keep


def site_config_record(
    content_key: str,
    content_id: str,
    payload: dict,
    rules: Rules,
) -> dict[str, Any]:
    rows = flatten_properties(payload.get("data"))
    fields, redacted = public_fields(rows)
    return {
        "key": content_key,
        "id": content_id,
        "fields": slim_integration_fields(fields, rules),
        "redacted": redacted,
    }


def patch_openapi(path, endpoints: list[dict[str, str]]) -> dict | None:
    if not path.is_file():
        return None
    spec = load_yaml(path, "integrations/openapi.yaml")
    spec["x-production-endpoints"] = endpoints
    info = spec.get("info")
    description = info.get("description") if isinstance(info, dict) else None
    if (
        isinstance(info, dict)
        and isinstance(description, str)
        and "metadata only" not in description.lower()
    ):
        info["description"] = (
            description.rstrip()
            + " Production URLs are metadata only. Do not use Try it out "
            "against production.\n"
        )
    return spec
