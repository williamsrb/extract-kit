"""enonic.forms — parse XP7 `<form>` and `<regions>` elements. Pure; no I/O."""

from __future__ import annotations

import xml.etree.ElementTree as ET

# XP7 defaults when an item has no <occurrences>: optional, single value.
DEFAULT_OCCURRENCES = {"min": 0, "max": 1}


def _int(raw: str | None, default: int) -> int:
    try:
        return int((raw or "").strip())
    except ValueError:
        return default


def _label(element: ET.Element) -> str | None:
    text = element.findtext("label")
    return text.strip() if text and text.strip() else None


def _occurrences(element: ET.Element) -> dict:
    node = element.find("occurrences")
    if node is None:
        return dict(DEFAULT_OCCURRENCES)
    return {
        "min": _int(node.get("minimum"), DEFAULT_OCCURRENCES["min"]),
        "max": _int(node.get("maximum"), DEFAULT_OCCURRENCES["max"]),
    }


def _config(element: ET.Element) -> dict[str, list[str]]:
    """Each config child becomes `tag -> [values]`. `value="…"` wins over text."""
    node = element.find("config")
    if node is None:
        return {}
    config: dict[str, list[str]] = {}
    for child in node:
        value = child.get("value")
        if value is None:
            value = (child.text or "").strip()
        config.setdefault(child.tag, []).append(value)
    return dict(sorted(config.items()))


def _items(element: ET.Element, field_set: str | None) -> list[dict]:
    container = element.find("items")
    return _walk(container, field_set) if container is not None else []


def _field(element: ET.Element, field_set: str | None) -> dict:
    field: dict = {
        "name": element.get("name") or "",
        "type": element.get("type") or "",
    }
    label = _label(element)
    if label:
        field["label"] = label
    field["occurrences"] = _occurrences(element)
    config = _config(element)
    if config:
        field["config"] = config
    if field_set:
        field["fieldSet"] = field_set
    return field


def _option_set(element: ET.Element, field_set: str | None) -> dict:
    field = _field(element, field_set)
    field["type"] = "option-set"
    options_node = element.find("options")
    options: list[dict] = []
    if options_node is not None:
        field["selection"] = {
            "min": _int(options_node.get("minimum"), 0),
            "max": _int(options_node.get("maximum"), 0),
        }
        for option in options_node.findall("option"):
            row: dict = {"name": option.get("name") or ""}
            label = _label(option)
            if label:
                row["label"] = label
            row["items"] = _items(option, field_set)
            options.append(row)
    field["options"] = options
    return field


def _walk(container: ET.Element, field_set: str | None) -> list[dict]:
    fields: list[dict] = []
    for child in container:
        tag = child.tag
        if tag == "input":
            fields.append(_field(child, field_set))
        elif tag == "item-set":
            field = _field(child, field_set)
            field["type"] = "item-set"
            field["items"] = _items(child, field_set)
            fields.append(field)
        elif tag == "option-set":
            fields.append(_option_set(child, field_set))
        elif tag == "field-set":
            fields.extend(_items(child, _label(child) or child.get("name") or ""))
        elif tag == "inline":
            ref = child.get("mixin")
            if ref:
                fields.append({"mixin": ref})
        elif tag == "mixin":
            ref = child.get("name")
            if ref:
                fields.append({"mixin": ref})
    return fields


def parse_form(element: ET.Element) -> list[dict]:
    """Fields of a descriptor root (or of a `<form>` itself), in document order."""
    form = element if element.tag == "form" else element.find("form")
    if form is None:
        return []
    return _walk(form, None)


def parse_regions(element: ET.Element) -> list[str]:
    """Region names of a page or layout descriptor root."""
    regions = element if element.tag == "regions" else element.find("regions")
    if regions is None:
        return []
    return [r.get("name") or "" for r in regions.findall("region") if r.get("name")]
