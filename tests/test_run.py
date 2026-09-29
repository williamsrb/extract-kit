"""Sidecar run: dry-run writes nothing; --apply is self-ignored; source stays clean."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from tests.support import (
    STATIC_UNTIL,
    copy_fixture,
    git_init,
    porcelain,
    run,
    sidecar_run_dir,
)


class RunTests(unittest.TestCase):
    def test_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            git_init(source)
            before = {p.relative_to(source) for p in source.rglob("*") if p.is_file()}
            result = run("run", "--profile", "enonic", "--source", str(source), *STATIC_UNTIL)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Dry run", result.stdout)
            after = {p.relative_to(source) for p in source.rglob("*") if p.is_file()}
            self.assertEqual(before, after)
            self.assertEqual(porcelain(source), "")

    def test_apply_writes_sidecar_and_leaves_git_clean(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            git_init(source)
            result = run(
                "run", "--profile", "enonic", "--source", str(source),
                "--apply", *STATIC_UNTIL,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(porcelain(source), "")
            out = sidecar_run_dir(source)
            self.assertTrue((out / "MANIFEST.yaml").is_file())
            self.assertTrue((out / "inventory" / "static.json").is_file())
            self.assertTrue((out / "integrations" / "openapi.yaml").is_file())
            self.assertTrue((out / "integrations" / "swagger-ui" / "index.html").is_file())
            ignore = source / ".extract" / ".gitignore"
            self.assertEqual(ignore.read_text(encoding="utf-8"), "*\n")
            manifest = yaml.safe_load((out / "MANIFEST.yaml").read_text())
            self.assertEqual(manifest["source"]["profile"], "enonic")
            self.assertIn("core", manifest["source"]["lineage"])
            skips = {row["step"]: row for row in manifest.get("skips") or []}
            self.assertIn("map.code", skips)
            self.assertIn("graft build", skips["map.code"]["fix"])
            self.assertIn("map.semantic", skips)
            openapi = (out / "integrations" / "openapi.yaml").read_text()
            self.assertNotIn("authentic-scandinavia", openapi)
            self.assertIn("x-source", openapi)
            self.assertIn("cdn.example.test", openapi)

    def test_code_map_records_existing_graft_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            graft = source / "graft"
            graft.mkdir()
            (graft / "INDEX.md").write_text("# graft\n", encoding="utf-8")
            result = run(
                "run", "--profile", "enonic", "--source", str(source),
                "--apply", *STATIC_UNTIL,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            out = sidecar_run_dir(source)
            manifest = yaml.safe_load((out / "MANIFEST.yaml").read_text())
            self.assertEqual(manifest["maps"]["code"], str(graft))
            skip_steps = {row["step"] for row in manifest.get("skips") or []}
            self.assertNotIn("map.code", skip_steps)


if __name__ == "__main__":
    unittest.main()
