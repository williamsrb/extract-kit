"""enonic.integrations harvest + read-only Swagger UI."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from steps.enonic.integrations import spec_js_body
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
