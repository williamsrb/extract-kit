"""XP7 page-template detection used by enonic.cms.

Guillotine `pageTemplate` is the *resolved* template, not the editor field.
Do not treat it as an explicit assignment.

Resolve order:

1. customized — `pageAsJson` has a descriptor/regions/children and no
   `page.template`
2. explicit — `pageAsJson.template` (path or id)
3. implicit — first `/_templates` child whose `data.supports` lists the
   content type (CMS folder order). A catch-all last in the folder (for
   example `forbidden-page`) loses to an earlier match.

`SAMPLE_PER_TYPE` is the per-type cap. `queryConnection(..., first=N)` is
that sample, not a tree walk (FR-14). Site Config harvest stays on the
pinned `--cms-key` list.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SAMPLE_PER_TYPE = 3
TEMPLATE_FOLDER = "_templates"
PORTAL_EXTRA_TYPES = (
    "portal:site",
    "portal:page-template",
    "portal:fragment",
)
RESOLVE_RULE = (
    "customized page (pageAsJson has descriptor/regions and no page.template)",
    "explicit page-template (pageAsJson.template)",
    (
        "implicit page-template: data.supports contains content type, "
        "first in /_templates child order"
    ),
)


@dataclass
class PageTemplate:
    path: str
    supports: tuple[str, ...]
    folder_index: int
    page: dict
    id: str = ""
    name: str = ""
    display_name: str = ""
    components: list = field(default_factory=list)


@dataclass(frozen=True)
class PageResolve:
    source: str
    customized: bool
    explicit: str | None
    template_path: str | None
    implicit_path: str | None
    implicit_paths: tuple[str, ...]
    effective: dict


def as_mapping(value: object) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def sample_per_type(profile_cms: dict | None, cli: dict | None = None) -> int:
    for blob in (cli or {}, profile_cms or {}):
        raw = blob.get("sample_per_type")
        if isinstance(raw, int) and raw >= 1:
            return raw
    return SAMPLE_PER_TYPE


def templates_folder_key(site_key: str) -> str:
    key = (site_key or "").strip() or "/"
    key = key.rstrip("/") or "/"
    return f"{key}/{TEMPLATE_FOLDER}"


def content_type_ids(resources: list[dict]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for resource in resources:
        if resource.get("kind") != "content-type":
            continue
        app = resource.get("app") or ""
        name = resource.get("name") or ""
        ident = f"{app}:{name}" if app and name else str(name or "")
        if ident and ident not in seen:
            seen.add(ident)
            ids.append(ident)
    for extra in PORTAL_EXTRA_TYPES:
        if extra not in seen:
            seen.add(extra)
            ids.append(extra)
    return ids


def supports_list(data: object) -> list[str]:
    mapping = as_mapping(data)
    raw = mapping.get("supports")
    if raw is None:
        raw = mapping.get("support")
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()]
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
            continue
        if not isinstance(item, dict):
            continue
        for key in ("contentType", "type", "id", "_name"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                out.append(value.strip())
                break
    return out


def parse_template(node: dict, folder_index: int) -> PageTemplate:
    path = str(node.get("_path") or "")
    return PageTemplate(
        path=path,
        supports=tuple(supports_list(node.get("dataAsJson"))),
        folder_index=folder_index,
        page=as_mapping(node.get("pageAsJson")),
        id=str(node.get("_id") or ""),
        name=str(node.get("_name") or path.rsplit("/", 1)[-1]),
        display_name=str(node.get("displayName") or ""),
        components=list(node.get("components") or [])
        if isinstance(node.get("components"), list) else [],
    )


def ordered_templates(templates: list[PageTemplate]) -> list[PageTemplate]:
    return sorted(templates, key=lambda item: item.folder_index)


def explicit_template_key(page: dict) -> str | None:
    if not isinstance(page, dict):
        return None
    raw = page.get("template")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if isinstance(raw, dict):
        for key in ("_path", "key", "path", "_id", "id"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def is_customized_page(page: dict) -> bool:
    if not isinstance(page, dict) or explicit_template_key(page):
        return False
    descriptor = page.get("descriptor")
    if isinstance(descriptor, str) and descriptor:
        return True
    regions = page.get("regions")
    if isinstance(regions, dict):
        for region in regions.values():
            if isinstance(region, dict) and region.get("components"):
                return True
    children = page.get("children")
    return bool(isinstance(children, list) and children)


def lookup_template(
    templates: list[PageTemplate],
    key: str,
) -> PageTemplate | None:
    if not key:
        return None
    for item in ordered_templates(templates):
        if key in (item.path, item.id, item.name):
            return item
        if item.path.endswith("/" + key):
            return item
    return None


def implicit_matches(
    content_type: str,
    templates: list[PageTemplate],
) -> list[PageTemplate]:
    if not content_type:
        return []
    return [item for item in ordered_templates(templates) if content_type in item.supports]


def resolve_page(
    content_type: str,
    page: dict,
    templates: list[PageTemplate],
) -> PageResolve:
    page = page if isinstance(page, dict) else {}
    explicit = explicit_template_key(page)
    matches = implicit_matches(content_type, templates)
    implicit_paths = tuple(item.path for item in matches)
    implicit = matches[0] if matches else None
    implicit_path = implicit.path if implicit else None
    if is_customized_page(page):
        return PageResolve(
            "customized", True, explicit, None, implicit_path,
            implicit_paths, page,
        )
    if explicit:
        found = lookup_template(templates, explicit)
        effective = found.page if found else {}
        path = found.path if found else explicit
        return PageResolve(
            "explicit-page-template", False, explicit, path, implicit_path,
            implicit_paths, effective if isinstance(effective, dict) else {},
        )
    if implicit:
        return PageResolve(
            "implicit-page-template", False, None, implicit.path,
            implicit_path, implicit_paths, implicit.page,
        )
    return PageResolve(
        "none", False, None, None, implicit_path, implicit_paths, {},
    )


def compact_page(page: dict | None) -> dict | None:
    if not isinstance(page, dict) or not page:
        return None
    children: list[dict] = []
    regions = page.get("regions")
    if isinstance(regions, dict):
        for region_name, region in regions.items():
            if not isinstance(region, dict):
                continue
            for component in region.get("components") or []:
                if not isinstance(component, dict):
                    continue
                child = compact_page(component)
                if child is None:
                    descriptor = component.get("descriptor")
                    if not isinstance(descriptor, str) or not descriptor:
                        continue
                    child = {"descriptor": descriptor}
                    if component.get("type"):
                        child["type"] = component["type"]
                child["region"] = region_name
                children.append(child)
    elif isinstance(page.get("children"), list):
        for component in page["children"]:
            if not isinstance(component, dict):
                continue
            child = compact_page(component)
            if child is None:
                descriptor = component.get("descriptor")
                if not isinstance(descriptor, str) or not descriptor:
                    continue
                child = {"descriptor": descriptor}
                if component.get("type"):
                    child["type"] = component["type"]
            if component.get("region"):
                child["region"] = component["region"]
            children.append(child)
    out: dict[str, Any] = {}
    if isinstance(page.get("descriptor"), str) and page["descriptor"]:
        out["descriptor"] = page["descriptor"]
    if isinstance(page.get("type"), str) and page["type"]:
        out["type"] = page["type"]
    if children:
        out["children"] = children
    return out or None


def component_edges(trees: list[dict | None]) -> list[dict]:
    counts: dict[tuple[str, str, str], int] = {}

    def walk(node: object, parent: str | None) -> None:
        if not isinstance(node, dict):
            return
        descriptor = node.get("descriptor")
        region = str(node.get("region") or "")
        if parent and isinstance(descriptor, str) and descriptor:
            key = (parent, region, descriptor)
            counts[key] = counts.get(key, 0) + 1
        nxt = descriptor if isinstance(descriptor, str) and descriptor else parent
        for child in node.get("children") or []:
            walk(child, nxt)
        regions = node.get("regions")
        if not isinstance(regions, dict):
            return
        for region_name, region_body in regions.items():
            if not isinstance(region_body, dict):
                continue
            for component in region_body.get("components") or []:
                if isinstance(component, dict) and region_name and "region" not in component:
                    tagged = dict(component)
                    tagged["region"] = region_name
                    walk(tagged, nxt)
                else:
                    walk(component, nxt)

    for tree in trees:
        walk(tree, None)
    rows = [
        {"parent": parent, "region": region, "child": child, "count": count}
        for (parent, region, child), count in counts.items()
    ]
    rows.sort(key=lambda row: (-int(row["count"]), row["parent"], row["region"], row["child"]))
    return rows


def node_to_raw_sample(node: dict) -> dict:
    page = compact_page(as_mapping(node.get("pageAsJson")))
    components = node.get("components") if isinstance(node.get("components"), list) else []
    return {
        "id": node.get("_id") or "",
        "path": node.get("_path") or "",
        "displayName": node.get("displayName") or "",
        "pageTemplate": None,
        "page": page,
        "components": components,
    }


def node_to_resolved_sample(node: dict, templates: list[PageTemplate]) -> dict:
    page = as_mapping(node.get("pageAsJson"))
    typ = str(node.get("type") or "")
    result = resolve_page(typ, page, templates)
    return {
        "path": node.get("_path") or "",
        "displayName": node.get("displayName") or "",
        "type": typ,
        "pageCustomized": result.customized,
        "pageTemplateField": result.explicit,
        "guillotinePageTemplate": None,
        "resolve": result.source,
        "resolvedTemplate": result.template_path,
        "implicitWouldBe": result.implicit_path,
        "implicitMatches": list(result.implicit_paths),
        "page": compact_page(result.effective),
    }


def cap_nodes(nodes: list[dict], limit: int) -> list[dict]:
    if limit < 1:
        return []
    return [node for node in nodes if isinstance(node, dict)][:limit]


def build_raw_survey(
    *,
    host: str,
    branch: str,
    sample_limit: int,
    types: list[dict],
) -> dict:
    rows: list[dict] = []
    empty: list[str] = []
    trees: list[dict | None] = []
    for item in types:
        typ = str(item.get("type") or "")
        total = int(item.get("totalCount") or 0)
        sampled = [node_to_raw_sample(node) for node in item.get("nodes") or []]
        rows.append({"type": typ, "totalCount": total, "sampled": sampled})
        if total == 0:
            empty.append(typ)
        for sample in sampled:
            trees.append(sample.get("page"))
    return {
        "schema": "99x.extract.content-survey/v1",
        "host": host,
        "branch": branch,
        "samplePerType": sample_limit,
        "types": rows,
        "component_edges": component_edges(trees),
        "empty_types": empty,
    }


def build_resolved_survey(
    *,
    sample_limit: int,
    folder_key: str,
    templates: list[PageTemplate],
    types: list[dict],
) -> dict:
    ordered = ordered_templates(templates)
    resolved_types: list[dict] = []
    trees: list[dict | None] = []
    for item in types:
        typ = str(item.get("type") or "")
        total = int(item.get("totalCount") or 0)
        sampled = [
            node_to_resolved_sample(node, ordered)
            for node in item.get("nodes") or []
        ]
        resolved_types.append({"type": typ, "totalCount": total, "sampled": sampled})
        for sample in sampled:
            trees.append(sample.get("page"))
    return {
        "schema": "99x.extract.content-survey-resolved/v1",
        "samplePerType": sample_limit,
        "templatesFolder": folder_key,
        "rule": list(RESOLVE_RULE),
        "templatesFolderOrder": [item.path for item in ordered],
        "templates": [
            {
                "path": item.path,
                "supports": list(item.supports),
                "folderIndex": item.folder_index,
                "page": compact_page(item.page) or {},
            }
            for item in ordered
        ],
        "types": resolved_types,
        "component_edges": component_edges(trees),
    }


def build_page_templates_doc(
    folder_key: str,
    templates: list[PageTemplate],
) -> dict:
    ordered = ordered_templates(templates)
    return {
        "schema": "99x.extract.page-templates/v1",
        "templatesFolder": folder_key,
        "total": len(ordered),
        "templates": [
            {
                "_path": item.path,
                "displayName": item.display_name,
                "supports": list(item.supports),
                "folderIndex": item.folder_index,
                "page": compact_page(item.page),
                "components": item.components,
            }
            for item in ordered
        ],
    }


def render_survey_md(survey: dict) -> str:
    host = survey.get("host") or ""
    limit = survey.get("samplePerType") or SAMPLE_PER_TYPE
    lines = [
        "# Content survey",
        "",
        (
            f"Host: `{host}`. Up to {limit} items per type "
            f"(`queryConnection` `first={limit}`, not a tree walk)."
        ),
        "",
        "## Counts",
        "",
    ]
    for row in survey.get("types") or []:
        typ = row.get("type") or ""
        total = row.get("totalCount")
        paths = [
            sample.get("path")
            for sample in (row.get("sampled") or [])
            if sample.get("path")
        ]
        sampled = ", ".join(f"`{path}`" for path in paths) if paths else "—"
        lines.append(f"- `{typ}`: {total} total; sampled {sampled}")
    lines.extend(["", "## Page descriptors by type (stored on content)", ""])
    wrote = False
    for row in survey.get("types") or []:
        counts: dict[str, int] = {}
        for sample in row.get("sampled") or []:
            page = sample.get("page") or {}
            descriptor = page.get("descriptor") if isinstance(page, dict) else None
            if isinstance(descriptor, str) and descriptor:
                counts[descriptor] = counts.get(descriptor, 0) + 1
        if not counts:
            continue
        wrote = True
        parts = ", ".join(f"`{name}` ×{n}" for name, n in sorted(counts.items()))
        lines.append(f"- `{row.get('type')}`: {parts}")
    if not wrote:
        lines.append("(none of the samples store a page descriptor)")
    lines.extend(["", "## Component containment (parent region child, stored)", ""])
    edges = survey.get("component_edges") or []
    if not edges:
        lines.append("(none)")
    else:
        for edge in edges:
            lines.append(
                f"- `{edge.get('parent')}` / {edge.get('region')} → "
                f"`{edge.get('child')}` ({edge.get('count')})"
            )
    empty = survey.get("empty_types") or []
    if empty:
        lines.extend(["", "## Empty types", ""])
        for typ in empty:
            lines.append(f"- `{typ}`")
    lines.append("")
    return "\n".join(lines)


def render_resolved_md(resolved: dict) -> str:
    folder = resolved.get("templatesFolder") or "/_templates"
    lines = [
        "# Content survey with page-template resolution",
        "",
        (
            "Order: customized page > explicit `page.template` > implicit "
            f"`data.supports` (first match in `{folder}` folder order)."
        ),
        "",
        (
            "Guillotine `pageTemplate` is already resolved; the kit does not "
            "treat it as an explicit assignment."
        ),
        "",
        f"## `{folder}` order + supports",
        "",
    ]
    templates = resolved.get("templates") or []
    if not templates:
        lines.append("(no page templates loaded)")
    for item in templates:
        supports = item.get("supports") or []
        listed = ", ".join(f"`{typ}`" for typ in supports) if supports else "(none)"
        lines.append(f"- `{item.get('path')}` supports {listed}")
    lines.extend(["", "## Sampled content resolution", ""])
    for row in resolved.get("types") or []:
        typ = row.get("type") or ""
        total = row.get("totalCount")
        sampled = row.get("sampled") or []
        if not sampled:
            lines.append(f"- `{typ}`: no content")
            continue
        parts = []
        for sample in sampled:
            path = sample.get("path") or ""
            source = sample.get("resolve") or "none"
            resolved_tmpl = sample.get("resolvedTemplate")
            extra = f" `{resolved_tmpl}`" if resolved_tmpl else ""
            parts.append(f"{path} → {source}{extra}")
        lines.append(f"- `{typ}` ({total}): {'; '.join(parts)}")
    lines.extend(["", "## Component containment (resolved pages)", ""])
    edges = resolved.get("component_edges") or []
    if not edges:
        lines.append("(none)")
    else:
        for edge in edges:
            lines.append(
                f"- `{edge.get('parent')}` / {edge.get('region')} → "
                f"`{edge.get('child')}` ({edge.get('count')})"
            )
    lines.append("")
    return "\n".join(lines)
