"""US-005: `extractkit headless` runs the extract with no human, through a fake agent."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

import yaml

from extractkit_cli import cli, headless
from tests.support import REPO, TEST_HOME, copy_fixture, run_checkout

FAKE = REPO / "tests" / "fixtures" / "fake_agent.py"
FAKE_TABLE = {
    "fake": {
        "argv": [sys.executable, str(FAKE)], "allowlist_args": [], "bypass_args": [],
        "allowed_tools": ["Read"], "preflight_tools": ["Read"],
    },
}
CI = "build:\n  script:\n    - cd xp && ./gradlew build\n"


def make_source(parent: Path) -> Path:
    """The fixture, a CI build that names `xp`, and two folders no build names; no indexes."""
    source = copy_fixture(parent)
    (source / ".gitlab-ci.yml").write_text(CI, encoding="utf-8")
    for folder, name in (("prototype", "index.html"), ("external", "cron.php")):
        (source / folder).mkdir()
        (source / folder / name).write_text("x\n", encoding="utf-8")
    return source


class HeadlessCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.source = make_source(Path(tmp.name))
        env = {
            "HOME": str(TEST_HOME),
            "PATH": f"{TEST_HOME / '.local' / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
        }
        for patcher in (
            mock.patch.dict(os.environ, env),
            mock.patch.object(headless, "agent_table", return_value=FAKE_TABLE),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def headless(self, *args: str, mode: str = "ok") -> tuple[int, dict]:
        buffer = io.StringIO()
        previous = os.getcwd()
        os.chdir(self.source)
        try:
            with mock.patch.dict(os.environ, {"FAKE_AGENT_MODE": mode}), contextlib.redirect_stdout(buffer):
                code = cli.main(["headless", "--source", ".", "--agent", "fake", "--json", *args])
        finally:
            os.chdir(previous)
        return code, json.loads(buffer.getvalue())

    def sidecar(self) -> Path:
        return max((self.source / ".extract").glob("2*"))

    def lines(self) -> list[dict]:
        path = self.sidecar() / "reports" / "headless.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    def overlay(self) -> dict:
        return yaml.safe_load((self.sidecar() / "context" / "profile.yaml").read_text())


class StageTests(HeadlessCase):
    def test_context_stage_runs_the_preflight_and_the_context_agent(self) -> None:
        self.assertFalse((self.source / ".serena").exists())
        self.assertFalse((self.source / "graphify-out").exists())
        code, doc = self.headless("--until", "agent:context")
        self.assertEqual(code, 0, doc)
        self.assertTrue(doc["ok"])
        self.assertEqual([s["id"] for s in doc["stages"]], list(headless.STAGES[:5]))
        self.assertTrue((self.source / ".serena" / "project.yml").is_file())
        self.assertTrue((self.source / "graphify-out" / "graph.json").is_file())
        self.assertEqual(self.overlay()["exclude"], ["prototype"])
        self.assertEqual(doc["sidecar"], str(self.sidecar()))
        stage_lines = [line for line in self.lines() if line["task"] is None]
        self.assertEqual([line["stage"] for line in stage_lines], list(headless.STAGES[:5]))
        tasks = [line for line in self.lines() if line["task"]]
        self.assertEqual([(t["stage"], t["task"], t["attempt"]) for t in tasks],
                         [("preflight", "preflight", 1), ("agent:context", "context.exclude", 1)])
        for line in tasks:
            self.assertTrue((self.sidecar() / line["log"]).is_file(), line)

    def test_offline_run_reaches_synthesis_without_a_cms_branch(self) -> None:
        code, doc = self.headless("--until", "synthesis")
        self.assertEqual(code, 0, doc)
        stages = {s["id"]: s for s in doc["stages"]}
        self.assertEqual(stages["cms"]["status"], "skipped")
        self.assertIn("offline", stages["cms"]["message"])
        self.assertNotIn("missing_branch", json.dumps(doc))
        manifest = yaml.safe_load((self.sidecar() / "MANIFEST.yaml").read_text())
        self.assertEqual(manifest["exclude"], ["prototype"])
        self.assertTrue((self.sidecar() / "inventory" / "static.json").is_file())

    def test_a_second_run_resumes_and_runs_no_agent(self) -> None:
        self.assertEqual(self.headless("--until", "synthesis")[0], 0)
        before = [line for line in self.lines() if line["task"]]
        code, doc = self.headless("--until", "synthesis")
        self.assertEqual(code, 0, doc)
        stages = {s["id"]: s["message"] for s in doc["stages"]}
        for name in ("preflight", "static", "agent:context", "agent:live_config", "synthesis"):
            self.assertIn("already done", stages[name], name)
        self.assertEqual([line for line in self.lines() if line["task"]], before)

    def test_a_blocker_stops_the_run_with_exit_3(self) -> None:
        code, doc = self.headless("--until", "agent:context", mode="block")
        # the preflight is not a task: it does not block, the context task does
        self.assertEqual(code, 3, doc)
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["exit"], 3)
        self.assertEqual(doc["error"]["code"], "task_blocked")
        blocker = self.sidecar() / "reports" / "blockers" / "context.exclude.md"
        self.assertIn("Reason:", blocker.read_text())
        self.assertEqual(doc["stages"][-1]["status"], "blocked")

    def test_fix_attempts_run_out_into_a_driver_written_blocker(self) -> None:
        # `noop` leaves the preflight undone too, so seed the indexes the way an earlier run would
        (self.source / ".serena" / "memories").mkdir(parents=True)
        (self.source / ".serena" / "project.yml").write_text("x: 1\n")
        (self.source / ".serena" / "memories" / "m.md").write_text("x\n")
        (self.source / "graphify-out").mkdir()
        (self.source / "graphify-out" / "graph.json").write_text("{}")
        code, doc = self.headless("--until", "agent:context", "--max-fix-attempts", "1", mode="noop")
        self.assertEqual(code, 3, doc)
        self.assertEqual(doc["error"]["code"], "task_blocked")
        blocker = (self.sidecar() / "reports" / "blockers" / "context.exclude.md").read_text()
        self.assertIn("written by headless", blocker)
        attempts = [line["attempt"] for line in self.lines() if line["task"] == "context.exclude"]
        self.assertEqual(attempts, [1, 2])

    def test_a_hung_agent_is_killed_at_the_timeout(self) -> None:
        code, doc = self.headless("--task-timeout", "1", mode="sleep")
        self.assertEqual(code, 1, doc)
        self.assertEqual(doc["error"]["code"], "agent_timeout")

    def test_a_crashing_agent_fails_with_agent_failed(self) -> None:
        code, doc = self.headless(mode="crash")
        self.assertEqual(code, 1, doc)
        self.assertEqual(doc["error"]["code"], "agent_failed")

    def test_an_unknown_agent_lists_the_table(self) -> None:
        buffer = io.StringIO()
        os.chdir(self.source)
        try:
            with contextlib.redirect_stdout(buffer):
                code = cli.main(["headless", "--source", ".", "--agent", "nope", "--json"])
        finally:
            os.chdir(REPO)
        doc = json.loads(buffer.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(doc["error"]["code"], "unknown_agent")
        self.assertIn("fake", doc["error"]["fix"])

    def test_the_resources_file_supplies_the_agent_and_the_timeout(self) -> None:
        resources = self.source.parent / "resources.yaml"
        resources.write_text(yaml.safe_dump({"agent": {"cli": "fake", "timeout_seconds": 7}}))
        buffer = io.StringIO()
        os.chdir(self.source)
        try:
            with contextlib.redirect_stdout(buffer), mock.patch.dict(os.environ, {"FAKE_AGENT_MODE": "ok"}):
                code = cli.main(["headless", "--source", ".", "--resources", str(resources),
                                 "--until", "preflight", "--json"])
        finally:
            os.chdir(REPO)
        doc = json.loads(buffer.getvalue())
        self.assertEqual(code, 0, doc)
        config = {row["name"]: row for row in doc["config"]}
        self.assertEqual(config["--agent"]["origin"], "file")
        self.assertEqual(config["--task-timeout"]["value"], 7)


class RefusalTests(unittest.TestCase):
    def test_headless_is_guarded(self) -> None:
        result = run_checkout("headless", "--source", str(REPO / "tests" / "fixtures" / "enonic-mini"), "--json")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "kit_workspace")

    def test_a_bad_stage_is_a_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = run_checkout("headless", "--source", ".", "--until", "bogus", cwd=Path(raw))
        self.assertEqual(result.returncode, 2)
        self.assertIn("not a stage", result.stderr)


class LoopTests(unittest.TestCase):
    """The agent loop and the driver's flag handling, with `_kit` and `_agent` mocked."""

    def _driver(self, **overrides: object) -> headless.Headless:
        base = {
            "source": "/tmp", "agent": "fake", "profile": None, "exclude": [], "resources": None,
            "promote": False, "max_fix_attempts": 2, "task_timeout": 5, "until": None,
            "agent_permissions": None, "allowed_tools": None, "branch": None, "xp_host": None,
            "guillotine": None, "project": None, "storage_state": None, "configenv": None,
            "site_url": None, "cms_keys": None, "round2": None,
        }
        base.update(overrides)
        with mock.patch.object(headless, "agent_table", return_value=FAKE_TABLE):
            driver = headless.Headless(Namespace(**base))
        driver.out = Path("/tmp/sidecar")
        return driver

    def test_a_final_stage_with_blocked_tasks_fails_with_task_inputs_missing(self) -> None:
        driver = self._driver()
        blocked = {"next": None, "blocked": [{"id": "rules.name", "missing_reads": ["maps/merged.json"]},
                                             {"id": "business", "missing_reads": ["rules/view-rules.json"]}]}
        with mock.patch.object(driver, "_kit", return_value=blocked), \
                self.assertRaises(headless.StageFailed) as caught:
            driver._loop("agent", only_context=False)
        self.assertEqual(caught.exception.code, "task_inputs_missing")
        self.assertEqual(caught.exception.exit, 1)
        self.assertIn("rules.name", str(caught.exception))
        self.assertIn("maps/merged.json", str(caught.exception))

    def test_a_context_stage_ignores_blocked_and_later_tasks(self) -> None:
        driver = self._driver()
        for doc in ({"next": None, "blocked": [{"id": "rules.name", "missing_reads": ["x"]}]},
                    {"next": {"id": "rules.name"}, "blocked": []}):
            with mock.patch.object(driver, "_kit", return_value=doc):
                self.assertIn("already done", driver._loop("agent:context", only_context=True))

    def test_a_task_that_stays_pending_cannot_loop_forever(self) -> None:
        driver = self._driver()
        pending = {"next": {"id": "business"}, "blocked": []}
        with (
            mock.patch.object(driver, "_kit", return_value=pending),
            mock.patch.object(driver, "_run_task"),
            self.assertRaises(headless.StageFailed),
        ):
            driver._loop("agent", only_context=False)

    def test_cms_flags_are_carried_only_online_and_never_include_allow_production(self) -> None:
        offline = self._driver(branch="draft", project="en")
        self.assertEqual(offline._cms(), [])
        online = self._driver(branch="draft", project="en", storage_state="/s.json", cms_keys=["/a", "/b"],
                              allow_production=True)
        flags = online._cms()
        self.assertEqual(flags[flags.index("--branch") + 1], "draft")
        self.assertEqual(flags.count("--cms-key"), 2)
        self.assertNotIn("--allow-production", flags)

    def test_children_get_no_extractkit_variables(self) -> None:
        driver = self._driver()
        with mock.patch.dict(os.environ, {"EXTRACTKIT_STORAGE_STATE_JSON": "{}", "EXTRACTKIT_UNTIL": "static", "KEEP": "1"}):
            env = driver._env()
        self.assertNotIn("EXTRACTKIT_STORAGE_STATE_JSON", env)
        self.assertNotIn("EXTRACTKIT_UNTIL", env)
        self.assertEqual(env["KEEP"], "1")

    def test_permissions_pick_the_allowlist_or_the_bypass_args(self) -> None:
        table = {"fake": {"argv": ["agent", "-p"], "allowlist_args": ["--tools", "{allowed_tools}"],
                          "bypass_args": ["--yolo"], "allowed_tools": ["Read", "Edit"], "preflight_tools": []}}
        for permissions, expected in (("allowlist", ["agent", "-p", "--tools", "Read,Edit"]),
                                      (None, ["agent", "-p", "--tools", "Read,Edit"]),
                                      ("bypass", ["agent", "-p", "--yolo"])):
            with self.subTest(permissions=permissions), \
                    mock.patch.object(headless, "agent_table", return_value=table):
                driver = headless.Headless(Namespace(
                    source="/tmp", agent="fake", agent_permissions=permissions, allowed_tools=None,
                    task_timeout=5, max_fix_attempts=2, storage_state=None))
                self.assertEqual(driver._argv(driver.s.allowed_tools), expected)

    def test_the_shipped_agents_build_a_stdin_command_per_permission_mode(self) -> None:
        table = headless.agent_table()
        self.assertEqual(sorted(table), ["claude", "codex", "cursor"])
        for name, binary in (("claude", "claude"), ("codex", "codex"), ("cursor", "cursor-agent")):
            driver = headless.Headless(Namespace(
                source="/tmp", agent=name, agent_permissions=None, allowed_tools=None,
                task_timeout=5, max_fix_attempts=2, storage_state=None))
            allowlist = driver._argv(driver.s.allowed_tools)
            driver.s.permissions = "bypass"
            bypass = driver._argv(driver.s.allowed_tools)
            with self.subTest(agent=name):
                self.assertEqual(allowlist[0], binary)
                self.assertNotEqual(allowlist, bypass)
                self.assertFalse([a for a in allowlist + bypass if "{" in a])

    def test_the_offline_rerun_is_split_around_the_cms_phase(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = make_source(Path(raw))
            driver = self._driver(source=str(source))
            with mock.patch.dict(os.environ, {"HOME": str(TEST_HOME)}):
                out = source / ".extract" / "x"
                (out / "context").mkdir(parents=True)
                (out / "context" / "profile.yaml").write_text("extends: enonic\n")
                driver.out = out
                self.assertEqual(
                    driver._split_rerun(["run", "--from", "static", "--until", "synthesis"]),
                    [["run", "--from", "static", "--until", "static"], ["run", "--from", "merge", "--until", "synthesis"]],
                )
                self.assertEqual(driver._split_rerun(["run", "--from", "merge", "--until", "synthesis"]),
                                 [["run", "--from", "merge", "--until", "synthesis"]])
                self.assertEqual(driver._split_rerun(["step", "inventory.runtime"]), [["step", "inventory.runtime"]])


if __name__ == "__main__":
    unittest.main()
