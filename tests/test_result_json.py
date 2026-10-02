"""US-002: every command prints one schema-valid JSON document with `--json`."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import jsonschema

from extractkit_cli import schema
from tests.support import build_sidecar, copy_fixture, run, sidecar_run_dir


def _validate(case: unittest.TestCase, result) -> dict:
    case.assertEqual(result.stdout.count("\n") > 0, True, result.stderr)
    doc = json.loads(result.stdout)
    jsonschema.validate(doc, schema.load_schema("result"))
    return doc


class EnvelopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.source, cls.out = build_sidecar(Path(cls._tmp.name))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _json(self, *args: str, code: int = 0) -> dict:
        result = run(*args, "--json", cwd=self.source)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        doc = _validate(self, result)
        self.assertEqual(doc["ok"], code == 0)
        self.assertEqual(doc["exit"], code)
        return doc

    def test_install(self) -> None:
        doc = self._json("install")
        self.assertIn("launcher extractkit", [r["name"] for r in doc["rows"]])
        self.assertEqual(doc["next_command"]["argv"][:2], ["extractkit", "doctor"])

    def test_deps(self) -> None:
        doc = self._json("deps", "--profile", "core")
        self.assertTrue(all("state" in r for r in doc["rows"]))
        self.assertIsNotNone(doc["next_command"])

    def test_doctor_with_source_reports_rows_and_a_failed_row_as_the_error(self) -> None:
        doc = self._json("doctor", "--profile", "enonic", "--source", ".", code=1)
        names = {r["name"]: r for r in doc["rows"]}
        self.assertEqual(names["serena onboarding"]["state"], "MISSING")
        self.assertEqual(doc["error"]["code"], "readiness_missing")
        self.assertTrue(doc["error"]["fix"])
        self.assertEqual(doc["source"], str(self.source))

    def test_context_run_status_resume(self) -> None:
        doc = self._json("context", "--source", ".")
        self.assertTrue(doc["sidecar"])
        self.assertEqual(doc["next_command"]["argv"][1], "run")
        doc = self._json("status", "--out", str(self.out))
        self.assertEqual(doc["sidecar"], str(self.out))
        self.assertIn(doc["phase"], {"cms", "agent", "check", None})
        doc = self._json("resume", "--source", ".", "--out", str(self.out), "--profile", "enonic", code=1)
        self.assertEqual(doc["command"], "resume")
        self.assertEqual(doc["error"]["code"], "missing_branch")

    def test_run_lists_what_it_wrote(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            result = run("run", "--source", ".", "--until", "static", "--json", cwd=source)
            doc = _validate(self, result)
            self.assertEqual(result.returncode, 0)
            self.assertTrue(doc["wrote"])
            self.assertEqual(doc["sidecar"], str(sidecar_run_dir(source)))
            self.assertEqual(doc["phase"], "cms")
            self.assertTrue(all(isinstance(t, str) for t in doc["next_command"]["argv"]))

    def test_check_clean(self) -> None:
        doc = self._json("check", "--out", str(self.out))
        self.assertEqual(doc["problems"], [])

    def test_agent_payloads_keep_their_keys_and_gain_the_envelope(self) -> None:
        listing = self._json("agent", "list", "--out", str(self.out))
        self.assertIsInstance(listing["next"], (str, type(None)))
        self.assertIsInstance(listing["tasks"], list)
        nxt = self._json("agent", "next", "--out", str(self.out))
        self.assertTrue(nxt["next"] is None or isinstance(nxt["next"], dict))
        self.assertIn("blocked", nxt)
        self.assertIn("pending", nxt)
        self.assertIsNotNone(nxt["next_command"])
        task = listing["tasks"][0]["id"]
        shown = self._json("agent", "show", task, "--out", str(self.out))
        self.assertIn("prompt", shown)
        self.assertIn("inputs", shown)


class FailureCodeTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.source = copy_fixture(self.tmp)

    def _error(self, *args: str, cwd: Path | None = None) -> dict:
        result = run(*args, "--json", cwd=cwd or self.source)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        doc = _validate(self, result)
        self.assertFalse(doc["ok"])
        self.assertTrue(doc["error"]["message"])
        return doc["error"]

    def test_no_source(self) -> None:
        error = self._error("run", "--source", "does-not-exist", "--until", "static")
        self.assertEqual(error["code"], "no_source")
        self.assertTrue(error["fix"])

    def test_production_host(self) -> None:
        error = self._error(
            "run", "--source", ".", "--branch", "draft", "--xp-host", "https://example.com",
            "--storage-state", "/dev/null",
        )
        self.assertEqual(error["code"], "production_host")

    def test_missing_branch_carries_a_runnable_fix_command(self) -> None:
        error = self._error("run", "--source", ".")
        self.assertEqual(error["code"], "missing_branch")
        self.assertIn("--branch draft", error["fix_command"])

    def test_no_stack_marker_and_multiple_stacks(self) -> None:
        empty = self.tmp / "empty"
        empty.mkdir()
        self.assertEqual(self._error("context", "--source", ".", cwd=empty)["code"], "no_stack_marker")
        both = self.tmp / "both"
        (both / "src/main/resources").mkdir(parents=True)
        (both / "src/main/resources/application.xml").write_text("<application/>")
        (both / "composer.json").write_text("{}")
        self.assertEqual(self._error("context", "--source", ".", cwd=both)["code"], "multiple_stacks")

    def test_check_failed_lists_the_problems(self) -> None:
        built = self.tmp / "built"
        built.mkdir()
        source, out = build_sidecar(built)
        (out / "business").mkdir(exist_ok=True)
        (out / "business" / "BUSINESS.md").write_text("# Business\n", encoding="utf-8")
        result = run("check", "--out", str(out), "--json", cwd=source)
        self.assertEqual(result.returncode, 1)
        doc = _validate(self, result)
        self.assertEqual(doc["error"]["code"], "check_failed")
        self.assertTrue(doc["problems"])

    def test_promote_refused_and_nothing_to_promote(self) -> None:
        self.assertEqual(self._error("promote", "--source", ".")["code"], "error")


if __name__ == "__main__":
    unittest.main()
