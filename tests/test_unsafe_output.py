"""The kit never writes through a symlink out of the source tree, and headless refuses nonsense numbers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from extractkit_cli import cli
from tests.support import copy_fixture, run


class SymlinkTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.parent = Path(tmp.name)
        self.outside = self.parent / "outside"
        self.outside.mkdir()
        self.source = copy_fixture(self.parent)

    def error_code(self, result) -> str:
        return json.loads(result.stdout)["error"]["code"]

    def test_a_symlinked_extract_folder_is_refused_before_anything_is_written(self) -> None:
        for name, args in ((".extract", ("run", "--until", "static")), ("extract", ("headless",))):
            with self.subTest(folder=name):
                link = self.source / name
                link.symlink_to(self.outside)
                result = run(*args, "--source", str(self.source), "--json")
                link.unlink()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(self.error_code(result), "unsafe_output")
                self.assertEqual(list(self.outside.iterdir()), [])

    def test_promote_never_writes_through_a_symlink_even_with_force(self) -> None:
        out = self.parent / "sidecar"
        (out / "product").mkdir(parents=True)
        (out / "product" / "PRODUCT.md").write_text("# new\n", encoding="utf-8")
        target = self.outside / "victim.md"
        target.write_text("keep me\n", encoding="utf-8")
        (self.source / "PRODUCT.md").symlink_to(target)
        for extra in ((), ("--force",)):
            with self.subTest(extra=extra):
                result = run("promote", "--source", str(self.source), "--out", str(out), "--json", *extra)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(self.error_code(result), "promote_refused")
                self.assertEqual(target.read_text(), "keep me\n")

    def test_a_folder_symlink_above_the_destination_is_refused_too(self) -> None:
        out = self.parent / "sidecar"
        (out / "spec-kit").mkdir(parents=True)
        (out / "spec-kit" / "constitution.md").write_text("# c\n", encoding="utf-8")
        (self.source / ".specify").symlink_to(self.outside, target_is_directory=True)
        result = run("promote", "--source", str(self.source), "--out", str(out), "--json", "--force")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(list(self.outside.iterdir()), [])


class NumberTests(unittest.TestCase):
    def test_headless_refuses_a_negative_fix_count_and_a_non_positive_timeout(self) -> None:
        for flag, value in (("--max-fix-attempts", "-1"), ("--task-timeout", "0"), ("--task-timeout", "-5"), ("--max-fix-attempts", "x")):
            with self.subTest(flag=flag, value=value):
                result = run("headless", "--source", ".", f"{flag}={value}")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(flag, result.stderr)

    def test_zero_fix_attempts_is_allowed(self) -> None:
        args = cli.build_parser().parse_args(["headless", "--source", ".", "--max-fix-attempts", "0"])
        self.assertEqual(args.max_fix_attempts, 0)


if __name__ == "__main__":
    unittest.main()
