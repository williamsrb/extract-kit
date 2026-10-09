"""domain.packet: one bounded JSON packet per source module, built from extracted facts only."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from extractkit_cli.schema import validate
from steps.enonic.domain_packet import _without_credentials, module_of
from tests.support import FIXTURE, REPO, STATIC_UNTIL, run, sidecar_run_dir


def _sidecar(parent: Path) -> tuple[Path, Path]:
    source = parent / "legacy"
    shutil.copytree(FIXTURE, source)
    for overlay in ("server-rules", "external-caller"):
        shutil.copytree(REPO / "tests" / "fixtures" / overlay, source, dirs_exist_ok=True)
    for args in (STATIC_UNTIL, None):
        extra = ("--from", "maps.merge", "--until", "spec.kit", "--out", str(sidecar_run_dir(source))) if args is None else args
        result = run("run", "--profile", "enonic", "--source", str(source), *extra)
        if result.returncode != 0:
            raise AssertionError(result.stderr + result.stdout)
    return source, sidecar_run_dir(source)


class ModuleOfTests(unittest.TestCase):
    def test_modules_follow_the_resources_layout(self) -> None:
        self.assertEqual(module_of("lib/modules/checkout/flywire.js"), "lib.modules.checkout")
        self.assertEqual(module_of("lib/util/extra/assets.js"), "lib.util")
        self.assertEqual(module_of("lib/mini.js"), "lib")
        self.assertEqual(module_of("services/getX/getX.js"), "services")
        self.assertEqual(module_of("tasks/t/t.js"), "tasks")
        self.assertEqual(module_of("cron/job/index.js"), "cron")
        self.assertEqual(module_of("main.js"), "main")
        self.assertIsNone(module_of("site/parts/p/p.js"))

    def test_a_packet_url_keeps_no_credentials(self) -> None:
        self.assertEqual(_without_credentials("https://u:p@h.test/a?apiKey=k&x=1"), "https://h.test/a?apiKey=&x=")


class PacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.source, cls.out = _sidecar(Path(cls._tmp.name))
        cls.index = json.loads((cls.out / "domain/packet/INDEX.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _packet(self, module: str) -> dict:
        packet = json.loads((self.out / f"domain/packet/{module}.json").read_text(encoding="utf-8"))
        validate(packet, "domain-packet")
        return packet

    def test_the_index_lists_one_packet_per_module_with_its_size(self) -> None:
        validate(self.index, "domain-packet-index")
        modules = {m["module"]: m for m in self.index["modules"]}
        self.assertEqual(sorted(modules), ["cron", "lib", "main", "services"])
        for row in modules.values():
            self.assertEqual((self.out / row["file"]).stat().st_size, row["bytes"])

    def test_a_lib_packet_has_exports_platform_calls_and_the_rules_inside_it(self) -> None:
        lib = self._packet("lib")
        names = {e["name"] for e in lib["exports"]}
        self.assertTrue({"sweep", "deposit", "canPay", "overdue", "get"} <= names)
        self.assertIn("/lib/xp/context", {p["module"] for p in lib["platform"]} | {u["module"] for u in lib["uses"]})
        rules = {r["expression"]: r for r in lib["rules"]}
        self.assertEqual(rules["total * DEPOSIT_RATE"]["source"], "xp/src/main/resources/lib/mini-pricing.js:7")
        self.assertTrue(all(r["source"].split(":")[0].startswith("xp/src/main/resources/lib/") for r in lib["rules"]))
        self.assertEqual(lib["http"][0]["url"], "https://api.example.test/v1")
        self.assertEqual([j["id"] for j in lib["jobs"]], [j["id"] for j in self._packet("cron")["jobs"]])

    def test_every_use_points_at_a_packet_that_exists(self) -> None:
        modules = {m["module"] for m in self.index["modules"]}
        for row in self.index["modules"]:
            for use in self._packet(row["module"])["uses"]:
                if use["module"].startswith("/lib/"):
                    self.assertIn(use["packet"], modules, use)

    def test_the_cron_packet_names_the_job_schedule_and_what_it_starts(self) -> None:
        job = self._packet("cron")["jobs"][0]
        self.assertEqual(job["schedule"]["key"], "miniCron")
        self.assertEqual(job["tasks"][0]["description"], "MINI_SWEEP")
        self.assertEqual(job["starts"][0]["call"], "/lib/mini-booking#sweep")

    def test_the_main_packet_carries_the_listeners_and_what_they_call(self) -> None:
        listeners = self._packet("main")["listeners"][0]
        self.assertEqual(listeners["source"], "xp/src/main/resources/main.js")
        self.assertEqual([x["type"] for x in listeners["listeners"]], ["node.pushed", "custom.booking.paid"])

    def test_the_services_packet_has_request_facts_and_the_external_caller_with_its_crontab(self) -> None:
        services = self._packet("services")
        post = next(r for r in services["requests"] if r["file"].endswith("mini-service.js"))
        self.assertIn(("param", "bookingId"), {(i["source"], i["name"]) for i in post["inputs"]})
        self.assertIn("role:system.admin", {a["value"] for a in post["auth"] if a["kind"] == "role-check"})
        caller = services["externalCallers"][0]
        self.assertEqual(caller["schedules"][0]["cron"], "*/15 * * * *")

    def test_no_packet_holds_source_text(self) -> None:
        for row in self.index["modules"]:
            text = (self.out / row["file"]).read_text(encoding="utf-8")
            self.assertNotIn("require(", text)
            self.assertNotIn("function (", text)


if __name__ == "__main__":
    unittest.main()
