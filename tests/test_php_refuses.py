"""PHP profile: doctor green, run refuses with the unfinished-work list."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.support import REPO, run


class PhpRefuseTests(unittest.TestCase):
    def test_doctor_php_is_green(self) -> None:
        result = run("doctor", "--profile", "php")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("clean", result.stdout)

    def test_run_php_exits_nonzero_with_todo(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw)
            (source / "README").write_text("not php source\n", encoding="utf-8")
            result = run(
                "run", "--profile", "php", "--source", str(source),
            )
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("unbound required adapters", combined)
        self.assertIn("unfinished work", combined.lower())
        self.assertIn("inventory.descriptors", combined)

    def test_php_step_raises_not_implemented(self) -> None:
        from extractkit_cli import manifest
        from extractkit_cli.common import Plan
        from extractkit_cli.runner import RunContext
        from steps.php import PhpPlaceholderStep

        ctx = RunContext(
            source=REPO,
            out=REPO / ".extract" / "unused",
            profile=manifest.load("php"),
            plan=Plan(),
            run_id="test",
        )
        with self.assertRaises(NotImplementedError) as caught:
            PhpPlaceholderStep().run(ctx)
        self.assertIn("unfinished", str(caught.exception).lower())


if __name__ == "__main__":
    unittest.main()
