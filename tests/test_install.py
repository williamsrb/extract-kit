"""`extractkit install` is detached: the install is a copy, never a link into the checkout."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from extractkit_cli import install
from tests.support import FIXTURE, REPO, TEST_HOME, run


def _clone_kit(dest: Path) -> Path:
    """A checkout-shaped copy of the working tree, with no git history."""
    shutil.copytree(
        REPO, dest,
        ignore=shutil.ignore_patterns(
            ".git", ".serena", ".extract", "graft", "tests", "diagrams", "__pycache__",
            ".ruff_cache", ".security-local", ".docs-rewrite-backup", ".agents", ".claude",
        ),
    )
    return dest


def _env(home: Path) -> dict[str, str]:
    return {
        **os.environ, "HOME": str(home),
        "PATH": f"{home / '.local' / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
    }


def _symlinks_into(base: Path, kit: Path) -> list[Path]:
    hits = []
    for path in base.rglob("*"):
        if path.is_symlink() and kit.resolve() in (path.resolve(), *path.resolve().parents):
            hits.append(path)
    return hits


class InstallTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        patcher = mock.patch.dict(os.environ, {"PATH": str(self.home / ".local" / "bin")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.root = self.home / ".local" / "share" / "extractkit"
        self.cli = self.home / ".local" / "bin" / "extractkit"

    def _rows(self, **kwargs: object) -> dict:
        return {r.name: r for r in install.install(home=self.home, **kwargs)}

    @staticmethod
    def _age_marker(folder: Path) -> None:
        """Make the install look like an older kit version, so the next run copies."""
        path = folder / install.MARKER
        path.write_text(json.dumps({**json.loads(path.read_text()), "digest": "old"}))

    def test_fresh_install_copies_the_kit_and_links_nothing_into_the_checkout(self) -> None:
        rows = self._rows()
        self.assertTrue(all(r.state == "ok" for r in rows.values()), rows)
        self.assertTrue((self.root / "extractkit_cli" / "cli.py").is_file())
        self.assertTrue((self.root / "docs" / "llm.md").is_file())
        self.assertTrue((self.root / install.MARKER).is_file())
        for left_out in ("tests", "graft", ".git"):
            self.assertFalse((self.root / left_out).exists(), left_out)
        self.assertFalse((self.root / "docs" / "diagrams").exists())
        self.assertTrue(self.cli.is_file() and not self.cli.is_symlink())
        self.assertTrue(os.access(self.cli, os.X_OK))
        self.assertNotIn(str(REPO), self.cli.read_text())
        skills = install.skill_names()
        self.assertIn("extract-legacy", skills)
        for name in skills:
            agents = self.home / ".agents" / "skills" / name
            claude = self.home / ".claude" / "skills" / name
            self.assertTrue(agents.is_dir() and not agents.is_symlink())
            self.assertTrue((agents / install.MARKER).is_file())
            self.assertEqual(Path(os.readlink(claude)), agents)
            self.assertTrue((claude / "SKILL.md").is_file())
        self.assertEqual(_symlinks_into(self.home, REPO), [])

    def test_marker_records_commit_time_and_files(self) -> None:
        self._rows()
        marker = json.loads((self.root / install.MARKER).read_text())
        self.assertEqual(set(marker) >= {"kit_commit", "installed_at", "source_path", "files"}, True)
        self.assertIn("extractkit_cli/cli.py", marker["files"])
        self.assertEqual(marker["source_path"], str(REPO))

    def test_second_run_is_a_no_op(self) -> None:
        self._rows()
        before = (self.root / install.MARKER).read_text()
        rows = self._rows()
        self.assertTrue(all("(installed)" not in r.detail and "(linked)" not in r.detail for r in rows.values()), rows)
        self.assertEqual((self.root / install.MARKER).read_text(), before)

    def test_changed_kit_replaces_only_marked_folders(self) -> None:
        self._rows()
        stale = self.root / "stale.txt"
        stale.write_text("old\n")
        (self.root / "extractkit.yaml").write_text("tampered\n")
        self._age_marker(self.root)
        rows = self._rows()
        self.assertTrue(all(r.state == "ok" for r in rows.values()), rows)
        self.assertFalse(stale.exists())
        self.assertEqual((self.root / "extractkit.yaml").read_text(), (REPO / "extractkit.yaml").read_text())

    def test_foreign_real_folder_and_file_are_never_touched(self) -> None:
        skill = self.home / ".agents" / "skills" / "extract-legacy"
        skill.mkdir(parents=True)
        (skill / "mine.txt").write_text("mine\n")
        self.cli.parent.mkdir(parents=True)
        self.cli.write_text("mine\n")
        self.root.mkdir(parents=True)
        (self.root / "mine.txt").write_text("mine\n")
        for force in (False, True):
            rows = self._rows(force=force)
            for name in ("skill extract-legacy", "launcher extractkit", "install"):
                self.assertEqual(rows[name].state, "BROKEN", name)
                self.assertIn("move ", rows[name].fix)
        self.assertEqual((skill / "mine.txt").read_text(), "mine\n")
        self.assertEqual(self.cli.read_text(), "mine\n")
        self.assertEqual((self.root / "mine.txt").read_text(), "mine\n")

    def test_old_symlinks_into_the_checkout_are_migrated(self) -> None:
        self.cli.parent.mkdir(parents=True)
        self.cli.symlink_to(REPO / "extractkit")
        agents = self.home / ".agents" / "skills" / "extract-legacy"
        agents.parent.mkdir(parents=True)
        agents.symlink_to(REPO / "skills" / "extract-legacy")
        claude = self.home / ".claude" / "skills" / "extract-legacy"
        claude.parent.mkdir(parents=True)
        claude.symlink_to(agents)
        rows = self._rows()
        self.assertTrue(all(r.state == "ok" for r in rows.values()), rows)
        self.assertFalse(self.cli.is_symlink())
        self.assertFalse(agents.is_symlink())
        self.assertTrue((agents / install.MARKER).is_file())
        self.assertEqual(_symlinks_into(self.home, REPO), [])

    def test_claude_link_to_a_removed_skill_folder_is_relinked_without_force(self) -> None:
        claude = self.home / ".claude" / "skills" / "extract-legacy"
        claude.parent.mkdir(parents=True)
        claude.symlink_to(self.home / ".agents" / "skills" / "extract-legacy")
        self.assertFalse(claude.exists())
        rows = self._rows()
        self.assertTrue(all(r.state == "ok" for r in rows.values()), rows)
        self.assertTrue((claude / "SKILL.md").is_file())

    def test_foreign_symlink_needs_force(self) -> None:
        self.cli.parent.mkdir(parents=True)
        self.cli.symlink_to("/somewhere/else")
        row = self._rows()["launcher extractkit"]
        self.assertEqual(row.state, "BROKEN")
        self.assertTrue(row.failed)
        self.assertIn("--force", row.fix)
        self.assertEqual(self._rows(force=True)["launcher extractkit"].state, "ok")
        self.assertFalse(self.cli.is_symlink())

    def test_claude_skills_linked_to_agents_skills_is_left_alone(self) -> None:
        agents = self.home / ".agents" / "skills"
        agents.mkdir(parents=True)
        (self.home / ".claude").mkdir()
        (self.home / ".claude" / "skills").symlink_to(agents)
        for force in (False, True):
            rows = self._rows(force=force)
            self.assertTrue(all(r.state == "ok" for r in rows.values()), rows)
        self.assertTrue((agents / "extract-legacy" / install.MARKER).is_file())

    def test_bin_dir_missing_from_path_fails(self) -> None:
        with mock.patch.dict(os.environ, {"PATH": "/usr/bin"}):
            row = self._rows()["extractkit on PATH"]
        self.assertEqual(row.state, "MISSING")
        self.assertIn("export PATH=", row.fix)

    def test_failed_copy_leaves_the_previous_install(self) -> None:
        self._rows()
        before = (self.root / "extractkit_cli" / "cli.py").read_text()
        self._age_marker(self.root)
        with mock.patch.object(install, "_swap", side_effect=OSError("disk full")):
            row = self._rows()["install"]
        self.assertEqual(row.state, "BROKEN")
        self.assertEqual((self.root / "extractkit_cli" / "cli.py").read_text(), before)
        self.assertEqual(list(self.root.parent.glob(".extractkit.new-*")), [])


class DetachedInstallTests(unittest.TestCase):
    """Install from a clone, delete the clone, and run from the installed copy."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        cls.home = tmp / "home"
        cls.home.mkdir()
        cls.clone = _clone_kit(tmp / "clone")
        cls.install_result = subprocess.run(
            [sys.executable, str(cls.clone / "extractkit"), "install"],
            cwd=cls.clone, capture_output=True, text=True, check=False, env=_env(cls.home),
        )
        cls.clone_path = str(cls.clone)
        shutil.rmtree(cls.clone)
        cls.cli = cls.home / ".local" / "bin" / "extractkit"
        cls.work = tmp / "work"
        shutil.copytree(FIXTURE, cls.work)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _run(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.cli), *args], cwd=cwd or self.work, capture_output=True, text=True,
            check=False, env=_env(self.home),
        )

    def test_install_succeeded_without_git(self) -> None:
        self.assertEqual(self.install_result.returncode, 0, self.install_result.stdout)
        marker = json.loads((self.home / ".local/share/extractkit" / install.MARKER).read_text())
        self.assertEqual(marker["kit_commit"], "unknown")

    def test_nothing_the_install_wrote_points_at_the_deleted_clone(self) -> None:
        self.assertFalse(Path(self.clone_path).exists())
        self.assertTrue(self.cli.is_file() and not self.cli.is_symlink())
        for path in self.home.rglob("*"):
            if path.is_symlink():
                self.assertNotIn(self.clone_path, os.readlink(path))
            elif path.is_file() and path.stat().st_size < 200_000:
                if path.name == install.MARKER:
                    continue
                self.assertNotIn(self.clone_path, path.read_text(errors="ignore"), path)

    def test_doctor_runs_and_names_the_install(self) -> None:
        result = self._run("doctor", "--profile", "enonic")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_deps_takes_the_check_only_path(self) -> None:
        root = self.home / ".local" / "share" / "extractkit"
        before = (root / install.MARKER).read_text()
        result = self._run("deps", "--profile", "core")
        self.assertIn("install ", result.stdout)
        self.assertIn("commit unknown", result.stdout)
        self.assertEqual((root / install.MARKER).read_text(), before)

    def test_offline_run_works_from_the_installed_copy(self) -> None:
        result = self._run("run", "--source", ".", "--until", "static")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(any((self.work / ".extract").iterdir()))

    def test_skills_load_and_name_the_installed_docs(self) -> None:
        for name in install.skill_names(self.home / ".local/share/extractkit"):
            text = (self.home / ".claude" / "skills" / name / "SKILL.md").read_text()
            self.assertIn("~/.local/share/extractkit/docs/llm.md", text)
        self.assertTrue((self.home / ".local/share/extractkit/docs/llm.md").is_file())

    def test_install_from_the_installed_copy_copies_nothing_and_flags_a_mismatch(self) -> None:
        root = self.home / ".local" / "share" / "extractkit"
        before = (root / install.MARKER).read_text()
        result = self._run("install")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual((root / install.MARKER).read_text(), before)
        skill_marker = self.home / ".agents/skills/extract-legacy" / install.MARKER
        data = json.loads(skill_marker.read_text())
        original = skill_marker.read_text()
        skill_marker.write_text(json.dumps({**data, "kit_commit": "deadbeef"}))
        try:
            result = self._run("install")
            self.assertEqual(result.returncode, 1)
            self.assertIn("run ./extractkit install from a kit checkout", result.stdout)
        finally:
            skill_marker.write_text(original)


class InstallCommandTests(unittest.TestCase):
    def test_install_command_copies_into_home(self) -> None:
        result = run("install")
        self.assertIn("launcher extractkit", result.stdout)
        launcher = TEST_HOME / ".local" / "bin" / "extractkit"
        self.assertTrue(launcher.is_file() and not launcher.is_symlink())
        self.assertTrue((TEST_HOME / ".local/share/extractkit" / install.MARKER).is_file())

    def test_deps_in_the_installed_copy_checks_instead_of_installing(self) -> None:
        folder = TEST_HOME / ".agents" / "skills" / "extract-agentic"
        backup = folder.with_name("extract-agentic.bak")
        folder.rename(backup)
        try:
            result = run("deps", "--profile", "core")
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("skill extract-agentic", result.stdout)
            self.assertIn("run ./extractkit install from a kit checkout", result.stdout)
            self.assertFalse(folder.exists())
        finally:
            backup.rename(folder)


if __name__ == "__main__":
    unittest.main()
