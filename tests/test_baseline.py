"""enonic.baseline: playwright-cli is mocked; no browser, no network."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from extractkit_cli import manifest
from extractkit_cli.common import Plan
from extractkit_cli.errors import ExtractkitError
from extractkit_cli.runner import RunContext
from steps.enonic import baseline
from steps.enonic.baseline import EnonicBaselineStep, parse_requests, slugify

RUNTIME = {
    "schema": "extractkit.runtime-inventory/v1",
    "env": "local", "host": "http://localhost:8080", "branch": "draft",
    "guillotine": "http://localhost:8080/admin/site/preview/en/draft",
    "pages": [
        {"key": "/en", "path": "/en", "round": 1, "context": "page"},
        {"key": "/en/about us", "path": "/en/about us", "round": 1, "context": "page"},
        {"key": "/en", "path": "/en", "round": 2, "context": "page"},
        {"key": "/en/broken", "path": "/en/broken", "round": 1, "context": "page", "error": "x"},
    ],
}
REQUESTS_TEXT = (
    "1. [GET] http://localhost:8080/admin/site/preview/en/draft/en => [200] OK\n"
    "2. [GET] https://fonts.example.test/a.woff2?key=abc => [200] OK\n"
    "3. [GET] https://stats.example.test/t.js => [FAILED] net::ERR_BLOCKED\n"
)


class FakePlaywright:
    def __init__(self, fail_on: str | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail_on = fail_on

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.calls.append(command[2:])
        verb = next(a for a in command[2:] if not a.startswith("--raw"))
        if self.fail_on == verb:
            return subprocess.CompletedProcess(command, 1, "", "### Error\nError: boom\n")
        out = ""
        if verb == "screenshot":
            name = next(a for a in command if a.startswith("--filename=")).split("=", 1)[1]
            Path(name).write_bytes(b"png")
        elif verb == "eval":
            out = json.dumps("<html><body>hi</body></html>") + "\n"
        elif verb == "requests":
            out = REQUESTS_TEXT
        return subprocess.CompletedProcess(command, 0, out, "")


def _ctx(parent: Path, **cms: object) -> RunContext:
    out = parent / "out"
    (out / "inventory").mkdir(parents=True)
    (out / "inventory/runtime.json").write_text(json.dumps(RUNTIME), encoding="utf-8")
    (out / "integrations").mkdir()
    (out / "integrations/openapi.yaml").write_text(
        yaml.safe_dump({"openapi": "3.1.0", "paths": {}}), encoding="utf-8",
    )
    state = parent / "state.json"
    state.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    return RunContext(
        source=parent, out=out, profile=manifest.load("enonic"), plan=Plan(), run_id="t",
        cms={
            "branch": "draft", "xp_host": "http://localhost:8080", "project": "en",
            "storage_state": str(state), **cms,
        },
    )


class HelperTests(unittest.TestCase):
    def test_slug_and_requests(self) -> None:
        self.assertEqual(slugify("/en/About us/"), "en-about-us")
        self.assertEqual(slugify("/"), "root")
        rows = parse_requests(REQUESTS_TEXT)
        self.assertEqual(rows[1]["url"], "https://fonts.example.test/a.woff2")
        self.assertEqual(rows[2]["status"], "FAILED")


class BaselineStepTests(unittest.TestCase):
    def _run(self, ctx: RunContext, fake: FakePlaywright | None = None) -> FakePlaywright:
        fake = fake or FakePlaywright()
        with (
            mock.patch.object(baseline.subprocess, "run", fake),
            mock.patch.object(baseline.shutil, "which", return_value="/usr/bin/playwright-cli"),
        ):
            EnonicBaselineStep().run(ctx)
        return fake

    def test_success_writes_screenshots_html_network_and_index(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            ctx = _ctx(Path(raw))
            fake = self._run(ctx)
            out = ctx.out / "baseline"
            for slug in ("en", "en-about-us"):
                for name in ("desktop.png", "mobile.png", "page.html", "network.json"):
                    self.assertTrue((out / slug / name).is_file(), f"{slug}/{name}")
            self.assertEqual((out / "en/page.html").read_text().strip(), "<html><body>hi</body></html>")
            index = (out / "INDEX.md").read_text()
            self.assertIn("| `/en` | `en/` | yes | yes | yes | yes |", index)
            self.assertNotIn("broken", index)
            self.assertEqual(ctx.skips, [])
            flat = [" ".join(c) for c in fake.calls]
            self.assertIn("state-load " + str(Path(raw) / "state.json"), flat)
            self.assertIn("resize 1440 900", flat)
            self.assertIn("resize 390 844", flat)
            self.assertIn(
                "goto http://localhost:8080/admin/site/preview/en/draft/en/about us", flat,
            )
            spec = yaml.safe_load((ctx.out / "integrations/openapi.yaml").read_text())
            self.assertEqual(spec["x-observed-hosts"], ["fonts.example.test", "stats.example.test"])
            network = json.loads((out / "en/network.json").read_text())
            self.assertNotIn("key=abc", json.dumps(network))

    def test_site_url_overrides_the_base(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fake = self._run(_ctx(Path(raw), site_url="http://127.0.0.1:9000"))
            self.assertIn(["goto", "http://127.0.0.1:9000/en"], fake.calls)

    def test_missing_binary_records_skip_not_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            ctx = _ctx(Path(raw))
            with mock.patch.object(baseline.shutil, "which", return_value=None):
                EnonicBaselineStep().run(ctx)
            self.assertEqual(len(ctx.skips), 1)
            self.assertIn("playwright-cli", ctx.skips[0]["reason"])
            self.assertIn("npm install", ctx.skips[0]["fix"])
            self.assertFalse((ctx.out / "baseline").exists())

    def test_failed_command_keeps_other_files_and_records_skip(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            ctx = _ctx(Path(raw))
            self._run(ctx, FakePlaywright(fail_on="screenshot"))
            self.assertTrue((ctx.out / "baseline/en/page.html").is_file())
            self.assertFalse((ctx.out / "baseline/en/desktop.png").exists())
            self.assertIn("| `/en` | `en/` | missing | missing | yes | yes |",
                          (ctx.out / "baseline/INDEX.md").read_text())
            self.assertTrue(any("screenshot failed" in s["reason"] for s in ctx.skips))

    def test_a_browser_that_does_not_open_is_written_into_the_index(self) -> None:
        for verb in ("open", "state-load"):
            with self.subTest(verb), tempfile.TemporaryDirectory() as raw:
                ctx = _ctx(Path(raw))
                self._run(ctx, FakePlaywright(fail_on=verb))
                index = (ctx.out / "baseline/INDEX.md").read_text()
                self.assertNotIn("No surveyed pages", index)
                self.assertIn("did not start", index)
                self.assertIn("Failure:", index)
                self.assertIn("Fix:", index)
                self.assertIn("boom", index)

    def test_no_runtime_json_records_skip(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            ctx = _ctx(Path(raw))
            (ctx.out / "inventory/runtime.json").unlink()
            self._run(ctx)
            self.assertIn("runtime.json", ctx.skips[0]["reason"])

    def test_production_site_url_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            ctx = _ctx(Path(raw), site_url="https://www.authentic-scandinavia.com")
            fake = FakePlaywright()
            with (
                mock.patch.object(baseline.subprocess, "run", fake),
                mock.patch.object(baseline.shutil, "which", return_value="/x"),
                self.assertRaises(ExtractkitError) as caught,
            ):
                EnonicBaselineStep().run(ctx)
            self.assertIn("deny-by-default", str(caught.exception))
            self.assertEqual(fake.calls, [])

    def test_secret_values_are_redacted_from_page_html(self) -> None:
        html = (
            '<meta name="csrf-token" content="abc"><meta name="viewport" content="w">'
            '<input name="_csrf" value="zz"><script>var c = {"apiKey": "k1", "title": "Home"};</script>'
        )
        self.assertEqual(
            baseline.redact_html(html),
            '<meta name="csrf-token" content="[redacted]"><meta name="viewport" content="w">'
            '<input name="_csrf" value="[redacted]"><script>var c = {"apiKey": "[redacted]", "title": "Home"};</script>',
        )

    def test_userinfo_site_url_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            ctx = _ctx(Path(raw), site_url="http://prod.example.com\\@localhost:8080")
            fake = FakePlaywright()
            with (
                mock.patch.object(baseline.subprocess, "run", fake),
                mock.patch.object(baseline.shutil, "which", return_value="/x"),
                self.assertRaises(ExtractkitError),
            ):
                EnonicBaselineStep().run(ctx)
            self.assertEqual(fake.calls, [])

    def test_production_host_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            ctx = _ctx(Path(raw), xp_host="https://www.authentic-scandinavia.com")
            fake = FakePlaywright()
            with (
                mock.patch.object(baseline.subprocess, "run", fake),
                mock.patch.object(baseline.shutil, "which", return_value="/x"),
                self.assertRaises(ExtractkitError),
            ):
                EnonicBaselineStep().run(ctx)
            self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
