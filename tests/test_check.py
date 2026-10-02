"""check gates: schemas, FR-10 coverage, OpenAPI x-source."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from extractkit_cli import check
from tests.support import (
    STATIC_UNTIL,
    build_sidecar,
    copy_fixture,
    run,
    sidecar_run_dir,
    valid_business,
)


def _apply(source: Path) -> Path:
    result = run(
        "run", "--profile", "enonic", "--source", str(source),
        *STATIC_UNTIL,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr + result.stdout)
    return sidecar_run_dir(source)


class CheckTests(unittest.TestCase):
    def test_fixture_extract_passes_check(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            out = _apply(source)
            result = run("check", "--out", str(out))
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            inventory = json.loads((out / "inventory" / "static.json").read_text())
            kinds = {row["kind"] for row in inventory["resources"]}
            for kind in (
                "site", "content-type", "mixin", "x-data", "page",
                "layout", "part", "macro", "service", "task", "filter",
                "response-processor", "error", "admin-tool", "admin-widget", "webapp",
                "id-provider", "i18n-bundle",
            ):
                self.assertIn(kind, kinds, kinds)

    def test_missing_x_source_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            out = _apply(source)
            path = out / "integrations" / "openapi.yaml"
            spec = yaml.safe_load(path.read_text())
            for item in spec["paths"].values():
                for op in item.values():
                    if isinstance(op, dict):
                        op.pop("x-source", None)
            path.write_text(yaml.safe_dump(spec), encoding="utf-8")
            result = run("check", "--out", str(out))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("x-source", result.stdout)

    def test_dropped_descriptor_fails_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            out = _apply(source)
            project = json.loads((out / "map" / "project-map.json").read_text())
            project["surfaces"] = [
                s for s in project["surfaces"] if s.get("kind") != "part"
            ]
            (out / "map" / "project-map.json").write_text(
                json.dumps(project, indent=2), encoding="utf-8",
            )
            for rel in ("component-map.json",):
                payload = json.loads((out / "map" / rel).read_text())
                payload["components"] = []
                (out / "map" / rel).write_text(
                    json.dumps(payload, indent=2), encoding="utf-8",
                )
            result = run("check", "--out", str(out))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("descriptor", result.stdout)

    def test_dropped_new_kind_fails_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            out = _apply(source)
            project = json.loads((out / "map" / "project-map.json").read_text())
            project["surfaces"] = [
                s for s in project["surfaces"] if s.get("kind") != "i18n-bundle"
            ]
            (out / "map" / "project-map.json").write_text(
                json.dumps(project, indent=2), encoding="utf-8",
            )
            model = json.loads((out / "map" / "content-model.json").read_text())
            model["types"] = [t for t in model["types"] if t.get("kind") != "i18n-bundle"]
            (out / "map" / "content-model.json").write_text(
                json.dumps(model, indent=2), encoding="utf-8",
            )
            result = run("check", "--out", str(out))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("phrases", result.stdout)

    def test_invalid_controllers_json_fails_check(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            out = _apply(source)
            path = out / "inventory" / "controllers.json"
            payload = json.loads(path.read_text())
            payload["controllers"][0].pop("calls")
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = run("check", "--out", str(out))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("controllers", result.stdout)

    def test_kit_repo_has_no_plan_md(self) -> None:
        from tests.support import REPO

        self.assertFalse((REPO / "PLAN.md").exists())
        self.assertFalse((REPO / ".gitlab-ci.yml").exists())
        self.assertFalse((REPO / ".gitlab-ci.yaml").exists())
        self.assertTrue((REPO / "docs" / "cli.md").is_file())
        self.assertTrue((REPO / "skills" / "extract-legacy" / "SKILL.md").is_file())


class BusinessCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.source, cls.out = build_sidecar(Path(cls._tmp.name))
        cls.file = cls.out / "business" / "BUSINESS.md"

    def tearDown(self) -> None:
        shutil.rmtree(self.file.parent, ignore_errors=True)

    def _check(self, text: str | None) -> list[str]:
        if text is not None:
            self.file.parent.mkdir(exist_ok=True)
            self.file.write_text(text, encoding="utf-8")
        return [p for p in check.check_tree(self.out) if "BUSINESS.md" in p]

    def test_absent_file_passes(self) -> None:
        self.assertEqual(self._check(None), [])
        self.assertEqual(run("check", "--out", str(self.out)).returncode, 0)

    def test_valid_file_passes(self) -> None:
        self.assertEqual(self._check(valid_business()), [])
        self.assertEqual(run("check", "--out", str(self.out)).returncode, 0)

    def test_missing_section_fails(self) -> None:
        text = valid_business().replace("## Glossary\n\n- Article: the mini-article content type.\n", "")
        problems = self._check(text)
        self.assertEqual(problems, ["business/BUSINESS.md is missing the section '## Glossary'"])
        result = run("check", "--out", str(self.out))
        self.assertEqual(result.returncode, 1)
        self.assertIn("## Glossary", result.stdout)

    def test_unresolved_source_ref_fails(self) -> None:
        for ref in ("xp/src/main/resources/site/site.xml:99999", "no/such/file.xml:1", "made-up-id"):
            with self.subTest(ref=ref):
                problems = self._check(valid_business().replace(
                    "`xp/src/main/resources/site/site.xml:1`", f"`{ref}`"))
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(f"`{ref}` does not resolve", problems[0])

    def test_source_ref_cannot_leave_the_checkout(self) -> None:
        problems = self._check(valid_business().replace(
            "`xp/src/main/resources/site/site.xml:1`", "`../../MANIFEST.yaml:1`"))
        self.assertEqual(len(problems), 1, problems)

    def test_unknown_rule_id_fails(self) -> None:
        problems = self._check(valid_business().replace(
            "`com.example.mini:site:site`", "`VR-aaaaaaaaaa`"))
        self.assertEqual(
            problems,
            ["business/BUSINESS.md cites rule VR-aaaaaaaaaa, which is not in rules/view-rules.json"],
        )

    def test_known_rule_id_resolves(self) -> None:
        rules = json.loads((self.out / "rules" / "view-rules.json").read_text())
        rules["rules"].append({"id": "VR-0123456789", "bucket": "presentational"})
        path = self.out / "rules" / "view-rules.json"
        original = path.read_text()
        self.addCleanup(path.write_text, original, encoding="utf-8")
        path.write_text(json.dumps(rules), encoding="utf-8")
        self.assertEqual(self._check(valid_business().replace(
            "`com.example.mini:site:site`", "`VR-0123456789`")), [])

    def test_capability_without_a_rule_or_surface_fails(self) -> None:
        text = valid_business().replace(
            "Evidence: `com.example.mini:part:mini-part`", "Evidence: `presentation`")
        problems = self._check(text)
        self.assertEqual(
            problems,
            ["business/BUSINESS.md capability 'Page rendering' cites no rule id or surface id"],
        )

    def test_inferred_paragraph_without_evidence_fails(self) -> None:
        text = valid_business().replace(
            "- Which editors publish articles? _(inferred)_\n\nEvidence: `com.example.mini:site:site`\n",
            "- Which editors publish articles? _(inferred)_\n")
        problems = self._check(text)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("section '## Open questions' has an `_(inferred)_` paragraph without", problems[0])

    def test_every_named_check_exists(self) -> None:
        self.assertEqual(set(check.NAMED_CHECKS), {"context_grounded", "business", "spec_fr", "spec_review"})


VALID_FINDING = """### SR-1: FR-1 misreads the site descriptor

