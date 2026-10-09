"""End to end: template inventory, component mapping, view rules, and their `check` gates."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from extractkit_cli.schema import validate
from tests.support import FIXTURE, REPO, run, sidecar_run_dir

MINI = REPO / "tests" / "fixtures" / "templates-mini"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def static_run(source: Path) -> Path:
    result = run("run", "--profile", "enonic", "--source", str(source), "--until", "static")
    assert result.returncode == 0, result.stderr + result.stdout
    return sidecar_run_dir(source)


def rest_run(source: Path, out: Path) -> None:
    result = run(
        "run", "--profile", "enonic", "--source", str(source), "--out", str(out),
        "--from", "merge", "--until", "synthesis",
    )
    assert result.returncode == 0, result.stderr + result.stdout


class StaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.source = Path(cls._tmp.name) / "legacy"
        shutil.copytree(MINI, cls.source)
        cls.out = static_run(cls.source)
        cls.templates = read(cls.out / "inventory" / "templates.json")
        cls.components = read(cls.out / "map" / "component-map.json")["components"]

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_templates_json_is_valid_and_lists_engines(self) -> None:
        validate(self.templates, "templates", what="templates.json")
        self.assertEqual(
            {e["id"] for e in self.templates["engines"]},
            {"freemarker", "thymeleaf", "mustache", "handlebars", "pebble", "react", "nextjs",
             "angular", "vue", "jquery"},
        )

    def test_one_surface_per_template_file(self) -> None:
        mapped = [c["template"]["file"] for c in self.components]
        self.assertEqual(sorted(mapped), sorted(f["path"] for f in self.templates["files"]))
        self.assertEqual(len(set(mapped)), len(mapped))

    def test_planted_includes_resolve_to_surface_ids(self) -> None:
        ids = {c["id"] for c in self.components}
        by_file = {c["template"]["file"]: c["template"] for c in self.components}
        for path, ref in (
            ("thymeleaf/templates/product-card.html", "fragments/price-tag"),
            ("freemarker/templates/product-card.ftl", "price-tag.ftl"),
            ("pebble/templates/product-card.peb", "price-tag.peb"),
            ("react/src/ProductCard.tsx", "PriceTag"),
            ("vue/src/ProductCard.vue", "PriceTag"),
            ("angular/src/app/product-card.component.ts", "app-price-tag"),
            ("handlebars/views/product-card.hbs", "price-tag"),
        ):
            child = next(c for c in by_file[path]["children"] if c["ref"] == ref)
            self.assertEqual(child["status"], "resolved", path)
            self.assertIn(child["surface"], ids, path)
            self.assertIn(f"{by_file[path]['engine']}:partial:", child["surface"], path)

    def test_a_partial_prefers_its_own_folder(self) -> None:
        by_file = {c["template"]["file"]: c["template"] for c in self.components}
        child = by_file["mustache/views/product-card.mustache"]["children"][0]
        self.assertEqual(child["surface"], "mustache:partial:mustache/views/price-tag")

    def test_every_component_is_spec_ready(self) -> None:
        for component in self.components:
            template = component["template"]
            self.assertTrue(component["entry"])
            self.assertIsInstance(template["inputs"], list)
            self.assertTrue(template["dataSource"])
            self.assertTrue(all(c["status"] in ("resolved", "unresolved") for c in template["children"]))

    def test_nextjs_pages_get_a_route_data_source(self) -> None:
        page = next(c for c in self.components if c["template"]["file"] == "nextjs/pages/product.tsx")
        self.assertEqual(page["template"]["dataSource"], "next:route:/product")
        routes = read(self.out / "map" / "route-map.json")["routes"]
        self.assertIn("next:route:/product", [r["id"] for r in routes])

    def test_check_passes_then_names_a_file_whose_surface_was_removed(self) -> None:
        self.assertEqual(run("check", "--out", str(self.out)).returncode, 0)
        path = self.out / "map" / "component-map.json"
        original = path.read_text(encoding="utf-8")
        try:
            payload = json.loads(original)
            gone = payload["components"].pop(0)["template"]["file"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = run("check", "--out", str(self.out))
            self.assertEqual(result.returncode, 1)
            self.assertIn(gone, result.stdout + result.stderr)
        finally:
            path.write_text(original, encoding="utf-8")

    def test_a_component_missing_its_data_source_is_not_spec_ready(self) -> None:
        path = self.out / "map" / "component-map.json"
        original = path.read_text(encoding="utf-8")
        try:
            payload = json.loads(original)
            payload["components"][0]["template"]["dataSource"] = ""
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = run("check", "--out", str(self.out))
            self.assertEqual(result.returncode, 1)
            self.assertIn("not spec-ready", result.stdout)
        finally:
            path.write_text(original, encoding="utf-8")


class EnonicJoinTests(unittest.TestCase):
    def test_descriptor_and_view_are_one_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "legacy"
            shutil.copytree(FIXTURE, source)
            out = static_run(source)
            components = read(out / "map" / "component-map.json")["components"]
            part = [c for c in components if c["id"].endswith(":part:mini-part")]
            self.assertEqual(len(part), 1)
            self.assertEqual(part[0]["template"]["engine"], "thymeleaf")
            self.assertTrue(part[0]["template"]["file"].endswith("mini-part/mini-part.html"))
            self.assertTrue(part[0]["config"] is not None or part[0].get("fields") is not None)
            self.assertEqual(part[0]["template"]["dataSource"], part[0]["id"])
            self.assertEqual([c["id"] for c in components if "template" in c], [part[0]["id"]])
            self.assertEqual(run("check", "--out", str(out)).returncode, 0)
            merged = run(
                "run", "--profile", "enonic", "--source", str(source), "--out", str(out),
                "--from", "merge", "--until", "merge",
            )
            self.assertEqual(merged.returncode, 0, merged.stderr)
            after = read(out / "map" / "component-map.json")["components"]
            self.assertEqual(
                [c["template"]["file"] for c in after if "template" in c],
                [part[0]["template"]["file"]],
            )


class ControllerRuleTests(unittest.TestCase):
    def test_branch_over_content_data_before_render_is_a_rule_on_the_merged_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "legacy"
            shutil.copytree(FIXTURE, source)
            controller = source / "xp/src/main/resources/site/parts/mini-part/mini-part.js"
            text = controller.read_text(encoding="utf-8")
            branch = "  if (app.config['miniMode'] === 'vip' && content.data.price > 500) {\n    mode = 'vip';\n  }\n"
            controller.write_text(text.replace("  return { body", branch + "  return { body"), encoding="utf-8")
            out = static_run(source)
            rest_run(source, out)
            rules = read(out / "rules" / "view-rules.json")["rules"]
            found = [r for r in rules if r["source"].startswith("xp/src/main/resources/site/parts/mini-part/mini-part.js:")]
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["bucket"], "business")
            self.assertTrue(found[0]["component"].endswith(":part:mini-part"))
            self.assertEqual(run("check", "--out", str(out)).returncode, 0)


class RulesPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.source = Path(cls._tmp.name) / "legacy"
        shutil.copytree(MINI, cls.source)
        cls.out = static_run(cls.source)
        rest_run(cls.source, cls.out)
        cls.payload = read(cls.out / "rules" / "view-rules.json")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_outputs_exist_and_validate(self) -> None:
        validate(self.payload, "view-rules", what="view-rules.json")
        for name in ("RULES.md", "literals.md", "review.md"):
            self.assertTrue((self.out / "rules" / name).is_file(), name)
        first = (self.out / "rules" / "RULES.md").read_text(encoding="utf-8").splitlines()
        self.assertTrue(first[2].startswith("Coverage: "), first[:4])

    def test_operands_resolve_against_component_inputs(self) -> None:
        rule = next(r for r in self.payload["rules"] if r["source"].startswith("react/src/ProductCard.tsx:15"))
        self.assertEqual(rule["operands"][0]["resolved"], "input")
        self.assertTrue(rule["operands"][0]["ref"].endswith("#price"))
        self.assertTrue(rule["component"].startswith("react:component:"))

    def test_divergent_groups_come_first_in_rules_md(self) -> None:
        text = (self.out / "rules" / "RULES.md").read_text(encoding="utf-8")
        self.assertLess(text.index("## Divergent rules"), text.index("## Context"))

    def test_literals_catalogue_lists_both_thresholds(self) -> None:
        text = (self.out / "rules" / "literals.md").read_text(encoding="utf-8")
        self.assertIn("| `100` |", text)
        self.assertIn("| `150` |", text)

    def test_spec_cites_rule_ids_and_asks_about_divergent_groups(self) -> None:
        spec = (self.out / "spec-kit" / "evidence" / "presentation.md").read_text(encoding="utf-8")
        business = [r for r in self.payload["rules"] if r["bucket"] == "business"]
        for rule in business:
            self.assertIn(rule["id"], spec)
        self.assertIn("## Open questions", spec)
        self.assertIn("## Components", spec)
        use_cases = (self.out / "use-cases" / "presentation.md").read_text(encoding="utf-8")
        self.assertIn(business[0]["id"], use_cases)

    def test_check_passes_and_fails_closed_on_an_uncited_business_rule(self) -> None:
        self.assertEqual(run("check", "--out", str(self.out)).returncode, 0)
        target = next(r for r in self.payload["rules"] if r["bucket"] == "business" and r["source"].startswith("vue/"))
        spec_path = self.out / "spec-kit" / "evidence" / "presentation.md"
        review_path = self.out / "rules" / "review.md"
        spec, review = spec_path.read_text(encoding="utf-8"), review_path.read_text(encoding="utf-8")
        try:
            spec_path.write_text(spec.replace(target["id"], "VR-redacted"), encoding="utf-8")
            result = run("check", "--out", str(self.out))
            self.assertEqual(result.returncode, 1)
            self.assertIn(target["id"], result.stdout)
            lines = review.splitlines()
            at = next(i for i, line in enumerate(lines) if target["id"] in line)
            end = next(i for i in range(at, len(lines)) if lines[i].strip().startswith("- out-of-scope:"))
            lines[end] = "  - out-of-scope: yes"
            review_path.write_text("\n".join(lines), encoding="utf-8")
            self.assertEqual(run("check", "--out", str(self.out)).returncode, 0)
        finally:
            spec_path.write_text(spec, encoding="utf-8")
            review_path.write_text(review, encoding="utf-8")

    def test_a_name_in_review_md_carries_over_to_the_next_run(self) -> None:
        review_path = self.out / "rules" / "review.md"
        original = review_path.read_text(encoding="utf-8")
        try:
            review_path.write_text(
                original.replace("  - name:\n", "  - name: Premium limit _(inferred)_\n", 1), encoding="utf-8",
            )
            rest_run(self.source, self.out)
            rerun = read(self.out / "rules" / "view-rules.json")
            named = [r for r in rerun["rules"] if r.get("name") == "Premium limit"]
            self.assertEqual(len(named), 1)
            self.assertEqual([r["id"] for r in rerun["rules"]], [r["id"] for r in self.payload["rules"]])
            self.assertIn("Premium limit _(inferred)_", (self.out / "rules" / "RULES.md").read_text(encoding="utf-8"))
        finally:
            review_path.write_text(original, encoding="utf-8")
            rest_run(self.source, self.out)


if __name__ == "__main__":
    unittest.main()
