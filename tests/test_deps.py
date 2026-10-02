"""Dependency probes: ok, MISSING, BROKEN and skipped, on a fake PATH of stubs."""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from extractkit_cli import deps, manifest
from extractkit_cli.errors import ExtractkitError
from extractkit_cli.schema import validate


def _stub(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def _profile(*entries: dict) -> dict:
    return {"name": "t", "pipeline": ["a"], "adapters": {}, "deps": list(entries)}


class DepsProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.bin = Path(tmp.name)
        _stub(self.bin, "healthy", "exit 0")
        _stub(self.bin, "broken", "echo 'boom: no environment' >&2\nexit 1")
        _stub(self.bin, "tracey", (
            "echo 'Traceback (most recent call last):' >&2\n"
            "echo '  File \"x\", line 1' >&2\n"
            "echo \"ModuleNotFoundError: No module named 'x'\" >&2\nexit 1"
        ))
        _stub(self.bin, "silent", "exit 3")
        _stub(self.bin, "hangs", f"exec {shutil.which('sleep')} 5")
        patcher = mock.patch.dict(os.environ, {"PATH": str(self.bin)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _rows(self, *entries: dict) -> dict:
        return {r.name: r for r in deps.check_deps(_profile(*entries))}

    def test_four_states(self) -> None:
        rows = self._rows(
            {"provides": ["healthy"], "probe": ["healthy"]},
            {"provides": ["broken"], "probe": ["broken"]},
            {"provides": ["absent"]},
            {"provides": ["absent-opt"], "optional": True},
        )
        self.assertEqual(rows["healthy"].state, "ok")
        self.assertEqual(rows["broken"].state, "BROKEN")
        self.assertEqual(rows["broken"].detail, "boom: no environment")
        self.assertEqual(rows["absent"].state, "MISSING")
        self.assertEqual(rows["absent-opt"].state, "skipped")
        self.assertEqual(
            [name for name, r in rows.items() if r.failed], ["broken", "absent"],
        )

    def test_no_probe_means_on_path_is_enough(self) -> None:
        self.assertEqual(self._rows({"provides": ["broken"]})["broken"].state, "ok")

    def test_traceback_reports_its_last_line(self) -> None:
        row = self._rows({"provides": ["tracey"], "probe": ["tracey"]})["tracey"]
        self.assertEqual(row.detail, "ModuleNotFoundError: No module named 'x'")

    def test_silent_failure_names_the_exit_code(self) -> None:
        row = self._rows({"provides": ["silent"], "probe": ["silent"]})["silent"]
        self.assertEqual((row.state, row.detail), ("BROKEN", "probe exited 3"))

    def test_probe_timeout_is_broken(self) -> None:
        with mock.patch.object(deps, "PROBE_TIMEOUT", 0.2):
            row = self._rows({"provides": ["hangs"], "probe": ["hangs"]})["hangs"]
        self.assertEqual(row.state, "BROKEN")
        self.assertIn("timed out", row.detail)

    def test_optional_broken_is_shown_but_does_not_fail(self) -> None:
        row = self._rows(
            {"provides": ["broken"], "probe": ["broken"], "optional": True},
        )["broken"]
        self.assertEqual(row.state, "BROKEN")
        self.assertFalse(row.failed)

    def test_missing_required_names_install_hints(self) -> None:
        row = self._rows({"provides": ["absent"], "apt": "absent-pkg"})["absent"]
        self.assertIn("apt: absent-pkg", row.fix)

    def test_python_version_and_modules(self) -> None:
        rows = self._rows({
            "provides": ["healthy"],
            "python": ">=3.0",
            "python_modules": ["json", "no_such_module_xyz"],
        })
        self.assertEqual(rows["python"].state, "ok")
        self.assertEqual(rows["python:json"].state, "ok")
        self.assertEqual(rows["python:no_such_module_xyz"].state, "MISSING")
        too_new = self._rows({"provides": ["healthy"], "python": ">=99"})
        self.assertEqual(too_new["python"].state, "BROKEN")
        self.assertTrue(too_new["python"].failed)


class DepsCommandTests(unittest.TestCase):
    def _run(self, profile: dict, path: str) -> tuple[int, str]:
        out = io.StringIO()
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        bin_dir = Path(home.name) / ".local" / "bin"
        with (
            mock.patch.dict(os.environ, {"PATH": f"{path}{os.pathsep}{bin_dir}", "HOME": home.name}),
            mock.patch.object(manifest, "load", return_value=profile),
            contextlib.redirect_stdout(out),
        ):
            code = deps.cmd_deps(Namespace(profile="t", argv=["deps"], prog_display="x"))
        return code, out.getvalue()

    def test_required_broken_exits_1_and_optional_broken_exits_0(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            _stub(Path(raw), "broken", "echo nope >&2\nexit 1")
            required = _profile({"provides": ["broken"], "probe": ["broken"]})
            code, text = self._run(required, raw)
            self.assertEqual(code, 1)
            self.assertIn("BROKEN", text)
            self.assertIn("nope", text)
            optional = _profile(
                {"provides": ["broken"], "probe": ["broken"], "optional": True},
            )
            code, text = self._run(optional, raw)
            self.assertEqual(code, 0)
            self.assertIn("BROKEN", text)

    def test_missing_required_exits_1(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            code, text = self._run(_profile({"provides": ["absent"]}), raw)
        self.assertEqual(code, 1)
        self.assertIn("MISSING", text)


class DependencyRowTests(unittest.TestCase):
    def test_shipped_profiles_validate_and_core_rows_are_declared(self) -> None:
        for name in ("core", "enonic", "php"):
            validate(manifest.load(name), "profile", what=name)
        rows = {r["name"]: r for r in manifest.dependency_rows(manifest.load("enonic"))}
        self.assertTrue(rows["git"]["required"])
        self.assertEqual(rows["git"]["probe"], ["git", "--version"])
        for optional in ("graft", "serena", "graphify"):
            self.assertFalse(rows[optional]["required"])
            self.assertTrue(rows[optional]["probe"])
        self.assertEqual(rows["python3"]["python"], ">=3.12")
        self.assertEqual(rows["python3"]["python_modules"], ["yaml", "jsonschema"])
        self.assertIn("playwright-cli", rows)

    def test_schema_rejects_a_malformed_probe(self) -> None:
        profile = _profile({"provides": ["x"], "probe": "x --version"})
        with self.assertRaises(ExtractkitError):
            validate(profile, "profile", what="t")


if __name__ == "__main__":
    unittest.main()
