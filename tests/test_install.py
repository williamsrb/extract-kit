"""`extractkit install` and the install rows preflight prints."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from extractkit_cli import install
from tests.support import REPO, TEST_HOME, run


class InstallTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        bin_dir = self.home / ".local" / "bin"
        patcher = mock.patch.dict(os.environ, {"PATH": str(bin_dir)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _rows(self, **kwargs: object) -> dict:
        return {r.name: r for r in install.install(home=self.home, **kwargs)}

    def test_links_cli_and_every_skill_back_into_the_kit(self) -> None:
        rows = self._rows()
        self.assertTrue(all(r.state == "ok" for r in rows.values()), rows)
        cli = self.home / ".local" / "bin" / "extractkit"
        self.assertEqual(cli.resolve(), (REPO / "extractkit").resolve())
        skills = sorted(p.name for p in (REPO / "skills").iterdir() if (p / "SKILL.md").is_file())
        self.assertIn("extract-legacy", skills)
        for name in skills:
            agents = self.home / ".agents" / "skills" / name
            claude = self.home / ".claude" / "skills" / name
            self.assertEqual(Path(os.readlink(agents)), REPO / "skills" / name)
            self.assertEqual(Path(os.readlink(claude)), agents)
            self.assertTrue((claude / "SKILL.md").is_file())

    def test_second_run_is_a_no_op(self) -> None:
        self._rows()
        rows = self._rows()
        self.assertTrue(all("(linked)" not in r.detail for r in rows.values()))

    def test_foreign_symlink_needs_force_and_real_file_is_never_touched(self) -> None:
        cli = self.home / ".local" / "bin" / "extractkit"
        cli.parent.mkdir(parents=True)
        cli.symlink_to("/somewhere/else")
        row = self._rows()["link extractkit"]
        self.assertEqual(row.state, "BROKEN")
        self.assertTrue(row.failed)
        self.assertIn("--force", row.fix)
        self.assertEqual(self._rows(force=True)["link extractkit"].state, "ok")
        self.assertEqual(cli.resolve(), (REPO / "extractkit").resolve())

        cli.unlink()
        cli.write_text("mine\n")
        row = self._rows(force=True)["link extractkit"]
        self.assertEqual(row.state, "BROKEN")
        self.assertEqual(cli.read_text(), "mine\n")

    def test_claude_skills_linked_to_agents_skills_is_left_alone(self) -> None:
        agents = self.home / ".agents" / "skills"
        agents.mkdir(parents=True)
        (self.home / ".claude").mkdir()
        (self.home / ".claude" / "skills").symlink_to(agents)
        for force in (False, True):
            rows = self._rows(force=force)
            self.assertTrue(all(r.state == "ok" for r in rows.values()), rows)
        self.assertEqual(Path(os.readlink(agents / "extract-legacy")), REPO / "skills" / "extract-legacy")

    def test_link_straight_to_the_kit_counts_as_installed(self) -> None:
        claude = self.home / ".claude" / "skills" / "extract-legacy"
        claude.parent.mkdir(parents=True)
        claude.symlink_to(REPO / "skills" / "extract-legacy")
        row = self._rows()["claude extract-legacy"]
        self.assertEqual(row.state, "ok")
        self.assertNotIn("(linked)", row.detail)
        self.assertEqual(Path(os.readlink(claude)), REPO / "skills" / "extract-legacy")

    def test_bin_dir_missing_from_path_fails(self) -> None:
        with mock.patch.dict(os.environ, {"PATH": "/usr/bin"}):
            row = self._rows()["extractkit on PATH"]
        self.assertEqual(row.state, "MISSING")
        self.assertIn("export PATH=", row.fix)


class InstallCommandTests(unittest.TestCase):
    def test_install_command_links_into_home(self) -> None:
        result = run("install")
        self.assertIn("link extractkit", result.stdout)
        self.assertTrue((TEST_HOME / ".local" / "bin" / "extractkit").is_symlink())

    def test_deps_installs_as_part_of_preflight(self) -> None:
        link = TEST_HOME / ".agents" / "skills" / "extract-agentic"
        if link.is_symlink():
            link.unlink()
        result = run("deps", "--profile", "core")
        self.assertIn("skill extract-agentic", result.stdout)
        self.assertTrue(link.is_symlink())


if __name__ == "__main__":
    unittest.main()
