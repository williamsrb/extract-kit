"""S11 merge-report, bounded contexts, live vs dead status."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from extractkit_cli.schema import validate
from steps.core.merge import _merge_report, merge_surfaces
from tests.support import STATIC_UNTIL, copy_fixture, run, sidecar_run_dir

RUNTIME = {
    "schema": "99x.extract.runtime-inventory/v1",
    "env": "local",
    "host": "http://127.0.0.1:9",
    "branch": "draft",
    "guillotine": "http://127.0.0.1:9/admin/site/preview/en/draft",
    "pages": [
        {
            "key": "/en",
            "round": 1,
            "context": "page",
            "templateOrder": [
                "com.example.mini:mini-page",
                "com.example.mini:mini-layout",
                "com.example.mini:mini-part",
            ],
        }
    ],
}


def _static(source: Path) -> Path:
    result = run(
        "run", "--profile", "enonic", "--source", str(source),
        *STATIC_UNTIL,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr + result.stdout)
    return sidecar_run_dir(source)


class MergeTests(unittest.TestCase):
    def test_static_merge_keeps_unverified_and_writes_contexts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            out = _static(source)
            result = run(
                "run", "--profile", "enonic", "--source", str(source),
                "--out", str(out),
                "--from", "maps.merge", "--until", "maps.merge",
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            contexts = json.loads((out / "map" / "bounded-contexts.json").read_text())
            validate(contexts, "bounded-contexts")
            ids = {c["id"] for c in contexts["contexts"]}
            self.assertIn("presentation", ids)
            self.assertIn("content", ids)
            self.assertIn("routing", ids)
            project = json.loads((out / "map" / "project-map.json").read_text())
            statuses = {s["status"] for s in project["surfaces"]}
            self.assertEqual(statuses, {"unverified-live"})
            report = (out / "inventory" / "merge-report.md").read_text()
            self.assertIn("No `inventory/runtime.json`", report)

    def test_runtime_marks_seen_live_and_unseen_components_unobserved(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            out = _static(source)
            (out / "inventory" / "runtime.json").write_text(
                json.dumps(RUNTIME, indent=2), encoding="utf-8",
            )
            result = run(
                "run", "--profile", "enonic", "--source", str(source),
                "--out", str(out),
                "--from", "maps.merge", "--until", "maps.merge",
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            project = json.loads((out / "map" / "project-map.json").read_text())
            by_id = {s["id"]: s for s in project["surfaces"]}
            self.assertEqual(by_id["com.example.mini:page:mini-page"]["status"], "live")
            self.assertEqual(by_id["com.example.mini:layout:mini-layout"]["status"], "live")
            self.assertEqual(by_id["com.example.mini:part:mini-part"]["status"], "live")
            self.assertEqual(by_id["com.example.mini:macro:mini-macro"]["status"], "unobserved")
            self.assertEqual(
                by_id["com.example.mini:content-type:mini-article"]["status"],
                "unverified-live",
            )
            composition = by_id["com.example.mini:page:mini-page"]["composition"]
            self.assertIn("com.example.mini:mini-page", composition)
            report = (out / "inventory" / "merge-report.md").read_text()
            self.assertIn("`live`", report)
            self.assertIn("`unobserved`: 1", report)
            self.assertIn("| id | kind | status | usage |", report)
            contexts = json.loads((out / "map" / "bounded-contexts.json").read_text())
            runtime_ids = {c["id"] for c in contexts["contexts"]}
            self.assertIn("runtime-page", runtime_ids)


def _component(name: str, kind: str = "part") -> dict:
    return {
        "id": f"a:{kind}:{name}", "kind": kind, "entry": "x", "evidence": [],
        "status": "unverified-live", "stackRef": {"enonic": {"app": "a"}},
    }


def _runtime(**extra: object) -> dict:
    return {"pages": [], **extra}


class StatusRuleTests(unittest.TestCase):
    def _status(self, runtime: dict, name: str = "p") -> dict:
        merged, _ = merge_surfaces([_component(name)], runtime)
        return merged[0]

    def test_unseen_without_usage_is_unobserved(self) -> None:
        self.assertEqual(self._status(_runtime())["status"], "unobserved")

    def test_usage_zero_is_dead(self) -> None:
        self.assertEqual(self._status(_runtime(usage={"a:part:p": 0}))["status"], "dead")

    def test_usage_above_zero_is_live_with_evidence(self) -> None:
        row = self._status(_runtime(usage={"a:part:p": 4}))
        self.assertEqual(row["status"], "live")
        self.assertIn("usage:a:p:4", row["evidence"])
        self.assertEqual(row["usage"], 4)

    def test_unsupported_probe_stays_unobserved(self) -> None:
        runtime = _runtime(usage={"a:part:p": None}, usageProbe="unsupported")
        self.assertEqual(self._status(runtime)["status"], "unobserved")

    def test_survey_beats_usage(self) -> None:
        runtime = _runtime(
            pages=[{"key": "/", "round": 1, "context": "page", "templateOrder": ["a:p"]}],
            usage={"a:part:p": 0},
        )
        self.assertEqual(self._status(runtime)["status"], "live")

    def test_usage_is_per_kind(self) -> None:
        runtime = _runtime(usage={"a:layout:hero": 3, "a:part:hero": 0})
        merged, _ = merge_surfaces([_component("hero", "layout"), _component("hero")], runtime)
        self.assertEqual([r["status"] for r in merged], ["live", "dead"])

    def test_report_shows_usage_column_and_probe_note(self) -> None:
        runtime = _runtime(usage={"a:part:p": 2, "a:part:q": None}, usageProbe="unsupported")
        merged, _ = merge_surfaces([_component("p"), _component("q")], runtime)
        report = _merge_report(runtime, merged, [])
        self.assertIn("| `a:part:p` | part | live | 2 |", report)
        self.assertIn("| `a:part:q` | part | unobserved | - |", report)
        self.assertIn("Usage probe: `unsupported`", report)


if __name__ == "__main__":
    unittest.main()
