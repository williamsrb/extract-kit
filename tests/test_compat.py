"""enonic.compat: facts only, outside spec-kit/, not promoted."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from steps.enonic import compat
from steps.enonic.compat import render_report
from tests.support import (
    FIXTURE,
    STATIC_UNTIL,
    copy_fixture,
    git_init,
    run,
    sidecar_run_dir,
)

OFFLINE = Path.home() / ".agents" / "kb" / "offline-reference"


def _static(parent: Path) -> tuple[Path, Path]:
    source = copy_fixture(parent)
    result = run("run", "--profile", "enonic", "--source", str(source), *STATIC_UNTIL)
    assert result.returncode == 0, result.stderr + result.stdout
    return source, sidecar_run_dir(source)


class CompatStepTests(unittest.TestCase):
    def test_step_writes_report_outside_spec_kit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source, out = _static(Path(raw))
            result = run(
                "step", "report.compat", "--profile", "enonic", "--source", str(source),
                "--out", str(out),
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            report = out / "reports" / "xp8-compat.md"
            self.assertTrue(report.is_file())
            self.assertFalse(list((out / "spec-kit").rglob("xp8-compat*")))
            text = report.read_text()
            self.assertIn("| content-type | 1 |", text)
            self.assertIn("| admin-widget | 1 |", text)
            self.assertIn("| application | 1 |", text)
            self.assertIn("Total XML descriptors: 14.", text)
            self.assertIn("Services and tasks without an XML descriptor: 1 service.", text)
            self.assertIn("`/lib/xp/content`", text)
            self.assertIn("lowercase exports", text)
            self.assertIn("mini-part.js:14", text)
            self.assertIn("filter `mini-filter`", text)
            self.assertIn("response processor `mini-processor` order 10", text)
            self.assertIn("`/site/filters/mini-filter.js`", text)

    def test_every_table_row_and_item_links_a_doc_page(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source, out = _static(Path(raw))
            run("step", "report.compat", "--profile", "enonic", "--source", str(source), "--out", str(out))
            lines = (out / "reports/xp8-compat.md").read_text().splitlines()
            rows = [ln for ln in lines if ln.startswith("| ") and not ln.startswith(("| kind", "| module", "| location", "|---"))]
            self.assertTrue(rows)
            unlinked = [ln for ln in rows if "](https://developer.enonic.com/docs/" not in ln]
            self.assertEqual(unlinked, [])

    def test_report_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source, out = _static(Path(raw))
            args = ("step", "report.compat", "--profile", "enonic", "--source", str(source), "--out", str(out))
            run(*args)
            first = (out / "reports/xp8-compat.md").read_text()
            run(*args)
            self.assertEqual(first, (out / "reports/xp8-compat.md").read_text())

    def test_promote_ignores_the_report(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source, out = _static(Path(raw))
            git_init(source)
            (out / "reports").mkdir()
            (out / "reports/xp8-compat.md").write_text("# x\n", encoding="utf-8")
            (out / "spec-kit").mkdir()
            (out / "spec-kit/constitution.md").write_text("# c\n", encoding="utf-8")
            result = run("promote", "--source", str(source), "--out", str(out))
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertFalse((source / "reports").exists())
            self.assertTrue((source / ".specify/memory/constitution.md").is_file())

    def test_missing_static_inventory_records_a_skip(self) -> None:
        from extractkit_cli import manifest
        from extractkit_cli.common import Plan
        from extractkit_cli.runner import RunContext

        with tempfile.TemporaryDirectory() as raw:
            ctx = RunContext(
                source=FIXTURE, out=Path(raw), profile=manifest.load("enonic"),
                plan=Plan(), run_id="t",
            )
            compat.EnonicCompatStep().run(ctx)
            self.assertEqual(len(ctx.skips), 1)
            self.assertFalse((Path(raw) / "reports").exists())


class RenderTests(unittest.TestCase):
    def _controller(self, calls: list[tuple[str, str, int]], methods: list[str] | None = None) -> dict:
        return {
            "file": "x/a.js", "folder": "x", "kind": "part", "name": "a", "app": "a",
            "imports": [{"module": m, "line": 1} for m in sorted({m for _, m, _ in calls})],
            "calls": [{"call": c, "module": m, "line": n} for c, m, n in calls],
            "methods": [{"name": n, "line": 1} for n in methods or []],
            "views": [],
        }

    def test_rows_quote_the_page_and_name_removal_only_where_it_does(self) -> None:
        controllers = [self._controller([
            ("c.setPermissions", "/lib/xp/content", 3),
            ("c.query", "/lib/xp/content", 4),
            ("n.modify", "/lib/xp/node", 5),
        ])]
        text = render_report(FIXTURE.resolve(), [], controllers)
        self.assertIn("`setPermissions` is removed. Use `applyPermissions` instead.", text)
        self.assertIn("`modify` is deprecated. Use `update` instead.", text)
        self.assertNotIn("query` is removed", text)
        removed = [ln for ln in text.splitlines() if "removed" in ln and ln.startswith("|")]
        self.assertEqual(len(removed), 1)

    def test_site_i18n_bundle_and_lib_task_submit_are_flagged(self) -> None:
        resources = [{"kind": "i18n-bundle", "name": "site.phrases", "location": "site/i18n"}]
        controllers = [self._controller([("t.submit", "/lib/xp/task", 3)])]
        text = render_report(FIXTURE.resolve(), resources, controllers)
        self.assertIn("| i18n-bundle in site/i18n | 1 |", text)
        self.assertIn("`/site/i18n/phrases` bundle location", text)
        self.assertIn("`submit` is removed. Use `executeFunction` instead.", text)

    def test_unknown_module_makes_no_claim(self) -> None:
        controllers = [self._controller([("x.thing", "/lib/xp/brand-new", 2)])]
        text = render_report(FIXTURE.resolve(), [], controllers)
        self.assertIn("| `/lib/xp/brand-new` | 1 | 1 | no page in the offline XP8 index | no section |", text)
        self.assertNotIn("brand-new` is", text)

    def test_lowercase_exports_and_all(self) -> None:
        controllers = [self._controller([], ["get", "all", "POST"])]
        text = render_report(FIXTURE.resolve(), [], controllers)
        self.assertIn("1 lowercase exports", text)
        self.assertNotIn("`all` at", text)

    def test_every_cited_page_exists_in_the_offline_index(self) -> None:
        if not OFFLINE.is_dir():
            self.skipTest("offline reference not available")
        pages = {p for p, _, _ in compat.DESCRIPTORS.values()}
        pages |= {p for p, _, _ in compat.SCRIPT_KINDS.values()}
        pages |= {p for p, _ in compat.SITE_ITEMS}
        pages |= {compat.LIB_PAGE.format(leaf=leaf) for leaf in compat.LIB_LEAVES}
        missing = sorted(p for p in pages if not (OFFLINE / p).is_file())
        self.assertEqual(missing, [])
        upgrade = (OFFLINE / compat.UPGRADE).read_text(encoding="utf-8")
        for section in {s for _, s, _ in compat.DESCRIPTORS.values()}:
            self.assertIn(f"### {section}", upgrade, section)
        for leaf in compat.LIB_SECTIONS:
            self.assertRegex(upgrade, rf"#{{3,4}} lib-{re.escape(leaf)}\b")


if __name__ == "__main__":
    unittest.main()
