"""enonic.cms — live XP7 survey via Playwright storage-state + Guillotine.

Auth is a Playwright storage-state file (cookies). Transport is HTTP POST to
the Guillotine GraphQL URL passed as a run parameter. An app-own GraphQL
service is not assumed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlsplit

from extractkit_cli import cms_target, schema, scope
from extractkit_cli.common import load_json
from extractkit_cli.errors import ExtractkitError
from steps.enonic import live_config, page_templates
from steps.enonic.integrations import write_swagger_spec

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

CHILDREN_QUERY = """\
query {{
  guillotine {{
    getChildren(key: "{key}", first: 100) {{
      _id
      _path
      _name
      type
      displayName
    }}
  }}
}}
"""

TEMPLATE_QUERY = """\
query {{
  guillotine {{
    get(key: "{key}") {{
      _id
      _path
      _name
      type
      displayName
      dataAsJson
      pageAsJson
      components {{ path type descriptor }}
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
    sample_per_type: int
    rules: live_config.Rules = field(default_factory=live_config.Rules)


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
                "<project>/<branch>, or an app-own GraphQL service when that is "
                "the intended endpoint) or set cms.project so a preview URL "
                "can be built",
                fix_args={"--guillotine": "<preview-graphql-url>"},
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
    rules = live_config.rules_from_profile(ctx.profile)
    if not configenv:
        configenv = live_config.default_configenv_url(host, rules)
    if configenv:
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
            fix_args={"--cms-key": "/en"},
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
        sample_per_type=page_templates.sample_per_type(profile, cli),
        rules=rules,
    )


def cookies_from_storage_state(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ExtractkitError(
            f"Playwright storage-state not found at {path}",
            "pass --storage-state at a harness file (see find-auth-storage.py); "
            "user.json can be stale",
            fix_args={"--storage-state": "<playwright-state.json>"},
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


class _SameHostRedirects(urlrequest.HTTPRedirectHandler):
    """Follow a redirect only on the same host, and never from https to http.

    The admin cookie is sent by hand, so urllib would copy it to whatever host a
    redirect names, and the production guard only ever saw the first URL.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urlsplit(req.full_url), urlsplit(newurl)
        if (old.hostname or "").lower() != (new.hostname or "").lower() or (old.scheme == "https" and new.scheme != "https"):
            raise ExtractkitError(
                f"{old.hostname} redirected to {new.scheme}://{new.hostname}; the request was not followed",
                "point --xp-host, --guillotine or --site-url at the final host: the session cookie "
                "and the production check apply to the host you name",
                code="redirect_refused",
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener() -> urlrequest.OpenerDirector:
    """http and https only, so a `file:` URL cannot be opened, with the same-host redirect rule."""
    opener = urlrequest.OpenerDirector()
    for handler in (
        urlrequest.HTTPHandler(), urlrequest.HTTPSHandler(), urlrequest.HTTPDefaultErrorHandler(),
        _SameHostRedirects(), urlrequest.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    return opener


def _open(req: urlrequest.Request, timeout: float):
    if urlsplit(req.full_url).scheme not in ("http", "https"):
        raise ExtractkitError(
            f"{req.full_url.split(':', 1)[0]}: URLs are not supported",
            "use an http or https URL for the XP host", code="redirect_refused",
        )
    return _opener().open(req, timeout=timeout)


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
        with _open(req, timeout) as resp:
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
            "an app-own GraphQL service endpoint",
            fix_args={"--guillotine": "<preview-graphql-url>"},
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
        with _open(req, timeout) as resp:
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

    return collect_resources(ctx.source, scope.of(ctx))


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
    page = page_templates.as_mapping(got.get("pageAsJson"))
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


def _gql_field(payload: dict, field: str) -> object:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    gql = data.get("guillotine") if isinstance(data, dict) else None
    if not isinstance(gql, dict):
        return None
    return gql.get(field)


def _graphql_optional(url: str, query: str, cookie: str) -> dict:
    try:
        return post_graphql(url, query, cookie)
    except ExtractkitError as exc:
        if "GraphQL errors" in str(exc):
            return {"data": {"guillotine": {}}, "errors": [str(exc)]}
        raise


def _type_query(type_id: str, limit: int) -> str:
    return (
        'query { guillotine { queryConnection(query: "", first: '
        + str(int(limit))
        + ", contentTypes: ["
        + json.dumps(type_id)
        + "]) { totalCount edges { node { "
        "_id _path displayName type pageAsJson } } } } }"
    )


USAGE_KINDS = ("page", "layout", "part")


def _usage_query(kind: str, key: str) -> str:
    noql = f"components.{kind}.descriptor = '{key}'"
    return (
        'query { guillotine { queryConnection(query: "'
        + _escape_key(noql)
        + '", first: 0) { totalCount } } }'
    )


def probe_usage(url: str, cookie: str, resources: list[dict]) -> dict:
    """Exhaustive per-descriptor usage count. A query error degrades, never refuses.

    Returns `{"usage": {"<app>:<kind>:<name>": int | None}, "usageProbe": "ok" | "unsupported"}`.
    Page, layout and part only: macros live in HtmlArea text with no indexed field.
    """
    keys = sorted({
        (r["kind"], f"{r.get('app')}:{r.get('name')}")
        for r in resources
        if isinstance(r, dict) and r.get("kind") in USAGE_KINDS and r.get("app") and r.get("name")
    })
    usage: dict[str, int | None] = {}
    for kind, key in keys:
        try:
            payload = post_graphql(url, _usage_query(kind, key), cookie)
        except ExtractkitError:
            return _usage_unsupported(keys)
        conn = _gql_field(payload, "queryConnection")
        count = conn.get("totalCount") if isinstance(conn, dict) else None
        if payload.get("errors") or not isinstance(count, int) or isinstance(count, bool):
            return _usage_unsupported(keys)
        usage[_usage_key(kind, key)] = count
    return {"usage": usage, "usageProbe": "ok"}


def _usage_unsupported(keys: list[tuple[str, str]]) -> dict:
    return {"usage": {_usage_key(kind, key): None for kind, key in keys}, "usageProbe": "unsupported"}


def _usage_key(kind: str, key: str) -> str:
    """Surface-id form: a page, a layout and a part may share one `<app>:<name>`."""
    app, _, name = key.rpartition(":")
    return f"{app}:{kind}:{name}"


def _count_probe(url: str, cookie: str, noql: str, aggregation: str = "") -> dict | None:
    """One exhaustive `queryConnection(first: 0)`. None when the query is not understood."""
    selection = "totalCount" + (" aggregationsAsJson" if aggregation else "")
    query = (
        'query { guillotine { queryConnection(query: "' + _escape_key(noql) + '", first: 0'
        + aggregation + ") { " + selection + " } } }"
    )
    try:
        payload = post_graphql(url, query, cookie)
    except ExtractkitError:
        return None
    conn = _gql_field(payload, "queryConnection")
    if payload.get("errors") or not isinstance(conn, dict):
        return None
    total = conn.get("totalCount")
    if not isinstance(total, int) or isinstance(total, bool):
        return None
    buckets = _buckets(conn.get("aggregationsAsJson")) if aggregation else []
    return {"total": total, "buckets": buckets}


def _buckets(raw: object) -> list[dict]:
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []
    rows: list[dict] = []
    for agg in data.values():
        if not isinstance(agg, dict):
            continue
        for bucket in agg.get("buckets") or []:
            if isinstance(bucket, dict) and bucket.get("key") is not None:
                rows.append({"key": str(bucket["key"]), "count": int(bucket.get("docCount") or 0)})
    return sorted(rows, key=lambda r: (-r["count"], r["key"]))


def _terms(name: str, field: str) -> str:
    return f', aggregations: [{{name: "{name}", terms: {{field: "{field}", size: 200}}}}]'


def _project_list(host: str, cookie: str) -> tuple[list[dict] | None, str]:
    url = f"{host}/admin/rest-v2/cs/project/list"
    try:
        status, raw = http_get(url, cookie, accept="application/json")
    except ExtractkitError as exc:
        return None, str(exc)
    if status != 200:
        return None, f"HTTP {status}"
    try:
        body = json.loads(raw.decode("utf-8"))
    except ValueError:
        return None, "non-JSON answer"
    items = body.get("projects") if isinstance(body, dict) else body
    if not isinstance(items, list):
        return None, "unexpected answer shape"
    rows: list[dict] = []
    for item in items:
        if isinstance(item, dict) and item.get("name"):
            row = {"name": str(item["name"])}
            if item.get("parent"):
                row["parent"] = str(item["parent"])
            rows.append(row)
    return sorted(rows, key=lambda r: r["name"]), ""


def survey_volume(cfg: CmsConfig, cookie: str, type_ids: list[str]) -> dict:
    """Content counts for sizing a content migration. A failed probe is `None`, never 0."""
    url = cfg.guillotine
    types = []
    for type_id in sorted(type_ids):
        probe = _count_probe(url, cookie, f"type = '{type_id}'")
        types.append({"type": type_id, "total": probe["total"] if probe else None})
    langs = _count_probe(url, cookie, "", _terms("languages", "language"))
    media = _count_probe(url, cookie, "type LIKE 'media:*'", _terms("types", "type"))
    projects, reason = _project_list(cfg.host, cookie)
    doc: dict = {
        "schema": "extractkit.content-volume/v1",
        "host": cfg.host,
        "branch": cfg.branch,
        "types": types,
        "languages": (
            [{"language": b["key"], "count": b["count"]} for b in langs["buckets"]]
            if langs else None
        ),
        "media": {
            "total": media["total"] if media else None,
            "byType": [{"type": b["key"], "count": b["count"]} for b in media["buckets"]] if media else [],
        },
        "projects": projects,
    }
    if projects is None:
        doc["projectsReason"] = reason
    return doc


def render_volume_md(doc: dict) -> str:
    def cell(value: object) -> str:
        return "unknown" if value is None else str(value)

    lines = ["# Content volume", "", f"Host `{doc['host']}`, branch `{doc['branch']}`. `unknown` = the query failed.", ""]
    lines += ["## Content types", "", "| type | total |", "|---|---|"]
    lines += [f"| `{row['type']}` | {cell(row['total'])} |" for row in doc["types"]]
    lines += ["", "## Languages", ""]
    if doc["languages"] is None:
        lines.append("unknown (aggregation not supported).")
    else:
        lines += ["| language | count |", "|---|---|"]
        lines += [f"| {row['language']} | {row['count']} |" for row in doc["languages"]]
    lines += ["", "## Media", "", f"Total: {cell(doc['media']['total'])}", ""]
    if doc["media"]["byType"]:
        lines += ["| type | count |", "|---|---|"]
        lines += [f"| `{row['type']}` | {row['count']} |" for row in doc["media"]["byType"]]
        lines.append("")
    lines += ["## Projects and layers", ""]
    if doc["projects"] is None:
        lines.append(f"unknown ({doc.get('projectsReason')}).")
    else:
        lines += ["| project | parent layer |", "|---|---|"]
        lines += [f"| {row['name']} | {row.get('parent', '')} |" for row in doc["projects"]]
    lines.append("")
    return "\n".join(lines)


def load_page_templates(
    url: str,
    cookie: str,
    folder_key: str,
) -> list[page_templates.PageTemplate]:
    payload = _graphql_optional(
        url, CHILDREN_QUERY.format(key=_escape_key(folder_key)), cookie,
    )
    children = _gql_field(payload, "getChildren")
    missing = children is None
    if not isinstance(children, list):
        children = []
    templates: list[page_templates.PageTemplate] = []
    index = 0
    for child in children:
        if not isinstance(child, dict):
            continue
        typ = child.get("type")
        if typ and typ != "portal:page-template":
            continue
        path = str(child.get("_path") or "")
        if not path:
            continue
        got_payload = _graphql_optional(
            url, TEMPLATE_QUERY.format(key=_escape_key(path)), cookie,
        )
        got = _gql_field(got_payload, "get")
        node = dict(child)
        if isinstance(got, dict):
            node.update(got)
        templates.append(page_templates.parse_template(node, index))
        index += 1
    if templates or not missing:
        return templates
    fallback = _graphql_optional(url, _type_query("portal:page-template", 100), cookie)
    conn = _gql_field(fallback, "queryConnection")
    if not isinstance(conn, dict):
        return []
    for i, edge in enumerate(conn.get("edges") or []):
        node = edge.get("node") if isinstance(edge, dict) else None
        if not isinstance(node, dict):
            continue
        path = str(node.get("_path") or "")
        if path:
            got_payload = _graphql_optional(
                url, TEMPLATE_QUERY.format(key=_escape_key(path)), cookie,
            )
            got = _gql_field(got_payload, "get")
            if isinstance(got, dict):
                node = {**node, **got}
        templates.append(page_templates.parse_template(node, i))
    return templates


def fetch_type_nodes(
    url: str,
    cookie: str,
    type_id: str,
    limit: int,
) -> dict:
    payload = _graphql_optional(url, _type_query(type_id, limit), cookie)
    conn = _gql_field(payload, "queryConnection")
    if not isinstance(conn, dict):
        return {"type": type_id, "totalCount": 0, "nodes": []}
    total = conn.get("totalCount")
    if not isinstance(total, int):
        total = 0
    nodes: list[dict] = []
    for edge in conn.get("edges") or []:
        node = edge.get("node") if isinstance(edge, dict) else None
        if isinstance(node, dict):
            nodes.append(node)
    return {
        "type": type_id,
        "totalCount": total,
        "nodes": page_templates.cap_nodes(nodes, limit),
    }


def _annotate_record(
    record: dict,
    templates: list[page_templates.PageTemplate],
) -> dict:
    if record.get("error"):
        return record
    page = record.get("pageAsJson") if isinstance(record.get("pageAsJson"), dict) else {}
    typ = str(record.get("type") or "")
    result = page_templates.resolve_page(typ, page, templates)
    record["pageCustomized"] = result.customized
    record["pageTemplateField"] = result.explicit
    record["resolve"] = result.source
    record["resolvedTemplate"] = result.template_path
    record["implicitWouldBe"] = result.implicit_path
    record["implicitMatches"] = list(result.implicit_paths)
    effective = result.effective if isinstance(result.effective, dict) else {}
    record["templateOrder"] = template_order(effective)
    record["pageTree"] = page_templates.compact_page(effective)
    return record


def _sample_runtime_page(
    node: dict,
    templates: list[page_templates.PageTemplate],
    index: dict[str, dict],
    context_by_key: dict[str, str],
) -> dict:
    path = str(node.get("_path") or "")
    fake = {"data": {"guillotine": {"get": node}}}
    record = _page_record(path, 1, fake, index, context_by_key)
    record["survey"] = True
    typ = str(node.get("type") or "")
    if typ:
        record["context"] = typ.split(":")[-1]
    return _annotate_record(record, templates)


def _write_enonic_survey(
    ctx: object,
    cfg: CmsConfig,
    folder_key: str,
    templates: list[page_templates.PageTemplate],
    type_rows: list[dict],
) -> None:
    raw = page_templates.build_raw_survey(
        host=cfg.host,
        branch=cfg.branch,
        sample_limit=cfg.sample_per_type,
        types=type_rows,
    )
    resolved = page_templates.build_resolved_survey(
        sample_limit=cfg.sample_per_type,
        folder_key=folder_key,
        templates=templates,
        types=type_rows,
    )
    pages_doc = page_templates.build_page_templates_doc(folder_key, templates)
    schema.validate(raw, "content-survey", what="inventory/content-survey.json")
    schema.validate(
        resolved, "content-survey-resolved",
        what="inventory/content-survey-resolved.json",
    )
    schema.validate(pages_doc, "page-templates", what="inventory/page-templates.json")
    ctx.write_json("inventory/content-survey.json", raw)  # type: ignore[attr-defined]
    ctx.write_json("inventory/content-survey-resolved.json", resolved)  # type: ignore[attr-defined]
    ctx.write_json("inventory/page-templates.json", pages_doc)  # type: ignore[attr-defined]
    ctx.write_text(  # type: ignore[attr-defined]
        "inventory/content-survey.md",
        page_templates.render_survey_md(raw),
    )
    ctx.write_text(  # type: ignore[attr-defined]
        "inventory/content-survey-resolved.md",
        page_templates.render_resolved_md(resolved),
    )


def _require_storage_state(cfg: CmsConfig) -> Path:
    if cfg.storage_state is None:
        raise ExtractkitError(
            "enonic.cms needs a Playwright storage-state",
            "pass --storage-state at a harness JSON (find-auth-storage.py / "
            "playwright-cli codegen --save-storage); do not put secrets in the kit",
            fix_args={"--storage-state": "<playwright-state.json>"},
        )
    path = cfg.storage_state.expanduser().resolve()
    if not path.is_file():
        raise ExtractkitError(
            f"Playwright storage-state not found at {path}",
            "pass --storage-state at an existing JSON file; user.json can be stale",
            fix_args={"--storage-state": "<playwright-state.json>"},
        )
    return path


class EnonicCmsStep:
    id = "enonic.cms"
    requires = ("inventory/static.json",)
    produces = (
        "inventory/runtime.json",
        "inventory/content-survey.json",
        "inventory/content-survey-resolved.json",
        "inventory/page-templates.json",
        "inventory/content-survey.md",
        "inventory/content-survey-resolved.md",
        "inventory/content-volume.json",
        "inventory/content-volume.md",
    )
    # inventory/live-config-candidates.json is written too, but is not listed:
    # phase completeness keys on runtime.json (progress.DISTINCTIVE).
    required = True

    def plan(self, ctx: object) -> list[str]:
        cfg = resolve_cms(ctx)
        folder = page_templates.templates_folder_key(cfg.keys[0])
        actions = [
            (
                f"Playwright storage-state -> POST {cfg.guillotine} "
                f"branch={cfg.branch} keys={cfg.keys}"
            ),
            (
                f"sample {cfg.sample_per_type} contents per type "
                f"(queryConnection first={cfg.sample_per_type}, no tree walk)"
            ),
            (
                f"resolve pages: customized > explicit page.template > "
                f"implicit data.supports in {folder} folder order"
            ),
        ]
        if cfg.round2:
            actions.append(f"round2 contexts: {cfg.round2}")
        actions.append(
            f"GET Content Studio siteConfig for pinned keys only + "
            f"Config Env {cfg.configenv}"
        )
        return actions

    def run(self, ctx: object) -> None:
        cfg = resolve_cms(ctx)
        resources = _static_resources(ctx)
        index = descriptor_index(resources)
        type_ids = page_templates.content_type_ids(resources)
        folder_key = page_templates.templates_folder_key(cfg.keys[0])
        pages: list[dict] = []
        type_rows: list[dict] = []
        state = _require_storage_state(cfg)
        cookie = cookies_from_storage_state(state)
        if not cookie:
            raise ExtractkitError(
                f"storage-state {state} has no cookies",
                "export a Playwright storage-state after logging into XP",
            )
        templates = load_page_templates(cfg.guillotine, cookie, folder_key)
        for type_id in type_ids:
            type_rows.append(
                fetch_type_nodes(
                    cfg.guillotine, cookie, type_id, cfg.sample_per_type,
                )
            )
        for key in cfg.keys:
            query = PAGE_QUERY.format(key=_escape_key(key))
            payload = post_graphql(cfg.guillotine, query, cookie)
            pages.append(_page_record(key, 1, payload, index, cfg.context_by_key))
        for row in pages:
            _annotate_record(row, templates)
        round2_keys = [
            row["key"] for row in pages
            if row.get("round") == 1
            and row.get("key") in cfg.keys
            and row.get("context") in cfg.round2
        ]
        for key in _unique(round2_keys):
            query = PAGE_QUERY.format(key=_escape_key(key))
            payload = post_graphql(cfg.guillotine, query, cookie)
            pages.append(
                _annotate_record(
                    _page_record(key, 2, payload, index, cfg.context_by_key),
                    templates,
                )
            )
        seen_keys = {str(row.get("key") or "") for row in pages}
        for item in type_rows:
            for node in item.get("nodes") or []:
                if not isinstance(node, dict):
                    continue
                path = str(node.get("_path") or "")
                if not path or path in seen_keys:
                    continue
                pages.append(
                    _sample_runtime_page(
                        node, templates, index, cfg.context_by_key,
                    )
                )
                seen_keys.add(path)
        site_configs, config_env, endpoints, candidates = _harvest_live_config(
            ctx, cfg, pages, cookie,
        )
        ctx.write_json("inventory/live-config-candidates.json", candidates)  # type: ignore[attr-defined]
        usage = probe_usage(cfg.guillotine, cookie, resources)
        payload = {
            "schema": "extractkit.runtime-inventory/v1",
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
            **usage,
        }
        schema.validate(payload, "runtime-inventory", what="inventory/runtime.json")
        ctx.write_json("inventory/runtime.json", payload)  # type: ignore[attr-defined]
        _write_enonic_survey(ctx, cfg, folder_key, templates, type_rows)
        volume = survey_volume(cfg, cookie, type_ids)
        schema.validate(volume, "content-volume", what="inventory/content-volume.json")
        ctx.write_json("inventory/content-volume.json", volume)  # type: ignore[attr-defined]
        ctx.write_text("inventory/content-volume.md", render_volume_md(volume))  # type: ignore[attr-defined]
        _patch_openapi(ctx, endpoints)

    def check(self, _ctx: object) -> list[str]:
        return []


def _harvest_live_config(
    ctx: Any,
    cfg: CmsConfig,
    pages: list[dict],
    cookie: str,
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    site_configs: list[dict] = []
    site_public: list[dict] = []
    endpoints: list[dict] = []
    seen_ids: set[str] = set()
    project = cfg.project or "en"
    pinned = set(cfg.keys)
    for page in pages:
        content_id = str(page.get("id") or "")
        key = str(page.get("key") or "")
        if key not in pinned:
            continue
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
        record = live_config.site_config_record(key, content_id, body, cfg.rules)
        site_configs.append(record)
        site_public.append(live_config.public_fields(
            live_config.flatten_properties(body.get("data")),
        )[0])
        endpoints.extend(
            live_config.endpoints_from_site_fields(
                record.get("fields") or {}, content_key=key, rules=cfg.rules,
            )
        )
    config_env: list[dict] = []
    if not cfg.configenv:
        ctx.record_skip(
            "enonic.cms.configenv",
            "no Config Env URL: the profile sets no live_config.configenv_path "
            "and --configenv was not given",
            "pass --configenv <config-env-tool-url>, or set live_config.configenv_path "
            "in <source>/.extractkit/profile.yaml",
        )
        return _live_config_result(
            site_configs, site_public, config_env, endpoints, cfg.rules,
        )
    status, raw = http_get(cfg.configenv, cookie, accept="text/html")
    if status == 200:
        config_env = live_config.parse_configenv_html(raw.decode("utf-8", "replace"))
        endpoints.extend(live_config.endpoints_from_config_env(config_env, cfg.rules))
    elif status in (404, 405, 501):
        ctx.record_skip(
            "enonic.cms.configenv",
            f"Config Env GET {cfg.configenv} returned HTTP {status}: that admin tool "
            "is not installed on this XP",
            "pass --configenv <config-env-tool-url> if the tool lives at another path",
        )
    else:
        raise ExtractkitError(
            f"Config Env GET {cfg.configenv} returned HTTP {status}",
            "pass --configenv at the Config Env admin tool URL, or skip it if "
            "that tool is not installed",
            fix_args={"--configenv": "<config-env-url>"},
        )
    return _live_config_result(site_configs, site_public, config_env, endpoints, cfg.rules)


def _live_config_result(
    site_configs: list[dict],
    site_public: list[dict],
    config_env: list[dict],
    endpoints: list[dict],
    rules: live_config.Rules,
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    candidates = live_config.config_candidates(site_public, config_env, rules)
    return site_configs, config_env, live_config.dedupe_endpoints(endpoints), candidates


def _patch_openapi(ctx: object, endpoints: list[dict]) -> None:
    path = ctx.rel("integrations/openapi.yaml")  # type: ignore[attr-defined]
    spec = live_config.patch_openapi(path, endpoints)
    if spec is None:
        return
    ctx.write_yaml("integrations/openapi.yaml", spec)  # type: ignore[attr-defined]
    dest = ctx.rel("integrations/swagger-ui")  # type: ignore[attr-defined]
    if dest.is_dir():
        ctx.plan.record(f"write {dest / 'spec.js'}")  # type: ignore[attr-defined]
        write_swagger_spec(dest, spec)
