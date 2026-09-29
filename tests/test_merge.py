"""S11 merge-report, bounded contexts, live vs dead status."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from extractkit_cli.schema import validate
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
        "--apply", *STATIC_UNTIL,
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
                "--out", str(out), "--apply",
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

    def test_runtime_marks_seen_live_and_unseen_components_dead(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            out = _static(source)
            (out / "inventory" / "runtime.json").write_text(
                json.dumps(RUNTIME, indent=2), encoding="utf-8",
            )
            result = run(
                "run", "--profile", "enonic", "--source", str(source),
                "--out", str(out), "--apply",
                "--from", "maps.merge", "--until", "maps.merge",
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            project = json.loads((out / "map" / "project-map.json").read_text())
            by_id = {s["id"]: s for s in project["surfaces"]}
            self.assertEqual(by_id["com.example.mini:page:mini-page"]["status"], "live")
            self.assertEqual(by_id["com.example.mini:layout:mini-layout"]["status"], "live")
            self.assertEqual(by_id["com.example.mini:part:mini-part"]["status"], "live")
            self.assertEqual(by_id["com.example.mini:macro:mini-macro"]["status"], "dead")
            self.assertEqual(
                by_id["com.example.mini:content-type:mini-article"]["status"],
                "unverified-live",
            )
            composition = by_id["com.example.mini:page:mini-page"]["composition"]
            self.assertIn("com.example.mini:mini-page", composition)
            report = (out / "inventory" / "merge-report.md").read_text()
            self.assertIn("`live`", report)
            contexts = json.loads((out / "map" / "bounded-contexts.json").read_text())
            runtime_ids = {c["id"] for c in contexts["contexts"]}
            self.assertIn("runtime-page", runtime_ids)


if __name__ == "__main__":
    unittest.main()
