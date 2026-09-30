"""S12–S13 docs, impeccable wrappers, use-cases, spec-kit, check FR gate."""

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

DOCS_UNTIL = ("--from", "maps.merge", "--until", "spec.kit")


def _docs_tree(source: Path) -> Path:
    static = run(
        "run", "--profile", "enonic", "--source", str(source),
        *STATIC_UNTIL,
    )
    if static.returncode != 0:
        raise AssertionError(static.stderr + static.stdout)
    out = sidecar_run_dir(source)
    result = run(
        "run", "--profile", "enonic", "--source", str(source),
        "--out", str(out), *DOCS_UNTIL,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr + result.stdout)
    return out


class DocsSpeckitTests(unittest.TestCase):
    def test_docs_product_design_usecases_speckit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            git_init(source)
            out = _docs_tree(source)
            self.assertTrue((out / "docs" / "harvest" / "INDEX.md").is_file())
            self.assertTrue((out / "docs" / "harvest" / "README.md").is_file())
            self.assertTrue((out / "product" / "PRODUCT.md").is_file())
            product = (out / "product" / "PRODUCT.md").read_text()
            self.assertIn("as-is", product.lower())
            self.assertNotIn("DECISIONS.md", product)
            self.assertTrue((out / "design" / "DESIGN.md").is_file())
            self.assertTrue((out / "design" / "design.json").is_file())
            self.assertTrue((out / "docs" / "technical" / "overview.md").is_file())
            self.assertTrue((out / "docs" / "guide" / "overview.md").is_file())
            use_cases = list((out / "use-cases").glob("*.md"))
            self.assertTrue(use_cases)
            gwt = use_cases[0].read_text()
            self.assertIn("**Given**", gwt)
            self.assertIn("**When**", gwt)
            self.assertIn("**Then**", gwt)
            self.assertTrue((out / "spec-kit" / "constitution.md").is_file())
            constitution = (out / "spec-kit" / "constitution.md").read_text()
            self.assertIn("as-is", constitution.lower())
            self.assertNotIn("React4XP port plan", constitution.lower())
            specs = list((out / "spec-kit" / "specs").glob("*/spec.md"))
            self.assertTrue(specs)
            self.assertFalse(list((out / "spec-kit" / "specs").glob("*/tasks.md")))
            self.assertFalse((out / "DECISIONS.md").exists())
            self.assertFalse((out / "IMPLEMENTATION.md").exists())
            self.assertEqual(porcelain(source), "")
            check = run("check", "--out", str(out))
            self.assertEqual(check.returncode, 0, check.stderr + check.stdout)

    def test_spec_fr_without_cite_fails_check(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            out = _docs_tree(source)
            spec = next((out / "spec-kit" / "specs").glob("*/spec.md"))
            spec.write_text("# Broken\n\n### FR-1 No cite\n\nPlain prose.\n", encoding="utf-8")
            check = run("check", "--out", str(out))
            self.assertNotEqual(check.returncode, 0)
            self.assertIn("cites neither", check.stdout)

    def test_tasks_flag_writes_tasks_md(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            static = run(
                "run", "--profile", "enonic", "--source", str(source),
                *STATIC_UNTIL,
            )
            self.assertEqual(static.returncode, 0, static.stderr + static.stdout)
            out = sidecar_run_dir(source)
            result = run(
                "run", "--profile", "enonic", "--source", str(source),
                "--out", str(out), "--tasks", *DOCS_UNTIL,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue(list((out / "spec-kit" / "specs").glob("*/tasks.md")))


if __name__ == "__main__":
    unittest.main()
