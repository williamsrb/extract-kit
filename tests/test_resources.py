"""US-004: the resources file fills options at the `file` level and `doctor` probes it."""

from __future__ import annotations

import http.server
import json
import tempfile
import threading
import unittest
from pathlib import Path

import jsonschema
import yaml

from extractkit_cli import schema
from tests.support import copy_fixture, run


class _Handler(http.server.BaseHTTPRequestHandler):
    """Answers GET; POST is 501, so the Guillotine probe fails."""

    def do_GET(self) -> None:
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args: object) -> None:
        pass


class ResourcesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.source = copy_fixture(self.tmp)
        (self.source / ".serena" / "memories").mkdir(parents=True)
        (self.source / ".serena" / "project.yml").write_text("name: x\n")
        (self.source / ".serena" / "memories" / "m.md").write_text("x\n")
        (self.source / "graphify-out").mkdir()
        (self.source / "graphify-out" / "graph.json").write_text("{}")

    def _state(self, domain: str = "localhost") -> Path:
        path = self.tmp / "state.json"
        path.write_text(json.dumps({"cookies": [{"name": "s", "value": "v", "domain": domain, "path": "/"}]}))
        return path

    def _resources(self, data: dict) -> Path:
        path = self.tmp / "resources.yaml"
        path.write_text(yaml.safe_dump(data))
        return path

    def _doctor(self, resources: Path) -> tuple:
        result = run("doctor", "--profile", "enonic", "--source", ".", "--resources", str(resources), "--json",
                     cwd=self.source)
        doc = json.loads(result.stdout)
        jsonschema.validate(doc, schema.load_schema("result"))
        return result, {row["name"]: row for row in doc["rows"]}, doc

    def test_probes_report_each_declared_resource(self) -> None:
        host = f"http://localhost:{self.port}"
        resources = self._resources({
            "xp": {"host": host, "project": "en", "branch": "draft"},
            "auth": {"storage_state": str(self._state())},
        })
        result, rows, doc = self._doctor(resources)
        self.assertEqual(rows["xp host"]["state"], "ok", rows)
        self.assertEqual(rows["storage state"]["state"], "ok", rows)
        self.assertEqual(rows["guillotine"]["state"], "MISSING")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(doc["error"]["code"], "resource_unreachable")
        self.assertIn("xp", doc["error"]["fix"])

    def test_storage_state_without_a_cookie_for_the_host_is_missing(self) -> None:
        resources = self._resources({
            "xp": {"host": f"http://localhost:{self.port}"},
            "auth": {"storage_state": str(self._state("elsewhere.test"))},
        })
        _result, rows, _doc = self._doctor(resources)
        self.assertEqual(rows["storage state"]["state"], "MISSING")
        self.assertIn("no cookie for localhost", rows["storage state"]["detail"])

    def test_storage_state_contents_from_the_env_reach_the_probe(self) -> None:
        resources = self._resources({"xp": {"host": f"http://localhost:{self.port}"}})
        result = run("doctor", "--profile", "enonic", "--source", ".", "--resources", str(resources), "--json",
                     cwd=self.source, env={"EXTRACTKIT_STORAGE_STATE_JSON": self._state().read_text()})
        rows = {row["name"]: row for row in json.loads(result.stdout)["rows"]}
        self.assertEqual(rows["storage state"]["state"], "ok", rows)

    def test_no_xp_skips_the_cms_rows_without_failing(self) -> None:
        resources = self._resources({"agent": {"cli": "claude"}})
        _result, rows, _doc = self._doctor(resources)
        for name in ("xp host", "guillotine", "storage state"):
            self.assertEqual(rows[name]["state"], "skipped", name)
            self.assertIn("offline run", rows[name]["detail"])
        self.assertNotIn("MISSING", {r["state"] for n, r in rows.items() if n.startswith(("xp", "guill", "storage"))})

    def test_an_unknown_agent_cli_is_a_missing_row(self) -> None:
        resources = self._resources({"agent": {"cli": "no-such-agent"}})
        _result, rows, _doc = self._doctor(resources)
        self.assertEqual(rows["agent cli"]["state"], "MISSING")
        self.assertIn("claude", rows["agent cli"]["fix"])

    def test_a_production_host_is_refused(self) -> None:
        resources = self._resources({"xp": {"host": "https://example.com"}})
        result = run("doctor", "--profile", "enonic", "--source", ".", "--resources", str(resources), "--json",
                     cwd=self.source)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "production_host")

    def test_a_production_guillotine_is_refused_before_cookies_are_sent(self) -> None:
        resources = self._resources({
            "xp": {"host": f"http://localhost:{self.port}", "guillotine": "https://example.com/graphql"},
            "auth": {"storage_state": str(self._state())},
        })
        result = run("doctor", "--profile", "enonic", "--source", ".", "--resources", str(resources), "--json",
                     cwd=self.source)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "production_host")

    def test_agent_api_key_is_checked_for_presence_only(self) -> None:
        resources = self._resources({"agent": {"api_key_env": "EXTRACTKIT_TEST_KEY"}})
        result = run("doctor", "--profile", "enonic", "--source", ".", "--resources", str(resources), "--json",
                     cwd=self.source, env={"EXTRACTKIT_TEST_KEY": "sk-never-printed"})
        self.assertNotIn("sk-never-printed", result.stdout + result.stderr)
        rows = {r["name"]: r for r in json.loads(result.stdout)["rows"]}
        self.assertEqual(rows["agent api key"]["state"], "ok")
        result = run("doctor", "--profile", "enonic", "--source", ".", "--resources", str(resources), "--json",
                     cwd=self.source)
        rows = {r["name"]: r for r in json.loads(result.stdout)["rows"]}
        self.assertEqual(rows["agent api key"]["state"], "MISSING")

    def test_schema_rejects_unknown_keys_and_a_database(self) -> None:
        for bad in ({"sqlite": {"path": "x.db"}}, {"xp": {"hots": "x"}}, {"agent": {"permissions": "yolo"}}):
            with self.subTest(bad=bad):
                result = run("doctor", "--profile", "enonic", "--source", ".", "--resources",
                             str(self._resources(bad)), "--json", cwd=self.source)
                self.assertEqual(result.returncode, 1)
                self.assertIn("resources", json.loads(result.stdout)["error"]["message"])

    def test_file_values_fill_defaults_below_cli_and_env(self) -> None:
        resources = self._resources({
            "xp": {"host": "http://localhost:9", "project": "en", "branch": "draft", "cms_keys": ["/a"]},
        })
        base = ["run", "--source", ".", "--until", "static", "--resources", str(resources), "--json"]
        result = run(*base, cwd=self.source)
        config = {r["name"]: r for r in json.loads(result.stdout)["config"]}
        self.assertEqual(config["--branch"]["origin"], "file")
        self.assertEqual(config["--branch"]["value"], "draft")
        self.assertEqual(config["--cms-key"]["value"], ["/a"])
        result = run(*base, "--branch", "master", cwd=self.source)
        config = {r["name"]: r for r in json.loads(result.stdout)["config"]}
        self.assertEqual((config["--branch"]["origin"], config["--branch"]["value"]), ("cli", "master"))
        result = run(*base, cwd=self.source, env={"EXTRACTKIT_BRANCH": "master"})
        config = {r["name"]: r for r in json.loads(result.stdout)["config"]}
        self.assertEqual((config["--branch"]["origin"], config["--branch"]["value"]), ("env", "master"))
        self.assertEqual(config["--xp-host"]["origin"], "file")

    def test_resources_env_var(self) -> None:
        resources = self._resources({"xp": {"branch": "draft"}})
        result = run("run", "--source", ".", "--until", "static", "--json", cwd=self.source,
                     env={"EXTRACTKIT_RESOURCES": str(resources)})
        config = {r["name"]: r for r in json.loads(result.stdout)["config"]}
        self.assertEqual(config["--branch"]["origin"], "file")


if __name__ == "__main__":
    unittest.main()
