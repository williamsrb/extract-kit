"""Forms and regions: parsed from XP7 XML, carried into the maps with mixins expanded."""

from __future__ import annotations

import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from extractkit_cli.schema import validate
from steps.core.normalize import _expand_all, _mixin_index
from steps.enonic.descriptors import collect_resources
from steps.enonic.forms import parse_form, parse_regions
from tests.support import (
    FIXTURE,
    STATIC_UNTIL,
    copy_fixture,
    run,
    sidecar_run_dir,
)


def _by_name(fields: list[dict]) -> dict[str, dict]:
    return {f.get("name") or f.get("mixin"): f for f in fields}


class ParseFormTests(unittest.TestCase):
    def test_input_defaults_and_config(self) -> None:
        root = ET.fromstring(
            "<part><form>"
            '<input name="a" type="ComboBox"><label>A</label>'
            '<config><option value="x">X</option><option value="y">Y</option></config>'
            "</input></form></part>"
        )
        [field] = parse_form(root)
        self.assertEqual(field["occurrences"], {"min": 0, "max": 1})
        self.assertEqual(field["label"], "A")
        self.assertEqual(field["config"], {"option": ["x", "y"]})

    def test_field_set_is_flattened_with_label(self) -> None:
        root = ET.fromstring(
            "<mixin><form><field-set><label>Group</label><items>"
            '<input name="a" type="TextLine"/></items></field-set></form></mixin>'
        )
        [field] = parse_form(root)
        self.assertEqual(field["fieldSet"], "Group")

    def test_option_set_item_set_and_mixin_refs(self) -> None:
        root = ET.parse(
            FIXTURE / "xp/src/main/resources/site/content-types/mini-article/mini-article.xml"
        ).getroot()
        fields = _by_name(parse_form(root))
        option_set = fields["layoutChoice"]
        self.assertEqual(option_set["type"], "option-set")
        self.assertEqual(option_set["selection"], {"min": 1, "max": 1})
        self.assertEqual([o["name"] for o in option_set["options"]], ["wide", "narrow"])
        self.assertEqual(option_set["options"][0]["items"][0]["name"], "caption")
        self.assertEqual(fields["links"]["type"], "item-set")
        self.assertEqual(fields["links"]["items"][0]["name"], "href")
        self.assertEqual(
            fields["related"]["config"]["allowContentType"],
            ["com.example.mini:mini-article"],
        )
        self.assertEqual(fields["related"]["fieldSet"], "Related")
        self.assertIn("mini-mixin", fields)

    def test_missing_form_and_regions_are_empty(self) -> None:
        root = ET.fromstring("<service/>")
        self.assertEqual(parse_form(root), [])
        self.assertEqual(parse_regions(root), [])

    def test_regions(self) -> None:
        root = ET.fromstring('<page><regions><region name="a"/><region name="b"/></regions></page>')
        self.assertEqual(parse_regions(root), ["a", "b"])


class CollectTests(unittest.TestCase):
    def test_resources_carry_form_regions_and_xdata(self) -> None:
        rows = {(r["kind"], r["name"]): r for r in collect_resources(FIXTURE)}
        self.assertEqual(rows[("layout", "mini-layout")]["regions"], ["left", "right"])
        self.assertEqual(rows[("page", "mini-page")]["regions"], ["main"])
        self.assertNotIn("regions", rows[("part", "mini-part")])
        self.assertEqual(rows[("part", "mini-part")]["form"][0]["name"], "heading")
        self.assertNotIn("form", rows[("service", "mini-service")])
        self.assertEqual(
            rows[("site", "site")]["xData"],
            [{
                "name": "com.example.mini:mini-xdata",
                "allowContentTypes": "com\\.example\\.mini:mini-article",
            }],
        )


class MixinExpansionTests(unittest.TestCase):
    def test_known_mixin_is_expanded_and_tagged(self) -> None:
        mixins = {"a:m": [{"name": "x", "type": "TextLine"}]}
        out = _expand_all([{"mixin": "m"}], "a", mixins)
        self.assertEqual(out, [{"name": "x", "type": "TextLine", "fromMixin": "a:m"}])

    def test_unknown_mixin_stays_a_reference(self) -> None:
        out = _expand_all([{"mixin": "other:gone"}], "a", {})
        self.assertEqual(out, [{"mixin": "other:gone"}])

    def test_mixin_cycle_does_not_loop(self) -> None:
        mixins = {"a:m": [{"mixin": "m"}]}
        out = _expand_all([{"mixin": "m"}], "a", mixins)
        self.assertEqual(out, [{"mixin": "m", "fromMixin": "a:m"}])

    def test_nested_items_are_expanded(self) -> None:
        mixins = {"a:m": [{"name": "x", "type": "TextLine"}]}
        field = {"name": "set", "type": "item-set", "items": [{"mixin": "m"}]}
        [row] = _expand_all([field], "a", mixins)
        self.assertEqual(row["items"][0]["fromMixin"], "a:m")

    def test_index_uses_app_and_name(self) -> None:
        index = _mixin_index([{"kind": "mixin", "app": "a", "name": "m", "form": []}])
        self.assertEqual(list(index), ["a:m"])


class MapTests(unittest.TestCase):
    def test_maps_carry_fields_config_regions_and_validate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            result = run("run", "--profile", "enonic", "--source", str(source), *STATIC_UNTIL)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            out = sidecar_run_dir(source)
            model = json.loads((out / "map/content-model.json").read_text())
            components = json.loads((out / "map/component-map.json").read_text())
            validate(model, "content-model")
            validate(components, "component-map")
            article = next(t for t in model["types"] if t["id"].endswith(":content-type:mini-article"))
            names = [f.get("name") or f.get("mixin") for f in article["fields"]]
            self.assertIn("seoTitle", names)
            self.assertIn("com.other.app:external", names)
            seo = next(f for f in article["fields"] if f.get("name") == "seoTitle")
            self.assertEqual(seo["fromMixin"], "com.example.mini:mini-mixin")
            layout = next(c for c in components["components"] if c["kind"] == "layout")
            self.assertEqual(layout["regions"], ["left", "right"])
            part = next(c for c in components["components"] if c["kind"] == "part")
            self.assertEqual(part["config"][0]["name"], "heading")

    def test_reference_graph_comes_from_selectors_and_survives_merge(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            run("run", "--profile", "enonic", "--source", str(source), *STATIC_UNTIL)
            out = sidecar_run_dir(source)
            merged = run(
                "run", "--profile", "enonic", "--source", str(source), "--out", str(out),
                "--from", "maps.merge", "--until", "maps.merge",
            )
            self.assertEqual(merged.returncode, 0, merged.stderr + merged.stdout)
            model = json.loads((out / "map/content-model.json").read_text())
            validate(model, "content-model")
            refs = {(r["from"], r["field"]): r["to"] for r in model["references"]}
            article = "com.example.mini:content-type:mini-article"
            self.assertEqual(refs[(article, "related")], ["com.example.mini:mini-article"])
            self.assertEqual(refs[(article, "heroImage")], ["media:image"])
            self.assertIn(("com.example.mini:mixin:mini-mixin", "heroImage"), refs)


if __name__ == "__main__":
    unittest.main()
