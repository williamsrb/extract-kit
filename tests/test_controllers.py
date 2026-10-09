"""enonic.controllers: regex scan facts with file:line, behavior on surfaces, inbound/outbound ops."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from extractkit_cli.schema import validate
from steps.enonic.controllers import (
    collect_controllers,
    http_requests,
    scan_text,
    strip_comments,
)
from tests.support import FIXTURE, STATIC_UNTIL, copy_fixture, run, sidecar_run_dir


class ScanTextTests(unittest.TestCase):
    def test_comments_never_report_but_urls_in_strings_survive(self) -> None:
        text = (
            "// const a = require('/lib/xp/content');\n"
            "/* b.query({ query: 'x' }) */\n"
            "const u = 'https://example.test/x'; // trailing\n"
        )
        stripped = strip_comments(text)
        self.assertNotIn("require", stripped)
        self.assertIn("https://example.test/x", stripped)
        self.assertEqual(stripped.count("\n"), text.count("\n"))
        self.assertEqual(scan_text(text)["imports"], [])

    def test_destructured_require_and_bare_calls(self) -> None:
        facts = scan_text(
            "const {\n  query,\n  get: fetch,\n} = require('/lib/xp/content');\n"
            "query({ count: 1 });\nfetch({ key: 'a' });\nmap.get('k');\n"
        )
        self.assertEqual(facts["imports"][0]["line"], 1)
        self.assertEqual(
            [(c["call"], c["line"]) for c in facts["calls"]],
            [("query", 5), ("get", 6)],
        )

    def test_es_import_forms(self) -> None:
        facts = scan_text(
            "import * as portal from '/lib/xp/portal';\n"
            "import thymeleaf from '/lib/thymeleaf';\n"
            "import { a, b as c } from '/lib/xp/node';\n"
            "import local from './local';\n"
        )
        self.assertEqual(
            [(i["module"], i.get("alias")) for i in facts["imports"]],
            [("/lib/xp/portal", "portal"), ("/lib/thymeleaf", "thymeleaf"), ("/lib/xp/node", None)],
        )
        self.assertEqual(facts["imports"][2]["names"][1], {"name": "b", "local": "c"})

    def test_object_of_requires_and_import_type(self) -> None:
        facts = scan_text(
            "var libs = {\n  content: require('/lib/xp/content'),\n"
            "  thymeleaf: require('/lib/thymeleaf'),\n};\n"
            "import type { Content } from '/lib/xp/content';\n"
            "libs.content.query({ count: 1 });\nreturn libs.thymeleaf.render(v, {});\n"
        )
        self.assertEqual(
            [(i["module"], i.get("alias"), i["line"]) for i in facts["imports"]],
            [("/lib/xp/content", "libs.content", 2), ("/lib/thymeleaf", "libs.thymeleaf", 3),
             ("/lib/xp/content", None, 5)],
        )
        self.assertEqual(
            [(c["call"], c["line"]) for c in facts["calls"]],
            [("libs.content.query", 6), ("libs.thymeleaf.render", 7)],
        )
        self.assertEqual([v["via"] for v in facts["views"]], ["libs.thymeleaf.render"])

    def test_concatenated_query_values_are_not_literals(self) -> None:
        facts = scan_text(
            "q({ query: \"_path LIKE '\" + p + \"'\", contentTypes: [app.name + ':a', 'x:y'] });\n"
        )
        self.assertEqual([(r["field"], r["value"]) for r in facts["queries"]], [("contentTypes", "x:y")])

    def test_helper_script_in_a_descriptor_folder_is_not_a_controller(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            part = next(source.rglob("site/parts/mini-part"))
            (part / "helpers.js").write_text("exports.x = 1;\n", encoding="utf-8")
            files = [r["file"] for r in collect_controllers(source) if r["kind"] == "part"]
            self.assertEqual([f.rsplit("/", 1)[-1] for f in files], ["mini-part.js"])

    def test_queries_skip_dynamic_template_literals(self) -> None:
        facts = scan_text(
            "q({ query: `type = '${t}'`, contentTypes: ['a:b', \"a:c\"] });\n"
            "q({ query: `fixed = 1` });\n"
        )
        values = [(r["field"], r["value"], r["line"]) for r in facts["queries"]]
        self.assertEqual(values, [
            ("contentTypes", "a:b", 1), ("contentTypes", "a:c", 1), ("query", "fixed = 1", 2),
        ])

    def test_export_forms(self) -> None:
        facts = scan_text(
            "exports.get = f;\nexports.helper = g;\n"
            "export async function post() {}\nexport const handleError = () => 1;\n"
            "export { run }\n"
        )
        self.assertEqual(
            [(m["name"], m["line"]) for m in facts["methods"]],
            [("get", 1), ("post", 3), ("handleError", 4), ("run", 5)],
        )

    def test_config_i18n_and_listener_facts(self) -> None:
        facts = scan_text(
            "const e = require('/lib/xp/event');\n"
            "e.listener({\n  type: 'node.*',\n});\n"
            "localize({\n  key: 'a.b',\n});\n"
            "app.config['x'] + app.config.y;\n"
        )
        self.assertEqual(facts["listeners"], [{"type": "node.*", "line": 3}])
        self.assertEqual(facts["i18n"], [{"key": "a.b", "line": 6}])
        self.assertEqual([(c["key"], c["line"]) for c in facts["configKeys"]], [("x", 8), ("y", 8)])


class HttpRequestTests(unittest.TestCase):
    def test_literal_and_expression_urls(self) -> None:
        text = (
            "const http = require('/lib/http-client');\n"
            "http.request({ url: 'https://a.example.test/x', method: 'GET' });\n"
            "http.request({\n  url: base + '/y',\n  headers: { a: 'b, c' },\n});\n"
        )
        self.assertEqual(http_requests(text), [
            {"line": 2, "url": "https://a.example.test/x", "method": "get"},
            {"line": 3, "urlExpr": "base + '/y'"},
        ])


class FixtureTests(unittest.TestCase):
    def test_fixture_controllers(self) -> None:
        rows = {r["file"].rsplit("resources/", 1)[1]: r for r in collect_controllers(FIXTURE.resolve())}
        self.assertEqual(
            sorted(rows),
            [
                "admin/tools/mini-tool/mini-tool.js",
                "cron/mini-cron/index.js",
                "error/error.js",
                "idprovider/idprovider.js",
                "main.js",
                "services/mini-script-only/mini-script-only.js",
                "services/mini-service/mini-service.js",
                "site/error/error.js",
                "site/filters/mini-filter.js",
                "site/pages/mini-page/mini-page.ts",
                "site/parts/mini-part/mini-part.js",
                "site/processors/mini-processor.js",
                "webapp/webapp.js",
            ],
        )
        part = rows["site/parts/mini-part/mini-part.js"]
        self.assertEqual(part["kind"], "part")
        self.assertEqual(part["app"], "com.example.mini")
        self.assertEqual(
            [(c["call"], c["line"]) for c in part["calls"]],
            [("contentLib.query", 7), ("i18n.localize", 12), ("thymeleaf.render", 14)],
        )
        self.assertEqual(part["i18n"], [{"key": "mini.title", "line": 12}])
        self.assertEqual({k["key"] for k in part["configKeys"]}, {"miniMode", "fallback"})
        self.assertNotIn("remove", json.dumps(part))
        self.assertEqual(rows["main.js"]["listeners"], [{"type": "node.pushed", "line": 5}, {"type": "custom.booking.paid", "line": 11, "calls": ["Booking.sweep"]}])


class RequestFactsTests(unittest.TestCase):
    def test_inputs_come_from_params_body_headers_and_cookies(self) -> None:
        facts = scan_text(
            "exports.post = function (req) {\n"
            "  const id = req.params.id;\n"
            "  const mode = req.params['mode'];\n"
            "  const body = JSON.parse(req.body);\n"
            "  const amount = body.amount + body['currency'];\n"
            "  const { name, city: town } = JSON.parse(req.body);\n"
            "  return req.headers['X-Key'] + req.cookies.sid;\n"
            "};\n"
        )
        got = [(i["source"], i["name"], i["line"]) for i in facts["inputs"]]
        self.assertEqual(got, [
            ("param", "id", 2), ("param", "mode", 3), ("body", "amount", 5), ("body", "currency", 5),
            ("body", "city", 6), ("body", "name", 6), ("cookie", "sid", 7), ("header", "X-Key", 7),
        ])

    def test_aliases_of_params_and_body_and_a_whole_params_hand_over(self) -> None:
        facts = scan_text(
            "exports.post = function (req) {\n"
            "  const reqParams = req.params || {}\n"
            "  const jsonBody = req.body || '{}'\n"
            "  const data = JSON.parse(jsonBody)\n"
            "  const other = JSON.parse(unrelated)\n"
            "  go(req.params)\n"
            "  return reqParams.callback + data.amount + other.bad\n"
            "}\n"
        )
        got = [(i["source"], i["name"], i["line"]) for i in facts["inputs"]]
        self.assertEqual(got, [("param", "*", 6), ("body", "amount", 7), ("param", "callback", 7)])

    def test_a_body_key_written_not_read_is_not_an_input(self) -> None:
        facts = scan_text("const b = JSON.parse(req.body);\nb.seen = true;\nreturn b.real;\n")
        self.assertEqual([i["name"] for i in facts["inputs"]], ["real"])

    def test_responses_record_literal_status_redirect_and_content_type(self) -> None:
        facts = scan_text(
            "return { status: 404 };\n"
            "return { contentType: 'application/json', status: 200 };\n"
            "return { redirect: '/en/thanks' };\n"
            "return portal.redirect(url);\n"
            "return { status: code };\n"
        )
        got = [(r["kind"], r["value"], r["line"]) for r in facts["responses"]]
        self.assertEqual(got, [
            ("status", "404", 1), ("contentType", "application/json", 2), ("status", "200", 2),
            ("redirect", "/en/thanks", 3), ("redirect", None, 4),
        ])

    def test_auth_signals_and_elevation(self) -> None:
        facts = scan_text(
            "if (!Auth.hasRole('role:system.admin')) return { status: 403 };\n"
            "const u = Auth.getUser();\n"
            "Context.run({ principals: ['role:system.admin', 'role:su'], repository: 'r' }, f);\n"
            "Context.run({ user: { login: 'su', idProvider: 'system' } }, f);\n"
            "// Auth.hasRole('role:commented')\n"
        )
        got = [(a["kind"], a["value"], a["line"]) for a in facts["auth"]]
        self.assertEqual(got, [
            ("role-check", "role:system.admin", 1), ("user-check", "getUser", 2),
            ("elevated", "role:su", 3), ("elevated", "role:system.admin", 3),
            ("elevated", "user:su", 4),
        ])

    def test_listener_rows_record_the_functions_the_callback_calls(self) -> None:
        facts = scan_text(
            "const event = require('/lib/xp/event');\n"
            "const Booking = require('/lib/booking');\n"
            "event.listener({\n  type: 'custom.paid',\n  callback: function (e) {\n"
            "    Booking.confirm(e);\n  },\n});\n"
        )
        self.assertEqual(facts["listeners"], [
            {"type": "custom.paid", "line": 4, "calls": ["Booking.confirm"]},
        ])


class SidecarTests(unittest.TestCase):
    def _static(self, parent: Path) -> tuple[Path, Path]:
        source = copy_fixture(parent)
        result = run("run", "--profile", "enonic", "--source", str(source), *STATIC_UNTIL)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return source, sidecar_run_dir(source)

    def test_controllers_json_validates_and_behavior_is_attached(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            _source, out = self._static(Path(raw))
            payload = json.loads((out / "inventory/controllers.json").read_text())
            validate(payload, "controllers")
            project = json.loads((out / "map/project-map.json").read_text())
            by_id = {s["id"]: s for s in project["surfaces"]}
            behavior = by_id["com.example.mini:part:mini-part"]["behavior"]
            self.assertTrue(behavior["file"].endswith("mini-part.js"))
            self.assertEqual(behavior["i18n"][0]["key"], "mini.title")
            self.assertNotIn("behavior", by_id["com.example.mini:macro:mini-macro"])
            components = json.loads((out / "map/component-map.json").read_text())
            validate(components, "component-map")

    def test_inbound_service_uses_exported_methods(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            _source, out = self._static(Path(raw))
            spec = yaml.safe_load((out / "integrations/openapi.yaml").read_text())
            item = spec["paths"]["/_/service/com.example.mini/mini-service"]
            self.assertEqual(list(item), ["get", "post"])
            self.assertTrue(item["get"]["x-source"][0].endswith("mini-service.js:4"))

    def test_script_only_service_is_an_inbound_operation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            _source, out = self._static(Path(raw))
            spec = yaml.safe_load((out / "integrations/openapi.yaml").read_text())
            item = spec["paths"]["/_/service/com.example.mini/mini-script-only"]
            self.assertEqual(list(item), ["post"])
            self.assertTrue(item["post"]["x-source"][0].endswith("mini-script-only.js:1"))

    def test_outbound_operation_has_literal_url_and_method(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            _source, out = self._static(Path(raw))
            spec = yaml.safe_load((out / "integrations/openapi.yaml").read_text())
            op = spec["paths"]["/outbound/mini-http"]["get"]
            self.assertEqual(op["x-url"], "https://api.example.test/v1")
            self.assertTrue(op["x-source"][0].endswith("mini-http.js:4"))

    def test_all_beside_post_takes_the_next_free_method(self) -> None:
        from steps.enonic.integrations import harvest_inbound

        controllers = [{
            "kind": "service", "app": "com.example.mini", "name": "mini-service", "file": "s.js",
            "methods": [{"name": "post", "line": 2}, {"name": "all", "line": 5}],
        }]
        ops = [o for o in harvest_inbound(FIXTURE.resolve(), controllers) if o["path"].endswith("/mini-service")]
        self.assertEqual(
            sorted((o["method"], o.get("x-exported-method")) for o in ops), [("get", "all"), ("post", None)],
        )

    def test_service_without_controllers_json_falls_back_to_post(self) -> None:
        from steps.enonic.integrations import build_openapi

        spec = build_openapi(FIXTURE.resolve(), "t", None)
        self.assertEqual(list(spec["paths"]["/_/service/com.example.mini/mini-service"]), ["post"])


if __name__ == "__main__":
    unittest.main()
