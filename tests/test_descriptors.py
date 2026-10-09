"""Wider descriptor coverage: filters, processors, errors, admin, webapp, id provider, i18n."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from extractkit_cli.check import check_tree
from extractkit_cli.schema import validate
from steps.enonic.descriptors import collect_resources
from tests.support import (
    FIXTURE,
    REPO,
    STATIC_UNTIL,
    copy_fixture,
    run,
    sidecar_run_dir,
)

RES = "xp/src/main/resources/"


def _rows() -> dict[tuple[str, str], dict]:
    return {(r["kind"], r["name"]): r for r in collect_resources(FIXTURE.resolve())}


class CollectTests(unittest.TestCase):
    def test_every_new_kind_is_collected(self) -> None:
        kinds = {kind for kind, _ in _rows()}
        self.assertTrue({
            "filter", "response-processor", "error", "admin-tool", "admin-widget",
            "webapp", "id-provider", "i18n-bundle",
        } <= kinds)

    def test_filter_comes_from_the_mapping_and_points_at_the_script(self) -> None:
        row = _rows()[("filter", "mini-filter")]
        self.assertEqual(row["path"], RES + "site/filters/mini-filter.js")
        self.assertEqual(row["mapping"], {"filter": "/site/filters/mini-filter.js", "order": "20"})

    def test_unmapped_filter_file_is_still_a_filter(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            site_xml = source / RES / "site/site.xml"
            site_xml.write_text("<site><form/></site>", encoding="utf-8")
            rows = {(r["kind"], r["name"]): r for r in collect_resources(source.resolve())}
            self.assertNotIn("mapping", rows[("filter", "mini-filter")])

    def test_processor_keeps_order_and_script_path(self) -> None:
        row = _rows()[("response-processor", "mini-processor")]
        self.assertEqual(row["order"], "10")
        self.assertEqual(row["path"], RES + "site/processors/mini-processor.js")

    def test_site_and_generic_error_handlers(self) -> None:
        rows = _rows()
        self.assertEqual(rows[("error", "site-error")]["path"], RES + "site/error/error.js")
        self.assertEqual(rows[("error", "error")]["path"], RES + "error/error.js")

    def test_admin_webapp_and_id_provider(self) -> None:
        rows = _rows()
        self.assertEqual(rows[("admin-tool", "mini-tool")]["path"], RES + "admin/tools/mini-tool/mini-tool.xml")
        self.assertEqual(rows[("admin-widget", "mini-widget")]["displayName"], "Mini widget")
        self.assertEqual(rows[("webapp", "webapp")]["path"], RES + "webapp/webapp.js")
        self.assertEqual(rows[("id-provider", "idprovider")]["path"], RES + "idprovider/idprovider.xml")

    def test_service_without_xml_is_found_from_its_controller(self) -> None:
        row = _rows()[("service", "mini-script-only")]
        self.assertEqual(row["path"], RES + "services/mini-script-only/mini-script-only.js")
        self.assertNotIn("form", row)
        self.assertEqual(_rows()[("service", "mini-service")]["path"], RES + "services/mini-service/mini-service.xml")

    def test_site_i18n_bundles_are_their_own_location(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            site_i18n = next(source.rglob("resources/site")) / "i18n"
            site_i18n.mkdir()
            (site_i18n / "phrases.properties").write_text("old.key=Old\n", encoding="utf-8")
            rows = {r["name"]: r for r in collect_resources(source) if r["kind"] == "i18n-bundle"}
            self.assertEqual(sorted(rows), ["phrases", "phrases_no", "site.phrases"])
            self.assertEqual(rows["site.phrases"]["location"], "site/i18n")
            self.assertEqual(rows["site.phrases"]["missingKeys"], [])
            self.assertEqual(rows["phrases"]["missingKeys"], ["mini.only.no"])

    def test_i18n_counts_keys_and_lists_the_gap(self) -> None:
        rows = _rows()
        default = rows[("i18n-bundle", "phrases")]
        norwegian = rows[("i18n-bundle", "phrases_no")]
        self.assertEqual((default["locale"], default["keyCount"]), ("default", 3))
        self.assertEqual(default["missingKeys"], ["mini.only.no"])
        self.assertEqual((norwegian["locale"], norwegian["keyCount"]), ("no", 2))
        self.assertEqual(norwegian["missingKeys"], ["mini.multi", "mini.only.default"])


class SidecarTests(unittest.TestCase):
    def test_new_kinds_reach_maps_contexts_and_pass_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            static = run("run", "--profile", "enonic", "--source", str(source), *STATIC_UNTIL)
            self.assertEqual(static.returncode, 0, static.stderr + static.stdout)
            out = sidecar_run_dir(source)
            static_routes = json.loads((out / "map/route-map.json").read_text())
            result = run(
                "run", "--profile", "enonic", "--source", str(source), "--out", str(out),
                "--from", "maps.merge", "--until", "maps.merge",
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            project = json.loads((out / "map/project-map.json").read_text())
            by_id = {s["id"]: s for s in project["surfaces"]}
            for ident in (
                "com.example.mini:filter:mini-filter",
                "com.example.mini:response-processor:mini-processor",
                "com.example.mini:error:site-error",
                "com.example.mini:admin-tool:mini-tool",
                "com.example.mini:webapp:webapp",
                "com.example.mini:id-provider:idprovider",
                "com.example.mini:i18n-bundle:phrases_no",
            ):
                self.assertIn(ident, by_id)
            contexts = {c["id"]: c for c in json.loads((out / "map/bounded-contexts.json").read_text())["contexts"]}
            self.assertIn("com.example.mini:filter:mini-filter", contexts["routing"]["surfaces"])
            self.assertIn("com.example.mini:admin-tool:mini-tool", contexts["admin"]["surfaces"])
            self.assertIn("com.example.mini:i18n-bundle:phrases", contexts["content"]["surfaces"])
            routes = json.loads((out / "map/route-map.json").read_text())
            validate(routes, "route-map")
            self.assertIn("com.example.mini:admin-widget:mini-widget", {r["id"] for r in routes["routes"]})
            site = by_id["com.example.mini:site:site"]
            self.assertEqual(site["configKeys"], ["fallback", "miniMode"])
            self.assertEqual(site["listeners"], ["custom.booking.paid", "node.pushed"])
            self.assertEqual(by_id["com.example.mini:error:site-error"]["behavior"]["methods"][0]["name"], "handle404")
            self.assertEqual(by_id["com.example.mini:filter:mini-filter"]["behavior"]["methods"][0]["name"], "filter")
            mapping = next(
                r for r in static_routes["routes"]
                if r["id"].endswith("mapping:/site/filters/mini-filter.js")
            )
            self.assertEqual(mapping["stackRef"]["enonic"]["filter"], "/site/filters/mini-filter.js")
            gaps = [p for p in check_tree(out) if "but not in maps" in p]
            self.assertEqual(gaps, [])


class JobSurfaceTests(unittest.TestCase):
    def _static(self, raw: str, overlay: str | None = None) -> tuple[Path, dict]:
        source = copy_fixture(Path(raw))
        if overlay:
            shutil.copytree(REPO / "tests" / "fixtures" / overlay, source, dirs_exist_ok=True)
        result = run("run", "--profile", "enonic", "--source", str(source), *STATIC_UNTIL)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        out = sidecar_run_dir(source)
        project = json.loads((out / "map/project-map.json").read_text())
        return out, {s["id"]: s for s in project["surfaces"]}

    def test_cron_and_init_are_surfaces_in_the_routing_context(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out, by_id = self._static(raw)
            merged = run(
                "run", "--profile", "enonic", "--source", str(out.parent.parent), "--out", str(out),
                "--from", "maps.merge", "--until", "maps.merge",
            )
            self.assertEqual(merged.returncode, 0, merged.stderr + merged.stdout)
            cron = by_id["com.example.mini:cron:mini-cron"]
            self.assertEqual(cron["schedule"]["key"], "miniCron")
            self.assertEqual(cron["tasks"][0]["description"], "MINI_SWEEP")
            self.assertIn("/lib/mini-booking#sweep", [c["call"] for c in cron["starts"]])
            self.assertNotIn("/lib/cron#schedule", [c["call"] for c in cron["starts"]])
            init = by_id["com.example.mini:init:main"]
            self.assertEqual([a["action"] for a in init["actions"]], ["eventLib.listener", "eventLib.listener"])
            listeners = init["behavior"]["listeners"]
            self.assertEqual(listeners[1], {"type": "custom.booking.paid", "line": 11, "calls": ["Booking.sweep"]})
            contexts = {c["id"]: c for c in json.loads((out / "map/bounded-contexts.json").read_text())["contexts"]}
            routing = contexts["routing"]["surfaces"]
            self.assertIn("com.example.mini:cron:mini-cron", routing)
            self.assertIn("com.example.mini:init:main", routing)
            routes = json.loads((out / "map/route-map.json").read_text())
            validate(routes, "route-map")
            self.assertIn("com.example.mini:cron:mini-cron", {r["id"] for r in routes["routes"]})

    def test_a_non_xp_caller_is_a_surface_with_its_crontab_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            _out, by_id = self._static(raw, overlay="external-caller")
            caller = by_id["com.example.mini:external-caller:mini-sweep"]
            self.assertEqual(caller["entry"], "external/mini-sweep.php")
            self.assertEqual(caller["callers"][0]["service"], "mini-service")
            self.assertEqual(caller["schedules"][0]["cron"], "*/15 * * * *")
            self.assertEqual(caller["schedules"][0]["source"], "external/mini.crontab:1")


if __name__ == "__main__":
    unittest.main()
