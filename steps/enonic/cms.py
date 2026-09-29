"""enonic.cms — live XP7 survey via Playwright storage-state + Guillotine.

Auth is a Playwright storage-state file (cookies). Transport is HTTP POST to
the Guillotine GraphQL URL passed as a run parameter. The as app-own service
(`POST /_/service/no.seeds.as/graphql`) is not assumed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

from extractkit_cli import cms_target, schema
from extractkit_cli.common import load_json
from extractkit_cli.errors import ExtractkitError
from steps.enonic import live_config

PAGE_QUERY = """\
query {{
  guillotine {{
    get(key: "{key}") {{
      _id
      _path
      type
      displayName
      pageAsJson
      components {{ path type }}
    }}
  }}
}}
"""


@dataclass
class CmsConfig:
    host: str
    branch: str
    project: str
    guillotine: str
    storage_state: Path | None
    keys: list[str]
    round2: list[str]
    env: str
    allow_production: bool
    context_by_key: dict[str, str]
    configenv: str


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _profile_cms(ctx: Any) -> dict:
    raw = ctx.profile.get("cms") if isinstance(ctx.profile, dict) else None
    return raw if isinstance(raw, dict) else {}


def _cli(ctx: Any) -> dict:
    raw = getattr(ctx, "cms", None)
    return raw if isinstance(raw, dict) else {}


def resolve_cms(ctx: Any) -> CmsConfig:
    cli = _cli(ctx)
    profile = _profile_cms(ctx)
    allow = bool(cli.get("allow_production"))
    branch = cms_target.assert_branch(
        cli.get("branch") or profile.get("branch"),
    )
    host = cms_target.normalize_url(
        cli.get("xp_host") or profile.get("host") or "http://localhost:8080",
    )
    project = str(cli.get("project") or profile.get("project") or "").strip()
    guillotine = cms_target.normalize_url(
        cli.get("guillotine") or profile.get("guillotine") or "",
    )
    if not guillotine:
        if not project:
            raise ExtractkitError(
                "enonic.cms has no Guillotine URL",
                "pass --guillotine (XP7 preview POST /admin/site/preview/"
                "<project>/<branch>, or the as app-own service when that is "
                "the intended endpoint) or set cms.project so a preview URL "
                "can be built",
            )
        guillotine = f"{host}/admin/site/preview/{project}/{branch}"
    host_env = cms_target.assert_allowed(
        host, allow_production=allow, what="--xp-host",
    )
    gql_env = cms_target.assert_allowed(
        guillotine, allow_production=allow, what="--guillotine",
    )
    configenv = cms_target.normalize_url(
        cli.get("configenv") or profile.get("configenv") or "",
    )
    if not configenv:
        configenv = live_config.default_configenv_url(host)
    cms_target.assert_allowed(
        configenv, allow_production=allow, what="--configenv",
    )
    env = gql_env if gql_env == "production" else host_env
    keys = _unique(list(cli.get("cms_keys") or []))
    if not keys:
        profile_keys = profile.get("keys") or []
        if isinstance(profile_keys, list):
            keys = _unique([str(k) for k in profile_keys])
        site_key = profile.get("site_key")
        if not keys and site_key:
            keys = _unique([str(site_key)])
    if not keys:
        raise ExtractkitError(
            "enonic.cms has no content keys to survey",
            "pass --cms-key /en (repeatable) or set cms.keys in the profile; "
            "do not walk the whole tree",
        )
    profile_round2 = ctx.profile.get("round2") if isinstance(ctx.profile, dict) else []
    if not isinstance(profile_round2, list):
        profile_round2 = []
    round2 = _unique([
        *[str(x) for x in (cli.get("round2") or [])],
        *[str(x) for x in profile_round2],
    ])
    context_by_key: dict[str, str] = {}
    raw_map = profile.get("context_by_key") or {}
    if isinstance(raw_map, dict):
        context_by_key = {str(k): str(v) for k, v in raw_map.items()}
    state_raw = cli.get("storage_state") or profile.get("storage_state")
    state_path = Path(state_raw).expanduser() if state_raw else None
    return CmsConfig(
        host=host,
        branch=branch,
        project=project,
        guillotine=guillotine,
        storage_state=state_path,
        keys=keys,
        round2=round2,
        env=env,
        allow_production=allow,
        context_by_key=context_by_key,
        configenv=configenv,
    )


def cookies_from_storage_state(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ExtractkitError(
            f"Playwright storage-state not found at {path}",
            "pass --storage-state at a harness file (see find-auth-storage.py); "
            "user.json can be stale",
        ) from None
    except ValueError as exc:
        raise ExtractkitError(
            f"storage-state {path} is not JSON: {exc}",
            "export a Playwright storage-state JSON with a cookies array",
        ) from None
    cookies = payload.get("cookies") if isinstance(payload, dict) else None
    if not isinstance(cookies, list):
        return ""
    parts: list[str] = []
    for item in cookies:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        if name and value is not None:
            parts.append(f"{name}={value}")
    return "; ".join(parts)


def _escape_key(key: str) -> str:
    return key.replace("\\", "\\\\").replace('"', '\\"')


def post_graphql(
    url: str,
    query: str,
    cookie_header: str,
    *,
    timeout: float = 30,
) -> dict:
    body = json.dumps({"query": query}).encode("utf-8")
    req = urlrequest.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if cookie_header:
        req.add_header("Cookie", cookie_header)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urlerror.HTTPError as exc:
        if exc.code in (401, 403):
            raise ExtractkitError(
                f"Guillotine POST {url} returned HTTP {exc.code}",
                "mint a fresh Playwright storage-state; user.json can be stale",
            ) from None
        raise ExtractkitError(
            f"Guillotine POST {url} returned HTTP {exc.code}",
            "pass --guillotine at the preview GraphQL URL "
            "(POST /admin/site/preview/<project>/<branch>); do not assume "
            "the as app-own /_/service/no.seeds.as/graphql endpoint",
        ) from None
    except urlerror.URLError as exc:
        raise ExtractkitError(
            f"Guillotine POST {url} failed: {exc.reason}",
            "start a local or review XP, or point --xp-host at it",
        ) from None
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise ExtractkitError(
            f"Guillotine POST {url} returned non-JSON: {exc}",
            "confirm --guillotine is the GraphQL endpoint, not the widget HTML",
        ) from None
    if not isinstance(payload, dict):
        raise ExtractkitError(
            f"Guillotine POST {url} returned a non-object JSON body",
            "confirm --guillotine is the GraphQL endpoint",
        )
    errors = payload.get("errors")
    if errors and not payload.get("data"):
        raise ExtractkitError(
            f"Guillotine GraphQL errors at {url}: {errors!r}",
            "fix the query or the --guillotine URL",
        )
    return payload


def http_get(
    url: str,
    cookie_header: str,
    *,
    timeout: float = 30,
    accept: str = "*/*",
) -> tuple[int, bytes]:
    req = urlrequest.Request(url, method="GET")
    req.add_header("Accept", accept)
    if cookie_header:
        req.add_header("Cookie", cookie_header)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urlerror.HTTPError as exc:
        if exc.code in (401, 403):
            raise ExtractkitError(
                f"GET {url} returned HTTP {exc.code}",
                "mint a fresh Playwright storage-state; user.json can be stale",
            ) from None
        return exc.code, exc.read()
    except urlerror.URLError as exc:
        raise ExtractkitError(
            f"GET {url} failed: {exc.reason}",
            "start a local or review XP, or point --xp-host at it",
        ) from None


def as_mapping(value: object) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def template_order(page: dict) -> list[str]:
    order: list[str] = []

    def walk(node: object) -> None:
        if not isinstance(node, dict):
            return
        desc = node.get("descriptor")
        if isinstance(desc, str) and desc:
            order.append(desc)
        regions = node.get("regions")
        if not isinstance(regions, dict):
            return
        for region in regions.values():
            if not isinstance(region, dict):
                continue
            for comp in region.get("components") or []:
                walk(comp)

    walk(page)
    return order


def descriptor_index(resources: list[dict]) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for resource in resources:
        name = resource.get("name")
        app = resource.get("app")
        if not isinstance(name, str) or not name:
            continue
        index[name] = resource
        if isinstance(app, str) and app:
            index[f"{app}:{name}"] = resource
    return index


def context_for(
    key: str,
    page: dict,
    index: dict[str, dict],
    context_by_key: dict[str, str],
) -> str:
    mapped = context_by_key.get(key)
    if mapped:
        return mapped
    desc = page.get("descriptor")
    if isinstance(desc, str) and desc in index:
        return str(index[desc].get("kind") or "uncategorized")
    local = desc.split(":")[-1] if isinstance(desc, str) else ""
    if local and local in index:
        return str(index[local].get("kind") or "uncategorized")
    typ = page.get("type")
    if isinstance(typ, str) and typ:
        return typ
    return "uncategorized"


def _static_resources(ctx: Any) -> list[dict]:
    path: Path = ctx.rel("inventory/static.json")
    if path.is_file():
        payload = load_json(path, "inventory/static.json")
        return list(payload.get("resources") or [])
    from steps.enonic.descriptors import collect_resources

    return collect_resources(ctx.source)


def _page_record(
    key: str,
    round_no: int,
    payload: dict,
    index: dict[str, dict],
    context_by_key: dict[str, str],
) -> dict:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    guillotine = data.get("guillotine") if isinstance(data, dict) else None
    got = None
    if isinstance(guillotine, dict):
        got = guillotine.get("get")
    if not isinstance(got, dict):
        return {
            "key": key,
            "round": round_no,
            "context": context_by_key.get(key) or "uncategorized",
            "error": "guillotine.get returned null",
        }
    page = as_mapping(got.get("pageAsJson"))
    components = got.get("components") if isinstance(got.get("components"), list) else []
    context = context_for(key, page, index, context_by_key)
    record: dict[str, Any] = {
        "key": key,
        "round": round_no,
        "context": context,
        "id": got.get("_id") or "",
        "path": got.get("_path") or "",
        "type": got.get("type") or "",
        "displayName": got.get("displayName") or "",
        "templateOrder": template_order(page),
        "components": components,
        "pageAsJson": page,
    }
    return record


def _require_storage_state(cfg: CmsConfig) -> Path:
    if cfg.storage_state is None:
        raise ExtractkitError(
            "enonic.cms --apply needs a Playwright storage-state",
            "pass --storage-state at a harness JSON (find-auth-storage.py / "
            "playwright-cli codegen --save-storage); do not put secrets in the kit",
        )
    path = cfg.storage_state.expanduser().resolve()
    if not path.is_file():
        raise ExtractkitError(
            f"Playwright storage-state not found at {path}",
            "pass --storage-state at an existing JSON file; user.json can be stale",
        )
    return path


class EnonicCmsStep:
    id = "enonic.cms"
    requires = ("inventory/static.json",)
    produces = ("inventory/runtime.json",)
    required = True

    def plan(self, ctx: object) -> list[str]:
        cfg = resolve_cms(ctx)
        actions = [
            (
                f"Playwright storage-state -> POST {cfg.guillotine} "
                f"branch={cfg.branch} keys={cfg.keys}"
            ),
        ]
        if cfg.round2:
            actions.append(f"round2 contexts: {cfg.round2}")
        actions.append(f"GET Content Studio siteConfig + Config Env {cfg.configenv}")
        return actions

    def run(self, ctx: object) -> None:
        cfg = resolve_cms(ctx)
        index = descriptor_index(_static_resources(ctx))
        pages: list[dict] = []
        cookie = ""
        if ctx.apply:  # type: ignore[attr-defined]
            state = _require_storage_state(cfg)
            cookie = cookies_from_storage_state(state)
            if not cookie:
                raise ExtractkitError(
                    f"storage-state {state} has no cookies",
                    "export a Playwright storage-state after logging into XP",
                )
            for key in cfg.keys:
                query = PAGE_QUERY.format(key=_escape_key(key))
                payload = post_graphql(cfg.guillotine, query, cookie)
                pages.append(_page_record(key, 1, payload, index, cfg.context_by_key))
            round2_keys = [
                row["key"] for row in pages
                if row.get("round") == 1 and row.get("context") in cfg.round2
            ]
            for key in _unique(round2_keys):
                query = PAGE_QUERY.format(key=_escape_key(key))
                payload = post_graphql(cfg.guillotine, query, cookie)
                pages.append(_page_record(key, 2, payload, index, cfg.context_by_key))
            site_configs, config_env, endpoints = _harvest_live_config(
                cfg, pages, cookie,
            )
        else:
            for key in cfg.keys:
                pages.append({
                    "key": key,
                    "round": 1,
                    "context": cfg.context_by_key.get(key) or "uncategorized",
                })
            site_configs, config_env, endpoints = [], [], []
        payload = {
            "schema": "99x.extract.runtime-inventory/v1",
            "env": cfg.env,
            "host": cfg.host,
            "branch": cfg.branch,
            "project": cfg.project,
            "guillotine": cfg.guillotine,
            "configenv": cfg.configenv,
            "pages": pages,
            "siteConfig": site_configs,
            "configEnv": config_env,
            "endpoints": endpoints,
        }
        schema.validate(payload, "runtime-inventory", what="inventory/runtime.json")
        ctx.write_json("inventory/runtime.json", payload)  # type: ignore[attr-defined]
        _patch_openapi(ctx, endpoints)

    def check(self, _ctx: object) -> list[str]:
        return []


def _harvest_live_config(
    cfg: CmsConfig,
    pages: list[dict],
    cookie: str,
) -> tuple[list[dict], list[dict], list[dict]]:
    site_configs: list[dict] = []
    endpoints: list[dict] = []
    seen_ids: set[str] = set()
    project = cfg.project or "en"
    for page in pages:
        content_id = str(page.get("id") or "")
        key = str(page.get("key") or "")
        if not content_id or content_id in seen_ids:
            continue
        seen_ids.add(content_id)
        url = live_config.cs_content_url(cfg.host, project, content_id)
        status, raw = http_get(url, cookie, accept="application/json")
        if status == 404:
            continue
        if status != 200:
            raise ExtractkitError(
                f"Content Studio GET {url} returned HTTP {status}",
                "confirm XP7 CS REST /admin/rest-v2/cs/cms/<project>/content/"
                "content?id=<uuid> with a valid storage-state",
            )
        try:
            body = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise ExtractkitError(
                f"Content Studio GET {url} returned non-JSON: {exc}",
                "confirm the CS REST URL",
            ) from None
        if not isinstance(body, dict):
            continue
        record = live_config.site_config_record(key, content_id, body)
        site_configs.append(record)
        endpoints.extend(
            live_config.endpoints_from_site_fields(
                record.get("fields") or {}, content_key=key,
            )
        )
    config_env: list[dict] = []
    status, raw = http_get(cfg.configenv, cookie, accept="text/html")
    if status == 200:
        config_env = live_config.parse_configenv_html(raw.decode("utf-8", "replace"))
        endpoints.extend(live_config.endpoints_from_config_env(config_env))
    elif status not in (404, 405, 501):
        raise ExtractkitError(
            f"Config Env GET {cfg.configenv} returned HTTP {status}",
            "pass --configenv at the XP7 tool "
            "/admin/tool/no.seeds.configenv/module-config, or skip if that "
            "app is not installed",
        )
    return site_configs, config_env, live_config.dedupe_endpoints(endpoints)


def _patch_openapi(ctx: object, endpoints: list[dict]) -> None:
    path = ctx.rel("integrations/openapi.yaml")  # type: ignore[attr-defined]
    spec = live_config.patch_openapi(path, endpoints)
    if spec is None:
        return
    ctx.write_yaml("integrations/openapi.yaml", spec)  # type: ignore[attr-defined]
