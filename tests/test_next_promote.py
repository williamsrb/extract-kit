"""S14 next / resume / promote."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.support import (
    STATIC_UNTIL,
    copy_fixture,
    git_init,
    porcelain,
    run,
    sidecar_run_dir,
)


class NextPromoteTests(unittest.TestCase):
    def test_next_after_static_is_cms(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            applied = run(
                "run", "--profile", "enonic", "--source", str(source),
                "--apply", *STATIC_UNTIL,
            )
            self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)
            result = run("next", "--source", str(source))
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn("enonic.cms", result.stdout)
            self.assertIn("skill: extract-legacy", result.stdout)

    def test_resume_from_static_runs_merge_when_runtime_present(self) -> None:
        import json

        from tests.test_merge import RUNTIME

        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            applied = run(
                "run", "--profile", "enonic", "--source", str(source),
                "--apply", *STATIC_UNTIL,
            )
            self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)
            out = sidecar_run_dir(source)
            (out / "inventory" / "runtime.json").write_text(
                json.dumps(RUNTIME, indent=2), encoding="utf-8",
            )
            nxt = run("next", "--source", str(source), "--out", str(out))
            self.assertEqual(nxt.returncode, 0, nxt.stderr + nxt.stdout)
            self.assertIn("maps.merge", nxt.stdout)
            resumed = run(
                "resume", "--profile", "enonic", "--source", str(source),
                "--out", str(out), "--apply", "--until", "spec.kit",
            )
            self.assertEqual(resumed.returncode, 0, resumed.stderr + resumed.stdout)
            self.assertTrue((out / "spec-kit" / "constitution.md").is_file())
            done = run("next", "--source", str(source), "--out", str(out))
            self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
            self.assertIn("next: done", done.stdout)

    def test_promote_maps_constitution_and_leaves_git_dirty_only_when_applied(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            git_init(source)
            static = run(
                "run", "--profile", "enonic", "--source", str(source),
                "--apply", *STATIC_UNTIL,
            )
            self.assertEqual(static.returncode, 0, static.stderr + static.stdout)
            out = sidecar_run_dir(source)
            docs = run(
                "run", "--profile", "enonic", "--source", str(source),
                "--out", str(out), "--apply",
                "--from", "maps.merge", "--until", "spec.kit",
            )
            self.assertEqual(docs.returncode, 0, docs.stderr + docs.stdout)
            dry = run("promote", "--source", str(source), "--out", str(out))
            self.assertEqual(dry.returncode, 0, dry.stderr + dry.stdout)
            self.assertIn("Dry run", dry.stdout)
            self.assertFalse((source / ".specify" / "memory" / "constitution.md").is_file())
            self.assertEqual(porcelain(source), "")
            applied = run(
                "promote", "--source", str(source), "--out", str(out), "--apply",
            )
            self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)
            dest = source / ".specify" / "memory" / "constitution.md"
            self.assertTrue(dest.is_file())
            self.assertIn("as-is", dest.read_text().lower())
            self.assertTrue((source / "PRODUCT.md").is_file())
            self.assertTrue((source / ".impeccable" / "design.json").is_file())
            self.assertTrue(list((source / "specs").glob("*/spec.md")))
            self.assertNotEqual(porcelain(source), "")
            self.assertFalse((source / ".gitignore").exists())


if __name__ == "__main__":
    unittest.main()
