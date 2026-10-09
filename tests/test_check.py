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
    valid_capabilities,
    valid_capability_spec,
    valid_constitution,
    valid_do_not_port,
    valid_domain_file,
    write_agent_outputs,
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
            (self.file.parent / "capabilities.json").write_text(valid_capabilities(), encoding="utf-8")
        return [p for p in check.check_tree(self.out) if "BUSINESS.md" in p or "capabilities.json" in p]

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
        self.assertEqual(set(check.NAMED_CHECKS), {
            "context_grounded", "business", "constitution", "spec_fr", "spec_review",
            "capability_spec", "domain_behavior", "do_not_port", "secrets",
        })


class ConstitutionCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.source, cls.out = build_sidecar(Path(cls._tmp.name))
        cls.file = cls.out / "spec-kit" / "constitution" / "project.md"

    def tearDown(self) -> None:
        self.file.unlink(missing_ok=True)

    def _check(self, text: str) -> list[str]:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(text, encoding="utf-8")
        return [p for p in check.check_tree(self.out) if "constitution" in p]

    def test_valid_file_passes(self) -> None:
        self.assertEqual(self._check(valid_constitution()), [])

    def test_missing_section_and_section_without_evidence_fail(self) -> None:
        text = valid_constitution().replace("## Stack", "## Platform")
        self.assertEqual(self._check(text), [
            "spec-kit/constitution/project.md is missing the section '## Stack'",
        ])
        text = valid_constitution().replace(
            "- One folder per component under `site/`.\n\nEvidence: `xp/src/main/resources/site/site.xml:1`",
            "- One folder per component under `site/`.",
        )
        self.assertEqual(self._check(text), [
            "spec-kit/constitution/project.md section '## Conventions' has no `Evidence:` line",
        ])

    def test_unresolved_ref_fails(self) -> None:
        problems = self._check(valid_constitution().replace("`content`", "`no-such-context`"))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("`no-such-context` does not resolve", problems[0])


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
        (cls.out / "spec-kit" / "specs" / "mini").mkdir(parents=True)
        (cls.out / "spec-kit" / "specs" / "mini" / "spec.md").write_text(valid_capability_spec("Mini"), encoding="utf-8")
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


