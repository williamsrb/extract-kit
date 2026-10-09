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
    valid_business,
    write_agent_outputs,
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
            self.assertIn("✓ 3 static", result.stdout)
            self.assertIn("→ 4 cms", result.stdout)
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
            self.assertIn("→ 5 merge", nxt.stdout)
            resumed = run(
                "resume", "--profile", "enonic", "--source", str(source),
                "--out", str(out), "--until", "spec.kit",
            )
            self.assertEqual(resumed.returncode, 0, resumed.stderr + resumed.stdout)
            self.assertTrue((out / "spec-kit" / "constitution.md").is_file())
            done = run("next", "--source", str(source), "--out", str(out))
            self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
            self.assertIn("→ 7 agent", done.stdout)
            self.assertIn("agent next --out", done.stdout)
            self.assertIn("or skip to check:", done.stdout)
            write_agent_outputs(out)
            back = run("next", "--source", str(source), "--out", str(out))
            self.assertIn("✓ 7 agent", back.stdout)
            self.assertIn("→ 8 check", back.stdout)
            self.assertIn("check --out", back.stdout)
            self.assertNotIn("agent next", back.stdout)

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
            self.assertIn("Agent is next:", result.stdout)
            self.assertIn("agent next --out", result.stdout)
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
            (out / "business").mkdir()
            (out / "business" / "BUSINESS.md").write_text(valid_business(), encoding="utf-8")
            applied = run(
                "promote", "--source", str(source), "--out", str(out),
            )
            self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)
            dest = source / ".specify" / "memory" / "constitution.md"
            self.assertTrue(dest.is_file())
            self.assertIn("as-is", dest.read_text().lower())
            self.assertTrue((source / "PRODUCT.md").is_file())
            self.assertEqual(
                (source / "BUSINESS.md").read_text(), (out / "business" / "BUSINESS.md").read_text(),
            )
            self.assertTrue((source / ".impeccable" / "design.json").is_file())
            self.assertFalse((source / "specs").exists(), "evidence specs are not promoted")
            self.assertNotEqual(porcelain(source), "")
            self.assertFalse((source / ".gitignore").exists())


if __name__ == "__main__":
    unittest.main()


class PromoteCapabilitySpecsTests(unittest.TestCase):
    def test_only_capability_specs_and_the_constitution_are_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            git_init(source)
            static = run("run", "--profile", "enonic", "--source", str(source), *STATIC_UNTIL)
            self.assertEqual(static.returncode, 0, static.stderr + static.stdout)
            out = sidecar_run_dir(source)
            docs = run(
                "run", "--profile", "enonic", "--source", str(source), "--out", str(out),
                "--from", "maps.merge", "--until", "spec.kit",
            )
            self.assertEqual(docs.returncode, 0, docs.stderr + docs.stdout)
            self.assertTrue(list((out / "spec-kit" / "evidence").glob("*.md")))
            (out / "spec-kit" / "specs" / "booking").mkdir(parents=True)
            (out / "spec-kit" / "specs" / "booking" / "spec.md").write_text("# Booking\n", encoding="utf-8")
            applied = run("promote", "--source", str(source), "--out", str(out))
            self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)
            self.assertEqual((source / "specs" / "booking" / "spec.md").read_text(), "# Booking\n")
            self.assertEqual([p.name for p in (source / "specs").iterdir()], ["booking"])
            self.assertTrue((source / ".specify" / "memory" / "constitution.md").is_file())
