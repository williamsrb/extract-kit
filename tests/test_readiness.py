"""Target readiness (Serena, Graphify, graft) and `doctor --source`."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from extractkit_cli import readiness
from tests.support import STATIC_UNTIL, copy_fixture, run, sidecar_run_dir


def _states(source: Path) -> dict[str, str]:
    return {r.name: r.state for r in readiness.check_source(source)}


def _onboard(source: Path) -> None:
    (source / ".serena" / "memories").mkdir(parents=True)
    (source / ".serena" / "project.yml").write_text("project_name: x\n")
    (source / ".serena" / "memories" / "suggested_commands.md").write_text("# x\n")


def _index(source: Path) -> None:
    (source / "graphify-out").mkdir()
    (source / "graphify-out" / "graph.json").write_text("{}")


class CheckSourceTests(unittest.TestCase):
    def test_empty_source_fails_serena_and_graphify_and_warns_on_graft(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            rows = {r.name: r for r in readiness.check_source(Path(raw))}
        self.assertEqual(
            {n: r.state for n, r in rows.items()},
            {"serena onboarding": "MISSING", "graphify index": "MISSING", "graft index": "warn"},
        )
        self.assertTrue(rows["serena onboarding"].failed)
        self.assertTrue(rows["graphify index"].failed)
        self.assertFalse(rows["graft index"].failed)
        self.assertEqual(
            rows["serena onboarding"].fix,
            f"open {raw} in an agent with Serena and run onboarding",
        )
        self.assertEqual(rows["graphify index"].fix, f"run `/graphify .` in {raw}")
        self.assertEqual(rows["graft index"].fix, f"run `graft build` in {raw}")

    def test_serena_needs_project_yml_and_a_memory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw)
            (source / ".serena" / "memories").mkdir(parents=True)
            (source / ".serena" / "project.yml").write_text("x: 1\n")
            self.assertEqual(_states(source)["serena onboarding"], "MISSING")
            self.assertIsNone(readiness.serena_pointer(source))
            (source / ".serena" / "memories" / "m.md").write_text("# m\n")
            self.assertEqual(_states(source)["serena onboarding"], "ok")
            self.assertEqual(readiness.serena_pointer(source), str(source / ".serena"))

    def test_graphify_and_graft_present(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw)
            _index(source)
            (source / "graft").mkdir()
            states = _states(source)
        self.assertEqual(states["graphify index"], "ok")
        self.assertEqual(states["graft index"], "ok")


class DoctorSourceTests(unittest.TestCase):
    def test_unprepared_source_exits_1_with_fix_lines_and_next(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            result = run("doctor", "--profile", "enonic", "--source", str(source))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"fix: open {source} in an agent with Serena", result.stdout)
        self.assertIn(f"fix: run `/graphify .` in {source}", result.stdout)
        self.assertIn(f"fix: run `graft build` in {source}", result.stdout)
        self.assertIn("doctor: 2 problem(s).", result.stdout)
        self.assertIn("and run onboarding, then re-run:", result.stdout)
        self.assertIn("$ ./extractkit doctor --profile enonic --source", result.stdout)

    def test_graft_missing_alone_is_a_warning(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            _onboard(source)
            _index(source)
            result = run("doctor", "--profile", "enonic", "--source", str(source))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("warn", result.stdout)
        self.assertIn("doctor: clean", result.stdout)
        self.assertIn("--until static", result.stdout)

    def test_missing_source_directory_is_an_error(self) -> None:
        result = run("doctor", "--source", "/nowhere/at/all")
        self.assertEqual(result.returncode, 1)
        self.assertIn("is not a directory", result.stderr)


class RunWiringTests(unittest.TestCase):
    def _manifest(self, source: Path) -> dict:
        result = run("run", "--profile", "enonic", "--source", str(source), *STATIC_UNTIL)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        out = sidecar_run_dir(source)
        return yaml.safe_load((out / "MANIFEST.yaml").read_text())

    def test_skip_fixes_reuse_the_readiness_strings(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            payload = self._manifest(source)
        skips = {row["step"]: row["fix"] for row in payload["skips"]}
        self.assertEqual(skips["map.code"], readiness.GRAFT_FIX.format(source=source))
        self.assertEqual(skips["map.semantic"], readiness.GRAPHIFY_FIX.format(source=source))
        self.assertIsNone(payload["maps"]["serena"])

    def test_manifest_points_at_serena_when_onboarded(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            _onboard(source)
            payload = self._manifest(source)
        self.assertEqual(payload["maps"]["serena"], str(source.resolve() / ".serena"))


if __name__ == "__main__":
    unittest.main()