class DomainGateTests(unittest.TestCase):
    """FR-15: capability_spec, domain_behavior, do_not_port and secrets."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.source, cls.out = build_sidecar(Path(cls._tmp.name))

    def setUp(self) -> None:
        write_agent_outputs(self.out)
        for rel in ("spec-kit/specs", "domain", "reports"):
            shutil.rmtree(self.out / rel, ignore_errors=True)
        self.addCleanup(self._clean)

    def _clean(self) -> None:
        for rel in ("spec-kit/specs", "domain", "reports"):
            shutil.rmtree(self.out / rel, ignore_errors=True)
        (self.out / "business" / "capabilities.json").unlink(missing_ok=True)

    def _write(self, rel: str, text: str) -> Path:
        path = self.out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def _problems(self, gate: str) -> list[str]:
        return check.NAMED_CHECKS[gate](self.out)

    def test_every_new_file_passes_when_valid(self) -> None:
        self._write("spec-kit/specs/article-publishing/spec.md", valid_capability_spec())
        self._write("domain/article-publishing.md", valid_domain_file())
        self._write("reports/do-not-port.md", valid_do_not_port())
        for gate in ("capability_spec", "domain_behavior", "do_not_port", "secrets"):
            self.assertEqual(self._problems(gate), [], gate)
        self.assertEqual(check.check_tree(self.out), [])

    def test_a_spec_needs_the_spec_kit_sections(self) -> None:
        self._write("spec-kit/specs/a/spec.md", "# A\n\n## Requirements\n\n- **FR-001**: System MUST x.\n")
        problems = self._problems("capability_spec")
        for title in ("User Scenarios & Testing", "Key Entities", "Success Criteria", "Edge Cases", "Evidence"):
            self.assertTrue(any(f"missing the section '## {title}'" in p for p in problems), title)

    def test_a_requirement_without_evidence_or_with_a_bad_ref_fails(self) -> None:
        spec = valid_capability_spec().replace(
            "- FR-002: `xp/src/main/resources/site/content-types/mini-article/mini-article.xml:13`, "
            "`com.example.mini:content-type:mini-article`\n", "- FR-002: `xp/nowhere.js:3`\n",
        ).replace("- FR-001: `xp/src/main/resources/site/content-types/mini-article/mini-article.xml:5`\n", "")
        self._write("spec-kit/specs/a/spec.md", spec)
        problems = self._problems("capability_spec")
        self.assertTrue(any("FR-001 has no evidence" in p for p in problems), problems)
        self.assertTrue(any("FR-002 Evidence ref `xp/nowhere.js:3` does not resolve" in p for p in problems), problems)

    def test_a_call_graph_requirement_and_a_missing_must_fail(self) -> None:
        spec = valid_capability_spec().replace(
            "System MUST let an article link to other articles.", "Calls `contentLib.query` to list articles.",
        )
        self._write("spec-kit/specs/a/spec.md", spec)
        problems = self._problems("capability_spec")
        self.assertTrue(any("FR-002 reads as a call graph" in p for p in problems), problems)
        self.assertTrue(any("FR-002 does not use MUST" in p for p in problems), problems)
        self._write("spec-kit/specs/a/spec.md", valid_capability_spec().replace("Exports", "x").replace(
            "require a title", "Exports `get` to require a title"))
        self.assertTrue(any("FR-001 reads as a call graph" in p for p in self._problems("capability_spec")))

    def test_a_spec_over_60_kb_fails(self) -> None:
        self._write("spec-kit/specs/a/spec.md", valid_capability_spec() + "\n" + "filler line\n" * 6000)
        self.assertTrue(any("over the 61440 byte limit" in p for p in self._problems("capability_spec")))

    def test_a_domain_bullet_needs_a_source_ref_that_resolves(self) -> None:
        text = valid_domain_file().replace(
            "Evidence: `xp/src/main/resources/lib/mini-http.js:4`", "Evidence: `xp/src/main/resources/lib/mini-http.js:999`",
        ).replace(" Evidence: `xp/src/main/resources/cron/mini-cron/index.js:11`", "")
        self._write("domain/a.md", text)
        problems = self._problems("domain_behavior")
        self.assertTrue(any("mini-http.js:999` does not resolve" in p for p in problems), problems)
        self.assertTrue(any("bullet has no `Evidence:` ref" in p for p in problems), problems)

    def test_a_domain_file_needs_its_sections(self) -> None:
        self._write("domain/a.md", "# A\n\n## Formulas\n\nNone found in the extracted module facts.\n")
        problems = self._problems("domain_behavior")
        self.assertTrue(any("missing the section '## State machines'" in p for p in problems))

    def test_do_not_port_entries_need_evidence_and_a_known_capability(self) -> None:
        text = valid_do_not_port().replace("Capability: `platform-and-operations`", "Capability: `nope`").replace(
            "Evidence: `xp/src/main/resources/services/mini-script-only/mini-script-only.js:1`", "Evidence:",
        )
        self._write("reports/do-not-port.md", text)
        problems = self._problems("do_not_port")
        self.assertTrue(any("DNP-001 has no `Evidence:` ref" in p for p in problems), problems)
        self.assertTrue(any("DNP-001 names no capability" in p for p in problems), problems)

    def test_a_requirement_may_not_cite_a_listed_defect_or_dead_code(self) -> None:
        ref = "xp/src/main/resources/lib/mini-http.js:4"
        self._write("reports/do-not-port.md", valid_do_not_port().replace(
            "## Dead code\n\nNone found.",
            f"## Dead code\n\n- **DNP-002** The helper is never called. Reason: dead. Capability: `page-rendering`. Evidence: `{ref}`",
        ))
        self._write("spec-kit/specs/article-publishing/spec.md", valid_capability_spec().replace(
            "mini-article.xml:5`", f"mini-article.xml:5`, `{ref}`", 1))
        problems = self._problems("do_not_port")
        self.assertTrue(any(f"cites `{ref}`" in p and "DNP-002" in p for p in problems), problems)

    def test_a_credential_literal_in_any_markdown_fails_naming_the_key_not_the_value(self) -> None:
        secret = "s3cr3t-Value-12345"
        (self.source / "xp" / "src" / "main" / "resources" / "app.cfg").write_text(
            f"sharedKey = {secret}\npassword = ${{env.PASSWORD}}\n", encoding="utf-8",
        )
        self.addCleanup((self.source / "xp" / "src" / "main" / "resources" / "app.cfg").unlink)
        self._write("reports/do-not-port.md", valid_do_not_port() + f"\nThe key is {secret}.\n")
        problems = self._problems("secrets")
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("reports/do-not-port.md", problems[0])
        self.assertIn("`sharedKey`", problems[0])
        self.assertIn("app.cfg:1", problems[0])
        self.assertNotIn(secret, problems[0])
        self._write("reports/do-not-port.md", valid_do_not_port())
        self.assertEqual(self._problems("secrets"), [])

    def test_business_needs_a_matching_capability_list_with_platform_and_operations(self) -> None:
        path = self.out / "business" / "capabilities.json"
        path.unlink()
        self.assertTrue(any("capabilities.json is missing" in p for p in check._business_gaps(self.out)))
        path.write_text(valid_capabilities().replace(
            '    {"id": "page-rendering", "title": "Page rendering"},\n', "").replace(
            '"platform-and-operations", "title": "Platform and operations"', '"extra", "title": "Extra"'), encoding="utf-8")
        problems = check._business_gaps(self.out)
        self.assertTrue(any("no row for the capability 'Page rendering'" in p for p in problems), problems)
        self.assertTrue(any("row 'extra' (Extra) has no '### Extra' heading" in p for p in problems), problems)
        self.assertTrue(any("no 'platform-and-operations' capability" in p for p in problems), problems)
