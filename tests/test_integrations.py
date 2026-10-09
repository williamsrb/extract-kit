"""enonic.integrations harvest + read-only Swagger UI."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from steps.enonic.integrations import _auth_modes, spec_js_body
from tests.support import REPO, STATIC_UNTIL, copy_fixture, run, sidecar_run_dir


class SpecJsTests(unittest.TestCase):
    def test_body_is_json_assignment(self) -> None:
        raw = spec_js_body({"openapi": "3.1.0", "paths": {}})
        self.assertTrue(raw.startswith("window.EXTRACTKIT_SPEC = "))
        payload = json.loads(raw.split("=", 1)[1].strip().rstrip(";"))
        self.assertEqual(payload["openapi"], "3.1.0")

    def test_script_tag_is_escaped(self) -> None:
        raw = spec_js_body({"note": "</script>"})
        self.assertNotIn("</script>", raw)
        self.assertIn("\\u003c/script>", raw)


class SwaggerUiApplyTests(unittest.TestCase):
    def test_static_apply_writes_read_only_swagger_ui(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = copy_fixture(Path(tmp))
            result = run(
                "run", "--profile", "enonic", "--source", str(source),
                *STATIC_UNTIL,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            ui = sidecar_run_dir(source) / "integrations" / "swagger-ui"
            bundle = ui / "swagger-ui-bundle.js"
            self.assertTrue(bundle.is_file())
            self.assertGreater(bundle.stat().st_size, 100_000)
            html = (ui / "index.html").read_text(encoding="utf-8")
            self.assertIn("swagger-ui-bundle.js", html)
            self.assertNotIn("Loading ../openapi.yaml", html)
            init = (ui / "swagger-initializer.js").read_text(encoding="utf-8")
            self.assertIn("supportedSubmitMethods: []", init)
            self.assertIn("tryItOutEnabled: false", init)
            spec_js = (ui / "spec.js").read_text(encoding="utf-8")
            self.assertIn("window.EXTRACTKIT_SPEC", spec_js)
            self.assertIn("inbound_mini-service", spec_js)
            self.assertIn("outbound_mini-http", spec_js)
            self.assertIn("cdn.example.test", spec_js)
            vendor = (REPO / "templates" / "swagger-ui" / "VENDOR.txt").read_text(
                encoding="utf-8",
            )
            self.assertIn("5.30.2", vendor)


if __name__ == "__main__":
    unittest.main()


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from steps.enonic.controllers import collect_controllers
        from steps.enonic.integrations import build_openapi

        cls._tmp = tempfile.TemporaryDirectory()
        source = copy_fixture(Path(cls._tmp.name))
        shutil.copytree(REPO / "tests" / "fixtures" / "server-rules", source, dirs_exist_ok=True)
        cls.spec = build_openapi(source, "t", collect_controllers(source))
        (Path(cls._tmp.name) / "plain").mkdir()
        plain = copy_fixture(Path(cls._tmp.name) / "plain")
        cls.plain = build_openapi(plain, "t", collect_controllers(plain))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _post(self) -> dict:
        return self.spec["paths"]["/_/service/com.example.mini/mini-service"]["post"]

    def test_inbound_operations_list_inputs_as_parameters_and_body(self) -> None:
        post = self._post()
        params = {(p["in"], p["name"]) for p in post["parameters"]}
        self.assertEqual(params, {("query", "bookingId"), ("query", "mode"), ("header", "x-mini-token")})
        for p in post["parameters"]:
            self.assertRegex(p["x-source"], r"mini-service\.js:\d+$")
        fields = post["requestBody"]["content"]["application/json"]["schema"]["properties"]
        self.assertEqual(list(fields), ["amount"])

    def test_auth_block_names_the_role_or_none(self) -> None:
        self.assertEqual(self._post()["x-auth"]["modes"], ["role:system.admin"])
        self.assertEqual(self._post()["x-auth"]["scope"], "controller")
        self.assertRegex(self._post()["x-auth"]["x-source"][0], r"mini-service\.js:\d+$")
        script_only = self.spec["paths"]["/_/service/com.example.mini/mini-script-only"]
        self.assertEqual(next(iter(script_only.values()))["x-auth"]["modes"], ["none"])
        plain_post = self.plain["paths"]["/_/service/com.example.mini/mini-service"]["post"]
        self.assertEqual(plain_post["x-auth"]["modes"], ["authenticated"])

    def test_role_check_on_a_variable_is_not_none(self) -> None:
        self.assertEqual(_auth_modes([{"kind": "role-check", "value": None}]), ["role:<computed>"])

    def test_response_codes_come_from_literal_statuses(self) -> None:
        post = self._post()
        self.assertEqual(sorted(post["responses"]), ["200", "400", "403"])
        self.assertIn("application/json", post["responses"]["200"]["content"])

    def test_a_request_built_elsewhere_cites_the_call_line_not_the_require(self) -> None:
        from steps.enonic.integrations import harvest_outbound

        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw)
            lib = source / "lib"
            lib.mkdir()
            (lib / "pay.js").write_text(
                "const HttpClient = require('/lib/http-client')\n"
                "exports.go = function (requestObj) {\n"
                "  return HttpClient.request(requestObj)\n"
                "}\n",
                encoding="utf-8",
            )
            ops = harvest_outbound(source)
            self.assertEqual(ops[0]["x-source"], ["lib/pay.js:3"])
