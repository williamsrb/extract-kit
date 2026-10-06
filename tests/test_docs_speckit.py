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
    write_agent_outputs,
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

    def test_constitution_and_product_take_the_agent_files_on_a_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            out = _docs_tree(source)
            constitution = (out / "spec-kit" / "constitution.md").read_text()
            self.assertIn("The `constitution` agent task writes", constitution)
            self.assertIn("## Governance", constitution)
            self.assertFalse((out / "spec-kit" / "constitution" / "as-is.md").exists())
            product = (out / "product" / "PRODUCT.md").read_text()
            self.assertIn("The `business` agent task writes", product)
            self.assertIn("| part | 1 |", product)
            write_agent_outputs(out)
            for slot in ("spec.kit", "product.impeccable"):
                result = run("step", slot, "--profile", "enonic", "--source", str(source), "--out", str(out))
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            constitution = (out / "spec-kit" / "constitution.md").read_text()
            self.assertTrue(constitution.startswith(f"# {source.name} constitution (as-is)\n\n## Product\n"))
            self.assertIn("## Invariants", constitution)
            self.assertNotIn("Not written yet", constitution)
            product = (out / "product" / "PRODUCT.md").read_text()
            self.assertIn("### Actors\n\n- Visitor: reads pages.", product)
            self.assertIn("- Article publishing\n- Page rendering", product)
            self.assertNotIn("Not known yet", product)
            self.assertEqual(run("check", "--out", str(out)).returncode, 0)

    def test_spec_fr_without_cite_fails_check(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            out = _docs_tree(source)
            spec = next((out / "spec-kit" / "specs").glob("*/spec.md"))
            spec.write_text("# Broken\n\n### FR-1 No cite\n\nPlain prose.\n", encoding="utf-8")
            check = run("check", "--out", str(out))
            self.assertNotEqual(check.returncode, 0)
            self.assertIn("has no `Evidence:` line", check.stdout)

    def test_inferred_paragraph_needs_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            out = _docs_tree(source)
            spec = next((out / "spec-kit" / "specs").glob("*/spec.md"))
            spec.write_text(
                "# T\n\n### FR-1 Model text\n\nThe part reads a title. _(inferred)_\n\n"
                "Evidence: `com.example.mini:part:mini-part`\n",
                encoding="utf-8",
            )
            clean = run("check", "--out", str(out))
            self.assertEqual(clean.returncode, 0, clean.stderr + clean.stdout)
            spec.write_text(
                "# T\n\n### FR-1 Model text\n\nThe part reads a title. _(inferred)_\n\n"
                "Another paragraph.\n\nEvidence: `com.example.mini:part:mini-part`\n",
                encoding="utf-8",
            )
            bad = run("check", "--out", str(out))
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("`_(inferred)_` paragraph without an `Evidence:` line", bad.stdout)
            spec.write_text(
                "# T\n\nThe system emails editors nightly. _(inferred)_\n\n"
                "### FR-1 Kit text\n\nEvidence: `com.example.mini:part:mini-part`\n",
                encoding="utf-8",
            )
            lede = run("check", "--out", str(out))
            self.assertNotEqual(lede.returncode, 0)
            self.assertIn("before its first FR", lede.stdout)

    def test_kit_output_contains_no_inferred_text(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            out = _docs_tree(source)
            for path in (out / "spec-kit").rglob("*.md"):
                self.assertNotIn("_(inferred)_", path.read_text(encoding="utf-8"), path.name)
            for path in (out / "use-cases").glob("*.md"):
                self.assertNotIn("_(inferred)_", path.read_text(encoding="utf-8"), path.name)

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

    def test_spec_and_use_cases_state_behavior_with_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            out = _docs_tree(source)
            spec = (out / "spec-kit/specs/presentation/spec.md").read_text()
            self.assertIn("Acceptance:", spec)
            self.assertIn("- Config input `heading` is a TextLine occurring 1..1.", spec)
            self.assertIn("- Exposes region `main`.", spec)
            self.assertIn("- Localises key `mini.title`", spec)
            self.assertIn("mini-part.js:7`", spec)
            content = (out / "spec-kit/specs/content/spec.md").read_text()
            self.assertIn("limited to content types `com.example.mini:mini-article`", content)
            self.assertIn("from mixin `com.example.mini:mini-mixin`", content)
            self.assertIn("selecting 1..1 of `wide`, `narrow`", content)
            blocks = [b for b in spec.split("### FR-")[1:]]
            self.assertTrue(blocks)
            for block in blocks:
                self.assertRegex(block, r"(?m)^Evidence: `")
            journey = (out / "use-cases/routing.md").read_text()
            self.assertIn("- Exports `get`", journey)

    def test_runtime_pages_become_journeys_with_runtime_and_baseline_refs(self) -> None:
        import json

        from tests.test_merge import RUNTIME

        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            static = run("run", "--profile", "enonic", "--source", str(source), *STATIC_UNTIL)
            self.assertEqual(static.returncode, 0, static.stderr + static.stdout)
            out = sidecar_run_dir(source)
            runtime = json.loads(json.dumps(RUNTIME))
            runtime["pages"][0].update({"path": "/en", "type": "portal:site"})
            (out / "inventory/runtime.json").write_text(json.dumps(runtime), encoding="utf-8")
            (out / "baseline/en").mkdir(parents=True)
            (out / "baseline/en/desktop.png").write_bytes(b"png")
            (out / "baseline/INDEX.md").write_text(
                "| path | folder |\n|---|---|\n| `/en` | `en/` | yes |\n", encoding="utf-8",
            )
            result = run(
                "run", "--profile", "enonic", "--source", str(source),
                "--out", str(out), *DOCS_UNTIL,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            text = (out / "use-cases/runtime-page.md").read_text()
            self.assertIn("**Given** content of type `portal:site` at path `/en`", text)
            self.assertIn("**When** a visitor opens it", text)
            self.assertIn(
                "**Then** it renders the composition `com.example.mini:mini-page`, "
                "`com.example.mini:mini-layout`, `com.example.mini:mini-part`",
                text,
            )
            self.assertIn("`runtime:/en:r1`", text)
            self.assertIn("`baseline:en/desktop.png`", text)
            self.assertNotIn("baseline:en/mobile.png", text)


if __name__ == "__main__":
    unittest.main()
