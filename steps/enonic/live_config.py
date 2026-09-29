"""Live Site Config and Config Env harvest.

Site Config is Content Studio REST (Guillotine dataAsJson omits it on XP7 CS 5.2).
Config Env is the no.seeds.configenv admin HTML table (no list JSON API).
Secrets are dropped. URLs are metadata only — never fetched.
"""

from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import quote

from extractkit_cli.common import load_yaml

SECRET_MARKERS = (
    "password",
    "token",
    "secret",
    "apikey",
)
SITE_URL_KEYS = frozenset({"tourplanurl"})
CONFIG_URL_SUFFIXES = ("endpoint",)
HOSTMAP_KEYS = frozenset({"env-hostmap", "hostmap"})

# Derived from as netaxept.js / flywire.js host selection. Not production calls.
NETAXEPT_PATHS = (
    ("Register", "/Netaxept/Register.aspx"),
    ("Process", "/Netaxept/Process.aspx"),
    ("Query", "/Netaxept/Query.aspx"),
    ("terminal", "/terminal/default.aspx"),
)
FLYWIRE_API = {
    "demo": "https://api-platform-sandbox.flywire.com",
    "prod": "https://api-platform.flywire.com",
}

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


def _provider(path: str) -> str:
    leaf = _leaf(path).casefold()
    if "tourplan" in leaf:
        return "Tourplan"
    if "netaxept" in leaf:
        return "Netaxept"
    if "flywire" in leaf:
        return "Flywire"
    if "travelspecialist" in leaf:
        return "TravelSpecialist"
    if "hostmap" in leaf:
        return "hostMap"
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
) -> list[dict[str, str]]:
    endpoints: list[dict[str, str]] = []
    for path, value in fields.items():
        leaf = _leaf(path).casefold()
        url = _http_url(value)
        if leaf in SITE_URL_KEYS and url:
            endpoints.append(_endpoint(
                _provider(path), url, f"siteConfig:{content_key}:{path}",
            ))
    netaxept = ""
    for path, value in fields.items():
        if _leaf(path).casefold() == "netaxeptenv" and isinstance(value, str):
            netaxept = value
            break
    if isinstance(netaxept, str) and netaxept.strip():
        prefix = "test." if netaxept.strip().casefold() == "test" else ""
        origin = f"https://{prefix}epayment.nets.eu"
        for _name, suffix in NETAXEPT_PATHS:
            endpoints.append(_endpoint(
                "Netaxept",
                origin + suffix,
                f"siteConfig:{content_key}:netaxeptEnv={netaxept.strip()}",
            ))
    flywire = None
    source_path = "siteConfig.config.flywirePortal.env"
    for path, value in fields.items():
        if _leaf(path).casefold() == "env" and "flywireportal" in path.casefold():
            flywire = value
            source_path = path
            break
    if isinstance(flywire, str) and flywire.strip():
        env = flywire.strip().casefold()
        url = FLYWIRE_API.get("demo" if env == "demo" else "prod")
        endpoints.append(_endpoint(
            "Flywire",
            url,
            f"siteConfig:{content_key}:{source_path}={flywire.strip()}",
        ))
    return endpoints


def endpoints_from_config_env(items: list[dict[str, str]]) -> list[dict[str, str]]:
    endpoints: list[dict[str, str]] = []
    for item in items:
        key = item.get("key") or ""
        if item.get("redacted") == "true":
            continue
        value = item.get("value") or ""
        folded = key.casefold()
        if folded in HOSTMAP_KEYS or folded.endswith("hostmap"):
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
            endpoints.append(_endpoint(_provider(key), url, f"configEnv:{key}"))
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


def cs_content_url(host: str, project: str, content_id: str) -> str:
    return (
        f"{host}/admin/rest-v2/cs/cms/{quote(project, safe='')}"
        f"/content/content?id={quote(str(content_id), safe='')}"
    )


def default_configenv_url(host: str) -> str:
    return f"{host}/admin/tool/no.seeds.configenv/module-config"


def slim_integration_fields(fields: dict[str, object]) -> dict[str, object]:
    keep: dict[str, object] = {}
    for path, value in fields.items():
        leaf = _leaf(path).casefold()
        blob = path.casefold()
        keep_it = (
            leaf in SITE_URL_KEYS
            or leaf == "netaxeptenv"
            or leaf.endswith("endpoint")
            or ("flywireportal" in blob and leaf == "env")
        )
        if keep_it:
            keep[path] = value
    return keep


def site_config_record(
    content_key: str,
    content_id: str,
    payload: dict,
) -> dict[str, Any]:
    rows = flatten_properties(payload.get("data"))
    fields, redacted = public_fields(rows)
    return {
        "key": content_key,
        "id": content_id,
        "fields": slim_integration_fields(fields),
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
