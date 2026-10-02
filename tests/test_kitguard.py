"""US-001: an extract command refuses to run from the kit workspace."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from extractkit_cli import cli, kitguard
from extractkit_cli.errors import ExtractkitError
from tests.support import FIXTURE, REPO, TEST_HOME, copy_fixture, run, run_checkout

MESSAGE = "extractkit runs from the legacy checkout, not from the kit repo"
INSTALL_ROOT = TEST_HOME / ".local" / "share" / "extractkit"


class RefusalTests(unittest.TestCase):
    def test_cwd_in_the_kit_checkout(self) -> None:
        result = run_checkout("run", "--source", str(FIXTURE), "--until", "static")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(MESSAGE, result.stderr)
        self.assertIn("cd into the legacy checkout", result.stderr)
        self.assertFalse((FIXTURE / ".extract").exists())

    def test_cwd_in_the_install_root(self) -> None:
        self.assertFalse((INSTALL_ROOT / "tests").exists())
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            result = run("run", "--source", str(source), "--until", "static", cwd=INSTALL_ROOT)
        self.assertEqual(result.returncode, 1)
        self.assertIn(MESSAGE, result.stderr)

    def test_source_in_the_kit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = run("run", "--source", str(FIXTURE), "--until", "static", cwd=Path(raw))
        self.assertEqual(result.returncode, 1)
        self.assertIn(MESSAGE, result.stderr)
        self.assertFalse((FIXTURE / ".extract").exists())

    def test_out_in_the_kit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            result = run("run", "--source", str(source), "--out", str(REPO / "x-out"), cwd=source)
        self.assertEqual(result.returncode, 1)
        self.assertIn(MESSAGE, result.stderr)
        self.assertFalse((REPO / "x-out").exists())

    def test_symlink_into_the_kit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            link = Path(raw) / "innocent"
            link.symlink_to(FIXTURE)
            result = run("run", "--source", str(link), "--until", "static", cwd=Path(raw))
        self.assertEqual(result.returncode, 1)
        self.assertIn(MESSAGE, result.stderr)

    def test_json_error_envelope(self) -> None:
        result = run_checkout("run", "--source", str(FIXTURE), "--until", "static", "--json")
        self.assertEqual(result.returncode, 1)
        doc = json.loads(result.stdout)
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["error"]["code"], "kit_workspace")
        self.assertIn("legacy checkout", doc["error"]["fix"])

    def test_agent_and_doctor_with_source_are_guarded(self) -> None:
        self.assertEqual(run_checkout("agent", "list").returncode, 1)
        self.assertEqual(run_checkout("doctor", "--profile", "enonic", "--source", ".").returncode, 1)


class ExemptTests(unittest.TestCase):
    def test_exempt_commands_run_from_the_kit(self) -> None:
        for args in (("install",), ("deps",), ("profile", "list"), ("--help",), ("doctor", "--profile", "enonic")):
            with self.subTest(args=args):
                result = run_checkout(*args)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_bare_invocation_prints_help(self) -> None:
        self.assertEqual(run_checkout().returncode, 0)

    def test_doctor_with_source_runs_from_the_checkout_being_extracted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            result = run("doctor", "--profile", "enonic", "--source", ".", cwd=source)
        self.assertNotIn(MESSAGE, result.stdout + result.stderr)
        self.assertIn("serena onboarding", result.stdout)


class GuardUnitTests(unittest.TestCase):
    def test_refuse_kit_by_cwd(self) -> None:
        args = cli.build_parser().parse_args(["agent", "list"])
        with mock.patch.object(kitguard, "cwd", return_value=REPO), \
                self.assertRaises(ExtractkitError) as caught:
            kitguard.refuse_kit(args)
        self.assertEqual(caught.exception.code, "kit_workspace")

    def test_a_folder_with_the_kit_markers_is_a_kit_tree(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fake = Path(raw)
            (fake / "extractkit_cli").mkdir()
            (fake / "extractkit_cli" / "cli.py").write_text("")
            (fake / "extractkit.yaml").write_text("name: x\n")
            (fake / "sub").mkdir()
            self.assertEqual(kitguard.kit_tree(fake / "sub"), fake.resolve())
            self.assertIsNone(kitguard.kit_tree(Path(raw).parent))


if __name__ == "__main__":
    unittest.main()
