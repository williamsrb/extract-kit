"""promote refuses to overwrite what git cannot restore, unless --force."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.support import git_init, run

CONSTITUTION = Path(".specify") / "memory" / "constitution.md"


def _sidecar(parent: Path) -> Path:
    out = parent / "sidecar"
    (out / "product").mkdir(parents=True)
    (out / "spec-kit").mkdir()
    (out / "product" / "PRODUCT.md").write_text("# new product\n", encoding="utf-8")
    (out / "spec-kit" / "constitution.md").write_text("# as-is\n", encoding="utf-8")
    return out


def _source(parent: Path, *, product: bool = False, ignore: bool = False) -> Path:
    source = parent / "legacy"
    source.mkdir()
    (source / "README.md").write_text("legacy\n", encoding="utf-8")
    if product:
        (source / "PRODUCT.md").write_text("# hand edited\n", encoding="utf-8")
    if ignore:
        (source / ".gitignore").write_text("PRODUCT.md\n", encoding="utf-8")
    return source


def _promote(source: Path, out: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return run("promote", "--source", str(source), "--out", str(out), *extra)


class PromoteGuardTests(unittest.TestCase):
    def _assert_refused(self, source: Path, out: Path, reason: str) -> None:
        result = _promote(source, out)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"PRODUCT.md  ({reason})", result.stderr)
        fix = [line for line in result.stderr.splitlines() if line.startswith("fix:")]
        self.assertEqual(len(fix), 1, result.stderr)
        self.assertTrue(fix[0].startswith("fix:   $ "), fix[0])
        self.assertTrue(fix[0].endswith(" --force"), fix[0])
        self.assertFalse((source / CONSTITUTION).exists())
        self.assertEqual((source / "PRODUCT.md").read_text(), "# hand edited\n")
        forced = _promote(source, out, "--force")
        self.assertEqual(forced.returncode, 0, forced.stdout + forced.stderr)
        self.assertEqual((source / "PRODUCT.md").read_text(), "# new product\n")
        self.assertTrue((source / CONSTITUTION).is_file())

    def test_tracked_clean_destination_is_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            source = _source(parent, product=True)
            git_init(source)
            out = _sidecar(parent)
            result = _promote(source, out)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((source / "PRODUCT.md").read_text(), "# new product\n")
            self.assertTrue((source / CONSTITUTION).is_file())
            self.assertIn("2 files written", result.stdout)
            self.assertIn(f"$ git -C {source} status", result.stdout)

    def test_modified_destination_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            source = _source(parent)
            (source / "PRODUCT.md").write_text("# committed\n", encoding="utf-8")
            git_init(source)
            (source / "PRODUCT.md").write_text("# hand edited\n", encoding="utf-8")
            self._assert_refused(source, _sidecar(parent), "modified")

    def test_staged_destination_is_refused_as_modified(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            source = _source(parent)
            git_init(source)
            (source / "PRODUCT.md").write_text("# hand edited\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(source), "add", "PRODUCT.md"], check=True)
            self._assert_refused(source, _sidecar(parent), "modified")

    def test_untracked_destination_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            source = _source(parent)
            git_init(source)
            (source / "PRODUCT.md").write_text("# hand edited\n", encoding="utf-8")
            self._assert_refused(source, _sidecar(parent), "untracked")

    def test_ignored_destination_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            source = _source(parent, ignore=True)
            git_init(source)
            (source / "PRODUCT.md").write_text("# hand edited\n", encoding="utf-8")
            self._assert_refused(source, _sidecar(parent), "ignored")

    def test_non_git_source_with_existing_destination_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            source = _source(parent, product=True)
            self._assert_refused(source, _sidecar(parent), "not in a git work tree")

    def test_non_git_source_without_existing_destinations_promotes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            source = _source(parent)
            result = _promote(source, _sidecar(parent))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((source / "PRODUCT.md").is_file())
            self.assertTrue((source / CONSTITUTION).is_file())


if __name__ == "__main__":
    unittest.main()