Spec: {spec} FR-1
Severity: medium
Fix in: extractor
Evidence: `xp/src/main/resources/site/site.xml:1`

The FR says the site has no config; the descriptor declares one.
"""


class SpecReviewCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.source, cls.out = build_sidecar(Path(cls._tmp.name))
        cls.file = cls.out / "reports" / "spec-review.md"
        specs = sorted((cls.out / "spec-kit" / "specs").glob("*/spec.md"))
        cls.spec = specs[0].relative_to(cls.out).as_posix()

    def setUp(self) -> None:
        self.addCleanup(self.file.unlink, missing_ok=True)

    def _finding(self, **replace: str) -> str:
        text = VALID_FINDING.format(spec=self.spec)
        for old, new in replace.items():
            text = text.replace(old, new)
        return text

    def _check(self, body: str | None) -> list[str]:
        if body is not None:
            self.file.parent.mkdir(exist_ok=True)
            self.file.write_text(body, encoding="utf-8")
        return [p for p in check.check_tree(self.out) if "spec-review.md" in p]

    def test_absent_file_passes(self) -> None:
        self.assertEqual(self._check(None), [])
        self.assertEqual(run("check", "--out", str(self.out)).returncode, 0)

    def test_no_findings_passes(self) -> None:
        self.assertEqual(self._check("# Spec review\n\nNo findings.\n"), [])
        self.assertEqual(run("check", "--out", str(self.out)).returncode, 0)

    def test_valid_finding_passes(self) -> None:
        self.assertEqual(self._check("# Spec review\n\n" + self._finding()), [])
        self.assertEqual(run("check", "--out", str(self.out)).returncode, 0)

    def test_a_high_severity_finding_does_not_fail_check(self) -> None:
        self.assertEqual(self._check("# Spec review\n\n" + self._finding(medium="high")), [])

    def test_missing_h1_fails(self) -> None:
        problems = self._check(self._finding())
        self.assertEqual(problems, ["reports/spec-review.md is missing the H1 '# Spec review'"])

    def test_neither_findings_nor_no_findings_fails(self) -> None:
        problems = self._check("# Spec review\n\nLooks fine.\n")
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("no 'No findings.' line", problems[0])

    def test_missing_field_fails(self) -> None:
        for field in ("Spec", "Severity", "Fix in", "Evidence"):
            with self.subTest(field=field):
                body = "\n".join(
                    line for line in self._finding().splitlines() if not line.startswith(f"{field}:")
                )
                problems = self._check("# Spec review\n\n" + body)
                self.assertIn(f"reports/spec-review.md SR-1 has no `{field}:` line", problems)

    def test_bad_severity_fails(self) -> None:
        problems = self._check("# Spec review\n\n" + self._finding(medium="critical"))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("Severity `critical`", problems[0])

    def test_bad_fix_in_fails(self) -> None:
        problems = self._check("# Spec review\n\n" + self._finding(extractor="somewhere"))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("Fix in `somewhere`", problems[0])

    def test_unknown_spec_path_fails(self) -> None:
        problems = self._check("# Spec review\n\n" + self._finding(**{self.spec: "spec-kit/specs/nope/spec.md"}))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("is not a spec-kit/specs/<slug>/spec.md in this sidecar", problems[0])

    def test_unresolved_evidence_fails(self) -> None:
        for ref in ("xp/src/main/resources/site/site.xml:99999", "made-up-id"):
            with self.subTest(ref=ref):
                problems = self._check(
                    "# Spec review\n\n" + self._finding(**{"xp/src/main/resources/site/site.xml:1": ref}))
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(f"`{ref}` does not resolve", problems[0])

    def test_findings_are_checked_one_by_one(self) -> None:
        second = self._finding(**{"SR-1": "SR-2", "medium": "urgent"})
        problems = self._check("# Spec review\n\n" + self._finding() + "\n" + second)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("SR-2", problems[0])


if __name__ == "__main__":
    unittest.main()
