"""check gates: schemas, FR-10 coverage, OpenAPI x-source."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from tests.support import STATIC_UNTIL, copy_fixture, run, sidecar_run_dir


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


if __name__ == "__main__":
    unittest.main()
