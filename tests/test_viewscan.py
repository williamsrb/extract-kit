"""View-layer scanners: engine detection, per-engine facts, and the planted business rules."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

from extractkit_cli.schema import validate
from steps.core import templates, view_rules
from steps.core.viewscan import dead, expr as ex
from tests.support import REPO

MINI = REPO / "tests" / "fixtures" / "templates-mini"
LOW = REPO / "tests" / "fixtures" / "templates-low"

ENGINE_FOLDERS = {
    "freemarker": "freemarker", "thymeleaf": "thymeleaf", "mustache": "mustache",
    "handlebars": "handlebars", "pebble": "pebble", "react": "react", "nextjs": "nextjs",
    "angular": "angular", "vue": "vue", "jquery": "jquery",
}


def scan(folder: Path) -> dict:
    return templates.collect(folder, {}, set(), [])


def line_of(path: Path, needle: str) -> int:
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if needle in line:
            return number
    raise AssertionError(f"{needle!r} not in {path}")


def rules_in(folder: Path) -> tuple[list[dict], list[dict]]:
    rules = view_rules.build_rules(scan(folder), [], [], {})
    return rules, view_rules.group_rules(rules)


class DetectionTests(unittest.TestCase):
    def test_every_engine_folder_is_detected_with_files(self) -> None:
        payload = scan(MINI)
        validate(payload, "templates", what="templates.json")
        engines = {e["id"]: e for e in payload["engines"]}
        for engine in ("freemarker", "thymeleaf", "mustache", "handlebars", "pebble", "react",
                       "angular", "vue", "jquery", "nextjs"):
            self.assertIn(engine, engines, engine)
            self.assertGreater(engines[engine]["files"], 0, engine)
            self.assertEqual(engines[engine]["confidence"], "high", engine)

    def test_signals_cite_path_line_and_rule(self) -> None:
        for engine in scan(MINI)["engines"]:
            for signal in engine["signals"]:
                self.assertGreaterEqual(signal["line"], 1)
                self.assertTrue(signal["rule"])
                self.assertTrue((MINI / signal["path"]).is_file())

    def test_nextjs_records_react_and_routes(self) -> None:
        payload = scan(MINI / "nextjs")
        by_path = {f["path"]: f for f in payload["files"]}
        page = by_path["pages/product.tsx"]
        self.assertEqual((page["engine"], page["framework"], page["route"]), ("react", "nextjs", "/product"))
        self.assertEqual({e["id"] for e in payload["engines"]}, {"nextjs", "react"})

    def test_decoys_and_excluded_folders_do_not_register(self) -> None:
        payload = scan(MINI)
        paths = [f["path"] for f in payload["files"]]
        self.assertFalse([p for p in paths if p.startswith("decoys/")])
        signal_paths = [s["path"] for e in payload["engines"] for s in e["signals"]]
        self.assertFalse([p for p in signal_paths if p.startswith("decoys/")])
        self.assertIn("node_modules", payload["coverage"]["excluded"])

    def test_jquery_found_only_by_usage_is_low(self) -> None:
        engines = {e["id"]: e["confidence"] for e in scan(LOW)["engines"]}
        self.assertEqual(engines, {"jquery": "low"})

    def test_angular_template_is_a_companion_not_a_second_file(self) -> None:
        files = {f["path"]: f for f in scan(MINI / "angular")["files"]}
        card = files["src/app/product-card.component.ts"]
        self.assertEqual(card["companions"], ["src/app/product-card.component.html"])
        self.assertNotIn("src/app/product-card.component.html", files)


class FactTests(unittest.TestCase):
    def facts(self, folder: str, path: str) -> dict:
        return {f["path"]: f for f in scan(MINI / folder)["files"]}[path]["scan"]

    def test_thymeleaf_fragment_children_and_i18n(self) -> None:
        scan_ = self.facts("thymeleaf", "templates/product-card.html")
        self.assertEqual([c["ref"] for c in scan_["children"]], ["fragments/price-tag"])
        self.assertEqual([s["name"] for s in scan_["slots"]], ["card"])
        self.assertEqual([i["key"] for i in scan_["i18n"]], ["card.buy"])
        declared = {i["name"] for i in scan_["inputs"] if not i["inferred"]}
        self.assertEqual(declared, {"title", "price"})
        self.assertEqual(scan_["logic"], {"loops": 1, "conditionals": 2})

    def test_freemarker_macro_params_are_inputs_and_includes_are_children(self) -> None:
        scan_ = self.facts("freemarker", "templates/product-card.ftl")
        self.assertEqual({i["name"] for i in scan_["inputs"] if not i["inferred"]}, {"title", "price"})
        self.assertEqual([c["ref"] for c in scan_["children"]], ["price-tag.ftl", "@pt.tag"])
        self.assertNotIn("size", {i["name"] for i in scan_["inputs"]})

    def test_react_props_are_typed_and_callbacks_are_outputs(self) -> None:
        scan_ = self.facts("react", "src/ProductCard.tsx")
        typed = {i["name"]: i["type"] for i in scan_["inputs"]}
        self.assertEqual(typed, {"title": "string", "price": "number", "items": "string[]"})
        self.assertEqual([o["name"] for o in scan_["outputs"]], ["onBuy"])
        self.assertEqual([c["ref"] for c in scan_["children"]], ["PriceTag"])

    def test_angular_inputs_outputs_and_template_children(self) -> None:
        scan_ = self.facts("angular", "src/app/product-card.component.ts")
        self.assertEqual({i["name"] for i in scan_["inputs"]}, {"title", "price", "items"})
        self.assertEqual([o["name"] for o in scan_["outputs"]], ["buy"])
        self.assertEqual([c["ref"] for c in scan_["children"]], ["app-price-tag"])
        self.assertEqual({p["file"] for p in scan_["predicates"]}, {"src/app/product-card.component.html"})

    def test_vue_props_emits_and_template(self) -> None:
        scan_ = self.facts("vue", "src/ProductTile.vue")
        self.assertEqual({i["name"] for i in scan_["inputs"]}, {"price", "quantity"})
        self.assertEqual([c["ref"] for c in scan_["children"]], ["PriceTag"])
        self.assertEqual(
            {p["construct"] for p in scan_["predicates"]}, {"v-if", "computed"},
        )

    def test_handlebars_partials_and_helper_bodies(self) -> None:
        card = self.facts("handlebars", "views/product-card.hbs")
        self.assertEqual([c["ref"] for c in card["children"]], ["price-tag"])
        helper = self.facts("handlebars", "js/helpers.js")
        self.assertEqual([p["construct"] for p in helper["predicates"]], ["registerHelper:isPremium"])

    def test_jquery_handlers_bind_to_markup_that_has_the_id(self) -> None:
        files = {f["path"]: f for f in scan(MINI / "jquery")["files"]}
        page = files["index.html"]["scan"]["dom"]
        self.assertIn(("#buy", "click", "js/product.js"), {(d["selector"], d["event"], d["script"]) for d in page})
        self.assertIn("js/tile.js", {d["script"] for d in page})


class ExpressionTests(unittest.TestCase):
    def test_equivalent_spellings_share_a_shape(self) -> None:
        shapes = {ex.shape(s) for s in ("price gt 100", "${item.price > 100.0}", "props.price>100", "price > 100")}
        self.assertEqual(shapes, {"$price > 100"})

    def test_different_literal_changes_the_shape(self) -> None:
        self.assertNotEqual(ex.shape("price > 100"), ex.shape("price > 150"))

    def test_length_checks_normalize(self) -> None:
        self.assertEqual(ex.shape("items.size() > 0"), ex.shape("items.length > 0"))
        self.assertEqual(ex.shape("products?size gt 0"), "$products.#len > 0")

    def test_operands_skip_keywords_calls_and_strings(self) -> None:
        self.assertEqual(ex.operands("user.role == 'admin' && !empty(cart)"), ["user.role", "cart"])
        self.assertEqual(ex.operands("Math.round(total) > limit"), ["total", "limit"])


class PlantedRuleTests(unittest.TestCase):
    """Every engine fixture plants a price threshold, a presentation guard and a divergent pair."""

    CASES: ClassVar[dict[str, tuple[str, ...]]] = {
        "freemarker": ("templates/product-card.ftl", "price gt 100", "templates/product-tile.ftl", "price gt 150", "templates/product-card.ftl", "products?size gt 0"),
        "thymeleaf": ("templates/product-card.html", "${price > 100}", "templates/product-tile.html", "${price > 150}", "templates/product-card.html", "items.size() > 0"),
        "handlebars": ("views/product-card.hbs", "(gt price 100)", "views/product-tile.hbs", "(gt price 150)", "views/product-card.hbs", "items.length"),
        "pebble": ("templates/product-card.peb", "price > 100", "templates/product-tile.peb", "price > 150", "templates/product-card.peb", "items is not empty"),
        "react": ("src/ProductCard.tsx", "price > 100", "src/ProductTile.tsx", "price > 150", "src/ProductCard.tsx", "items.length > 0"),
        "nextjs": ("pages/product.tsx", "price > 100", "pages/featured.tsx", "price > 150", "pages/product.tsx", "items.length > 0"),
        "angular": ("src/app/product-card.component.html", "price > 100", "src/app/product-tile.component.html", "price > 150", "src/app/product-card.component.html", "items.length > 0"),
        "vue": ("src/ProductCard.vue", "price > 100", "src/ProductTile.vue", "price > 150", "src/ProductCard.vue", "items.length > 0"),
        "jquery": ("js/product.js", "> 100", "js/tile.js", "> 150", "js/product.js", "children().length > 0"),
    }

    def rule_at(self, rules: list[dict], folder: Path, path: str, needle: str) -> dict:
        source = f"{path}:{line_of(folder / path, needle)}"
        found = [r for r in rules if r["source"] == source]
        self.assertEqual(len(found), 1, f"{source}: {[r['source'] for r in rules]}")
        return found[0]

    def test_threshold_guard_and_divergent_pair_per_engine(self) -> None:
        for engine, (a_path, a_needle, b_path, b_needle, g_path, g_needle) in self.CASES.items():
            with self.subTest(engine=engine):
                folder = MINI / ENGINE_FOLDERS[engine]
                rules, groups = rules_in(folder)
                first = self.rule_at(rules, folder, a_path, a_needle)
                second = self.rule_at(rules, folder, b_path, b_needle)
                guard = self.rule_at(rules, folder, g_path, g_needle)
                for rule in (first, second):
                    self.assertEqual(rule["bucket"], "business")
                    self.assertIn(rule["kind"], ("eligibility", "calculation"))
                    self.assertTrue(rule["divergent"], rule)
                    self.assertIn("price", [o["leaf"] for o in rule["operands"]])
                self.assertEqual(guard["bucket"], "presentational")
                self.assertFalse(guard["divergent"])
                self.assertEqual(first["group"], second["group"])
                self.assertEqual([g["type"] for g in groups if g["id"] == first["group"]], ["divergent"])

    def test_mustache_section_named_by_a_domain_term_is_business(self) -> None:
        folder = MINI / "mustache"
        rules, _ = rules_in(folder)
        flag = self.rule_at(rules, folder, "views/product-card.mustache", "{{#discountEligible}}")
        self.assertEqual((flag["bucket"], flag["kind"]), ("business", "eligibility"))
        guard = self.rule_at(rules, folder, "views/product-card.mustache", "{{^items}}")
        self.assertEqual(guard["bucket"], "presentational")

    def test_calculation_is_business_and_formatting_is_not(self) -> None:
        folder = MINI / "thymeleaf"
        rules, _ = rules_in(folder)
        calc = self.rule_at(rules, folder, "templates/product-tile.html", "total=${price * quantity}")
        self.assertEqual((calc["kind"], calc["bucket"]), ("calculation", "business"))
        fmt = self.rule_at(rules, folder, "templates/fragments/price-tag.html", "formatDecimal")
        self.assertEqual((fmt["kind"], fmt["bucket"]), ("formatting", "presentational"))

    def test_ids_are_stable_across_runs(self) -> None:
        folder = MINI / "react"
        self.assertEqual([r["id"] for r in rules_in(folder)[0]], [r["id"] for r in rules_in(folder)[0]])

    def test_every_rule_cites_a_real_line(self) -> None:
        for folder in (p for p in MINI.iterdir() if p.is_dir() and p.name != "decoys"):
            for rule in rules_in(folder)[0]:
                path, line = rule["source"].rsplit(":", 1)
                lines = (folder / path).read_text(encoding="utf-8").splitlines()
                self.assertTrue(1 <= int(line) <= len(lines), rule["source"])


class ReviewCarryOverTests(unittest.TestCase):
    def test_names_ticks_and_scope_survive_a_rerun_and_removed_ids_are_listed(self) -> None:
        folder = MINI / "react"
        rules, groups = rules_in(folder)
        text = view_rules.render_review_md(rules, [])
        target = next(r for r in rules if r["bucket"] == "business")
        other = next(r for r in rules if r["bucket"] == "business" and r["id"] != target["id"])
        edited = text.replace(
            f"- [ ] `{target['id']}`", f"- [x] `{target['id']}`",
        ).replace("  - name:\n", "  - name: Premium threshold _(inferred)_\n", 1).replace(
            "  - intent:\n", "  - intent: Show the premium badge above the limit _(inferred)_\n", 1,
        )
        edited += "\n- [ ] `VR-0000000000` gone\n  - name: Old\n  - intent: Old\n  - out-of-scope: no\n"
        state = view_rules.parse_review(edited)
        fresh, _ = rules_in(folder)
        removed = view_rules.apply_review(fresh, state)
        carried = next(r for r in fresh if r["id"] == target["id"])
        self.assertEqual(carried["name"], "Premium threshold")
        self.assertEqual(carried["status"], "confirmed")
        self.assertEqual(next(r for r in fresh if r["id"] == other["id"])["status"], "extracted")
        self.assertEqual(removed, ["VR-0000000000"])
        self.assertIn("VR-0000000000", view_rules.render_review_md(fresh, removed))
        self.assertTrue(groups is not None)

    def test_out_of_scope_is_parsed(self) -> None:
        text = "- [ ] `VR-abcdef0123` x\n  - name:\n  - intent:\n  - out-of-scope: yes\n"
        self.assertTrue(view_rules.parse_review(text)["VR-abcdef0123"]["outOfScope"])


class NameBatchTests(unittest.TestCase):
    REVIEW = (
        "# Rule review\n\n"
        "- [ ] `VR-aaaaaaaaaa` `a.html:1` · eligibility · `x == 1`\n  - name:\n  - intent:\n  - out-of-scope: no\n\n"
        "- [x] `VR-bbbbbbbbbb` `b.html:2` · eligibility · `y == 2`\n  - name: kept\n  - intent: kept it\n  - out-of-scope: no\n\n"
        "- [ ] `VR-cccccccccc` `c.html:3` · eligibility · `z == 3`\n  - name:\n  - intent:\n  - out-of-scope: yes\n"
    )

    def test_names_go_in_by_id_and_survive_a_re_parse(self) -> None:
        names = {"VR-aaaaaaaaaa": ("Open order", "An order is open."), "VR-cccccccccc": ("Gate", "Gate rule.")}
        text, applied, unknown, ticked = view_rules.apply_names(self.REVIEW, names)
        self.assertEqual((applied, unknown, ticked), (["VR-aaaaaaaaaa", "VR-cccccccccc"], [], []))
        state = view_rules.parse_review(text)
        self.assertEqual(state["VR-aaaaaaaaaa"]["name"], "Open order")
        self.assertEqual(state["VR-aaaaaaaaaa"]["intent"], "An order is open.")
        self.assertIn("  - name: Open order _(inferred)_\n", text)
        self.assertTrue(state["VR-cccccccccc"]["outOfScope"])

    def test_a_ticked_rule_and_an_unknown_id_are_reported_not_applied(self) -> None:
        names = {"VR-bbbbbbbbbb": ("New", "New words."), "VR-dddddddddd": ("Ghost", "No such rule.")}
        text, applied, unknown, ticked = view_rules.apply_names(self.REVIEW, names)
        self.assertEqual((applied, unknown, ticked), ([], ["VR-dddddddddd"], ["VR-bbbbbbbbbb"]))
        self.assertEqual(text, self.REVIEW)


class SampleTests(unittest.TestCase):
    def test_samples_are_capped_and_always_empty_business_rules_are_possibly_dead(self) -> None:
        rules, _ = rules_in(MINI / "react")
        live = next(r for r in rules if r["source"].startswith("src/ProductCard.tsx:15"))
        dead = next(r for r in rules if r["source"].startswith("src/ProductTile.tsx:10"))
        values = {"price": [*range(20)]}
        view_rules.attach_samples([live], values)
        self.assertEqual(len(live["samples"]["price"]), 10)
        self.assertNotIn("possiblyDead", live)
        view_rules.attach_samples([dead], {"price": [None, ""]})
        self.assertTrue(dead["possiblyDead"])

    def test_without_a_sample_nothing_is_flagged(self) -> None:
        rules, _ = rules_in(MINI / "react")
        view_rules.attach_samples(rules, None)
        self.assertFalse([r for r in rules if "possiblyDead" in r or "samples" in r])


class CoverageTests(unittest.TestCase):
    def test_oversized_files_are_reported_as_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "big.js").write_text("$('#a').on('click', function () {});\n" + "x" * 1_100_000)
            payload = scan(root)
        self.assertEqual([s["path"] for s in payload["coverage"]["skipped"]], ["big.js"])
        self.assertEqual(payload["files"], [])


if __name__ == "__main__":
    unittest.main()


class DeadCodeTests(unittest.TestCase):
    def test_markup_spans_cover_comments_and_constant_false_blocks(self) -> None:
        from steps.core.viewscan import dead

        text = (
            "<div th:text=\"${a}\"></div>\n"
            "<!-- <div data-th-if=\"${booking.status == 'paid'}\">x</div> -->\n"
            "<div data-th-if=\"false\"><span th:if=\"${x > 3}\">no</span>\n</div>\n"
            "<!--/*/ <p th:if=\"${live}\">proto</p> /*/-->\n"
        )
        spans = dead.markup_spans(text)
        self.assertEqual([(s.start, s.end, s.gate) for s in spans], [(2, 2, 2), (3, 4, 3)])
        self.assertEqual(spans[0].reason, "html-comment")

    def test_js_spans_follow_module_constants(self) -> None:
        from steps.core.viewscan import dead

        text = (
            "const DISABLED = true\nconst ON = false\n"
            "function a(x) {\n  if (DISABLED) return 1\n  if (x > 3) { go() }\n}\n"
            "function b() {\n  if (ON) { foo() }\n  else { keep() }\n  if (!ON) { fine() } else { gone() }\n}\n"
        )
        got = [(s.start, s.end, s.gate) for s in dead.js_spans(text)]
        self.assertEqual(got, [(5, 5, 4), (8, 8, 8), (10, 10, 10)])

    def test_js_spans_stay_off_live_code(self) -> None:
        from steps.core.viewscan import dead

        conditional_exit = "const FLAG = true\nfunction f(a) {\n  if (FLAG) {\n    if (a)\n      return\n  }\n  live(a)\n}\n"
        reassigned = "let ON = false\nfunction f() {\n  ON = true\n  if (ON) { go() }\n}\n"
        self.assertEqual(dead.js_spans(conditional_exit), [])
        self.assertEqual(dead.js_spans(reassigned), [])

    def test_js_spans_cover_a_whole_else_if_chain(self) -> None:
        from steps.core.viewscan import dead

        text = "const T = true\nfunction f(x) {\n  if (T) {\n    a()\n  } else if (x) {\n    b()\n  } else {\n    c()\n  }\n  d()\n}\n"
        self.assertEqual([(s.start, s.end, s.gate) for s in dead.js_spans(text)], [(5, 9, 3)])

    def test_a_rule_in_a_commented_block_is_dead_with_its_gate_line(self) -> None:
        rules, _groups = rules_in(REPO / "tests" / "fixtures" / "dead-code")
        commented = [r for r in rules if r["source"].startswith("xp/") and r["expression"].count("paid")]
        self.assertEqual(len(commented), 1)
        self.assertTrue(commented[0]["dead"])
        self.assertEqual(commented[0]["deadAt"], "xp/src/main/resources/site/parts/mini-dead/mini-dead.html:2")
        self.assertEqual(commented[0]["deadReason"], "html-comment")

    def test_a_rule_behind_a_constant_gate_is_dead_and_the_gate_is_not(self) -> None:
        rules, _groups = rules_in(REPO / "tests" / "fixtures" / "dead-code")
        by_expr = {r["expression"]: r for r in rules if r["source"].startswith("web/")}
        late = by_expr["booking.status === 'late'"]
        paid = by_expr["booking.status === 'paid' && booking.total > 500"]
        live = by_expr["booking.total > 500"]
        self.assertEqual((late["deadAt"], paid["deadAt"]), ("web/src/Gated.tsx:7", "web/src/Gated.tsx:14"))
        self.assertEqual(paid["deadReason"], "DISABLED is always true")
        self.assertNotIn("dead", live)
        self.assertNotIn("dead", by_expr["!(DISABLED)"])

    def test_live_rules_carry_no_dead_flag(self) -> None:
        rules, _groups = rules_in(MINI)
        self.assertFalse(any(r.get("dead") for r in rules))


class UnreferencedTests(unittest.TestCase):
    def test_an_exported_lib_function_without_callers_marks_the_rules_inside_it(self) -> None:
        import json

        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw)
            (source / "graft/.graph").mkdir(parents=True)
            nodes = [
                {"id": "a/lib/x.js#used", "name": "used", "kind": "function", "path": "a/lib/x.js",
                 "span": "L1-L5", "exported": True},
                {"id": "a/lib/x.js#orphan", "name": "orphan", "kind": "function", "path": "a/lib/x.js",
                 "span": "L7-L12", "exported": True},
                {"id": "a/site/p.js#get", "name": "get", "kind": "function", "path": "a/site/p.js",
                 "span": "L1-L9", "exported": True},
            ]
            edges = [
                {"source": "a/site/p.js", "target": "a/lib/x.js#used", "relation": "calls"},
                {"source": "a/lib/x.js", "target": "a/lib/x.js#orphan", "relation": "contains"},
            ]
            (source / "graft/.graph/wiring.json").write_text(json.dumps({"nodes": nodes, "edges": edges}))
            found = view_rules.unreferenced_functions(source)
            self.assertEqual([f["name"] for f in found], ["orphan"])
            rules = [{"source": "a/lib/x.js:9"}, {"source": "a/lib/x.js:3"}, {"source": "a/lib/y.js:9"}]
            view_rules.mark_unreferenced(rules, found)
            self.assertEqual([bool(r.get("unreferenced")) for r in rules], [True, False, False])

    def test_without_a_graft_index_nothing_is_marked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            self.assertEqual(view_rules.unreferenced_functions(Path(raw)), [])


class LiteralHyphenTests(unittest.TestCase):
    def test_a_hyphen_inside_a_string_literal_is_kept(self) -> None:
        self.assertEqual(ex.shape("type == 'booking-contact'"), '$type == "booking-contact"')
        self.assertEqual(ex.shape("type == `pre-paid`"), '$type == "pre-paid"')
        self.assertEqual(ex.literals("type == `pre-${kind}`"), [])
        self.assertEqual(ex.shape("a-b > 3 && x == 'pre-paid'"), '$a - $b > 3 && $x == "pre-paid"')


class ServerRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import shutil

        cls._tmp = tempfile.TemporaryDirectory()
        source = Path(cls._tmp.name) / "legacy"
        shutil.copytree(REPO / "tests" / "fixtures" / "enonic-mini", source)
        shutil.copytree(REPO / "tests" / "fixtures" / "server-rules", source, dirs_exist_ok=True)
        lib = source / "xp/src/main/resources/lib"
        (lib / "vendor.min.js").write_text("if (a.status === 'x' && b.price > 1) { go() }\n", encoding="utf-8")
        cls.templates = scan(source)
        cls.rules = view_rules.build_rules(cls.templates, [], [], {})
        validate(cls.templates, "templates", what="templates.json")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _server(self) -> dict[str, dict]:
        return {r["expression"]: r for r in self.rules if r["scope"] == "server"}

    def test_status_comparison_role_check_and_amount_arithmetic_are_server_rules(self) -> None:
        rules = self._server()
        gate = rules["booking.status === STATUS_OPEN && Auth.hasRole('role:system.admin')"]
        self.assertEqual((gate["effect"], gate["kind"], gate["bucket"]), ("authorize", "authorization", "business"))
        deposit = rules["total * DEPOSIT_RATE"]
        self.assertEqual((deposit["effect"], deposit["kind"]), ("compute", "calculation"))
        self.assertEqual(deposit["source"], "xp/src/main/resources/lib/mini-pricing.js:7")
        self.assertIn("booking.dueDate < now", rules)

    def test_a_status_only_comparison_is_a_lifecycle_rule(self) -> None:
        from steps.core.viewscan import server

        found = server.scan("if (booking.status === 'paid') { x() }\nif (a.name === 'b') { y() }\n")
        self.assertEqual([(p["expr"], p["effect"]) for p in found], [("booking.status === 'paid'", "transition")])
        rule = view_rules.build_rules(
            {"files": [], "controllers": [], "server": [{"path": "lib/x.js", "predicates": found}], "coverage": {}},
            [], [], {},
        )[0]
        self.assertEqual((rule["kind"], rule["scope"], rule["bucket"]), ("lifecycle", "server", "business"))

    def test_view_rules_say_so_and_vendored_minified_files_are_skipped(self) -> None:
        self.assertTrue(all(r["scope"] in ("view", "server") for r in self.rules))
        self.assertFalse(any("vendor.min.js" in r["source"] for r in self.rules))

    def test_a_dead_server_branch_is_marked(self) -> None:
        from steps.core.viewscan import server

        text = "const OFF = true\nfunction f(b) {\n  if (OFF) return 1\n  if (b.status === 'x') { go() }\n}\n"
        found = server.scan(text)
        dead.mark(found, dead.js_spans(text), "lib/f.js")
        self.assertEqual(found[0]["deadAt"], "lib/f.js:3")
