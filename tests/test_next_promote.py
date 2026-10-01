"""status (alias next) / resume / promote."""

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
                *STATIC_UNTIL,
            )
            self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)
            result = run("status", "--source", str(source))
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn("✓ 2 static", result.stdout)
            self.assertIn("→ 3 cms", result.stdout)
            self.assertIn("skills: extract-legacy", result.stdout)
            alias = run("next", "--source", str(source))
            self.assertEqual(alias.returncode, 0, alias.stderr + alias.stdout)
            self.assertEqual(alias.stdout, result.stdout)

    def test_resume_from_static_runs_merge_when_runtime_present(self) -> None:
        import json

        from tests.test_merge import RUNTIME

        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            applied = run(
                "run", "--profile", "enonic", "--source", str(source),
                *STATIC_UNTIL,
            )
            self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)
            out = sidecar_run_dir(source)
            (out / "inventory" / "runtime.json").write_text(
                json.dumps(RUNTIME, indent=2), encoding="utf-8",
            )
            nxt = run("next", "--source", str(source), "--out", str(out))
            self.assertEqual(nxt.returncode, 0, nxt.stderr + nxt.stdout)
            self.assertIn("→ 4 merge", nxt.stdout)
            resumed = run(
                "resume", "--profile", "enonic", "--source", str(source),
                "--out", str(out), "--until", "spec.kit",
            )
            self.assertEqual(resumed.returncode, 0, resumed.stderr + resumed.stdout)
            self.assertTrue((out / "spec-kit" / "constitution.md").is_file())
            done = run("next", "--source", str(source), "--out", str(out))
            self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
            self.assertIn("→ 6 check", done.stdout)
            self.assertIn("check --out", done.stdout)

    def test_status_names_optional_slots_that_were_not_captured(self) -> None:
        import json

        from tests.test_merge import RUNTIME

        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            run("run", "--profile", "enonic", "--source", str(source), *STATIC_UNTIL)
            out = sidecar_run_dir(source)
            (out / "inventory" / "runtime.json").write_text(
                json.dumps(RUNTIME, indent=2), encoding="utf-8",
            )
            resumed = run(
                "resume", "--profile", "enonic", "--source", str(source),
                "--out", str(out),
            )
            self.assertEqual(resumed.returncode, 0, resumed.stderr + resumed.stdout)
            result = run("status", "--source", str(source), "--out", str(out))
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn("optional, not captured: inventory.baseline", result.stdout)
            self.assertIn("tip   inventory.baseline not captured (optional):", result.stdout)
            self.assertIn("step inventory.baseline", result.stdout)
            self.assertIn("--storage-state", result.stdout)
            self.assertIn("Pipeline complete", result.stdout)
            quiet = run("status", "--source", str(source), "--out", str(out), "-q")
            self.assertNotIn("tip ", quiet.stdout)

    def test_promote_maps_constitution_into_source(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            git_init(source)
            static = run(
                "run", "--profile", "enonic", "--source", str(source),
                *STATIC_UNTIL,
            )
            self.assertEqual(static.returncode, 0, static.stderr + static.stdout)
            out = sidecar_run_dir(source)
            docs = run(
                "run", "--profile", "enonic", "--source", str(source),
                "--out", str(out),
                "--from", "maps.merge", "--until", "spec.kit",
            )
            self.assertEqual(docs.returncode, 0, docs.stderr + docs.stdout)
            applied = run(
                "promote", "--source", str(source), "--out", str(out),
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
