"""US-005: `extractkit headless` runs the extract with no human, through a fake agent."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

import yaml

from extractkit_cli import cli, headless
from tests.support import REPO, TEST_HOME, copy_fixture, run_checkout
from tests.test_assets import resource, seven
from tests.test_xp_login import PASSWORD, serve

FAKE = REPO / "tests" / "fixtures" / "fake_agent.py"
FAKE_TABLE = {
    "fake": {
        "argv": [sys.executable, str(FAKE)], "allowlist_args": [], "bypass_args": [],
        "allowed_tools": ["Read"], "preflight_tools": ["Read"],
        "api_key_env": "FAKE_TOKEN", "conflicting_env": ["FAKE_CONFLICT"], "env_prefixes": ["FAKE_"],
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
        return max((self.source / "extract").glob("2*"))

    def lines(self) -> list[dict]:
        path = self.sidecar() / "reports" / "headless.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    def overlay(self) -> dict:
        return yaml.safe_load((self.sidecar() / "context" / "profile.yaml").read_text())


USAGE_JSON = {"tokens": ["usage.input_tokens", "usage.output_tokens", "usage.cache_read_input_tokens"],
              "cost_usd": "total_cost_usd"}


class UsageTests(unittest.TestCase):

    def test_json_paths_are_summed(self) -> None:
        text = json.dumps({"result": "x", "total_cost_usd": 0.12345,
                           "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100}})
        self.assertEqual(headless.agent_usage(text, USAGE_JSON), {"tokens": 115, "cost_usd": 0.1235})

    def test_a_regex_reads_plain_text(self) -> None:
        spec = {"tokens_regex": r"tokens used\W+([\d,]+)"}
        self.assertEqual(headless.agent_usage("done\ntokens used\n12,345\n", spec), {"tokens": 12345})

    def test_no_spec_or_no_match_reports_nothing(self) -> None:
        self.assertEqual(headless.agent_usage('{"usage": {"input_tokens": 1}}', None), {})
        self.assertEqual(headless.agent_usage("plain text\n", USAGE_JSON), {})


class StageTests(HeadlessCase):
    def test_context_stage_runs_the_preflight_and_the_context_agent(self) -> None:
        self.assertFalse((self.source / ".serena").exists())
        self.assertFalse((self.source / "graphify-out").exists())
        code, doc = self.headless("--until", "agent:context")
        self.assertEqual(code, 0, doc)
        self.assertTrue(doc["ok"])
        self.assertEqual([s["id"] for s in doc["stages"]], list(headless.STAGES[:6]))
        self.assertTrue((self.source / ".serena" / "project.yml").is_file())
        self.assertTrue((self.source / "graphify-out" / "graph.json").is_file())
        self.assertEqual(self.overlay()["exclude"], ["prototype"])
        self.assertEqual(doc["sidecar"], str(self.sidecar()))
        stage_lines = [line for line in self.lines() if line["task"] is None]
        self.assertEqual([line["stage"] for line in stage_lines], list(headless.STAGES[:6]))
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

    def test_the_sidecar_is_a_visible_folder_with_no_gitignore(self) -> None:
        code, doc = self.headless("--until", "synthesis")
        self.assertEqual(code, 0, doc)
        self.assertEqual(self.sidecar().parent, self.source / "extract")
        self.assertFalse((self.source / ".extract").exists())
        self.assertEqual([p.name for p in (self.source / "extract").iterdir()], [self.sidecar().name])
        scope = json.loads((self.sidecar() / "context" / "build-scope.json").read_text())
        self.assertNotIn("extract", json.dumps(scope))
        static = (self.sidecar() / "inventory" / "static.json").read_text()
        self.assertNotIn("extract/", static)

    def test_progress_goes_to_stderr_and_stdout_stays_json(self) -> None:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, _ = self.headless("--until", "static")
        self.assertEqual(code, 0)
        text = err.getvalue()
        for expected in ("[1/5] install ...", "[5/5] static ok", "step 1/", "done in"):
            self.assertIn(expected, text)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.headless("--until", "static", "-q")
        self.assertEqual(err.getvalue(), "")

    def test_the_summary_carries_durations_and_agent_runs(self) -> None:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            _, doc = self.headless("--until", "agent:context")
        self.assertIn("summary:", err.getvalue())
        self.assertEqual(doc["summary"]["agent_runs"], len(self.agent_runs()))
        self.assertGreater(doc["summary"]["duration_s"], 0)

    def agent_runs(self) -> list[dict]:
        return [l for l in self.lines() if l["message"] == "agent finished"]

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

    def test_a_failed_preflight_keeps_the_agent_log_with_no_sidecar(self) -> None:
        code, doc = self.headless("--until", "preflight", mode="noop")
        self.assertEqual(code, 1, doc)
        self.assertEqual(doc["error"]["code"], "readiness_missing")
        kept = self.source / "extract" / "headless-preflight-preflight-1.log"
        self.assertTrue(kept.is_file())
        self.assertIn(str(kept), doc["error"]["fix"])
        self.assertEqual([p for p in (self.source / "extract").iterdir() if p.is_dir()], [])
        self.assertFalse((self.source / "extract" / ".gitignore").exists())

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

    def test_an_unwritable_source_stops_before_any_stage(self) -> None:
        buffer = io.StringIO()
        os.chdir(self.source)
        try:
            with contextlib.redirect_stdout(buffer), mock.patch.object(headless.os, "access", return_value=False):
                code = cli.main(["headless", "--source", ".", "--agent", "fake", "--json"])
        finally:
            os.chdir(REPO)
        doc = json.loads(buffer.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(doc["error"]["code"], "source_not_writable")
        self.assertIn("--user", doc["error"]["fix"])

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


class AssetsStageTests(HeadlessCase):
    """The `assets` stage reads attachments by content and never fails the run."""

    TOKEN = "tok-SECRET-value"

    def assets(self, **files: str) -> Path:
        folder = self.source.parent / "assets"
        folder.mkdir(exist_ok=True)
        for name, text in files.items():
            (folder / name).write_text(text, encoding="utf-8")
        return folder

    def prepare_readiness(self) -> None:
        (self.source / ".serena" / "memories").mkdir(parents=True)
        (self.source / ".serena" / "project.yml").write_text("p: 1\n", encoding="utf-8")
        (self.source / ".serena" / "memories" / "o.md").write_text("# o\n", encoding="utf-8")
        (self.source / "graphify-out").mkdir()
        (self.source / "graphify-out" / "graph.json").write_text("{}\n", encoding="utf-8")

    def stage(self, doc: dict, name: str) -> dict:
        return next(s for s in doc["stages"] if s["id"] == name)

    def test_the_credential_reaches_only_the_agent_and_the_cms_gets_a_login(self) -> None:
        server = serve("/admin/_/idprovider/system")
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_address[1]}"
        folder = self.assets(
            **{"one.yaml": resource("agent_api_key", token=self.TOKEN, agent="fake"),
               "two.bin": resource("cms_url", url=url, login="su", password=PASSWORD)},
        )
        leaks = {"FAKE_CONFLICT": "x", "OP_SERVICE_ACCOUNT_TOKEN": "optok", "MY_PASSWORD": "pw", "EXTRACTKIT_X": "y"}
        err = io.StringIO()
        env = {**leaks, "FAKE_AGENT_REPORT_ENV": "FAKE_TOKEN," + ",".join(leaks)}
        with mock.patch.dict(os.environ, env), contextlib.redirect_stderr(err):
            code, doc = self.headless(
                "--until", "doctor", "--assets-dir", str(folder),
                "--assets-password-env", "MY_PASSWORD", "--xp-host", url, "--branch", "draft",
            )
        self.assertEqual(code, 0, doc)
        stage = self.stage(doc, "assets")
        self.assertEqual(stage["status"], "ok")
        self.assertIn("logged in to 127.0.0.1", stage["message"])
        seen = json.loads((self.source / "fake-env.json").read_text())
        self.assertEqual(seen["FAKE_TOKEN"], self.TOKEN)
        self.assertEqual({k: v for k, v in seen.items() if k != "FAKE_TOKEN"}, dict.fromkeys(leaks))
        for text in (json.dumps(doc), err.getvalue()):
            self.assertNotIn(self.TOKEN, text)
            self.assertNotIn(PASSWORD, text)

    @unittest.skipUnless(shutil.which("7z"), "7z is not installed")
    def test_a_password_protected_archive_opens_with_a_password_from_the_environment(self) -> None:
        folder = self.assets()
        seven(folder / "locked.7z", "t.yaml", resource("agent_api_key", token=self.TOKEN, agent="fake"), password="pw1")
        with mock.patch.dict(os.environ, {"MY_PW": "pw1", "FAKE_AGENT_REPORT_ENV": "FAKE_TOKEN"}):
            code, doc = self.headless("--until", "agent:context", "--assets-dir", str(folder), "--assets-password-env", "MY_PW")
        self.assertEqual(code, 0, doc)
        self.assertEqual(json.loads((self.source / "fake-env.json").read_text())["FAKE_TOKEN"], self.TOKEN)

    def test_a_missing_credential_skips_the_agent_stages_and_the_run_still_checks(self) -> None:
        self.prepare_readiness()
        folder = self.assets(**{"junk.txt": self.TOKEN, "other.yaml": resource("something_else")})
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, doc = self.headless("--until", "check", "--assets-dir", str(folder), "-q")
        self.assertEqual(code, 0, doc)
        statuses = {s["id"]: s["status"] for s in doc["stages"]}
        for name in ("agent:context", "agent:live_config", "agent"):
            self.assertEqual(statuses[name], "skipped", name)
        for name in ("assets", "preflight", "doctor", "static", "synthesis", "check"):
            self.assertEqual(statuses[name], "ok", name)
        self.assertEqual(doc["summary"]["agent_runs"], 0)
        self.assertIn("junk.txt: ignored", err.getvalue())
        self.assertIn("no credential for agent fake", err.getvalue())
        self.assertNotIn(self.TOKEN, err.getvalue() + json.dumps(doc))

    def test_an_unprepared_checkout_without_a_credential_stops_at_doctor_with_the_cause_printed(self) -> None:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, doc = self.headless("--until", "check", "--assets-dir", str(self.assets()))
        self.assertEqual(code, 1)
        self.assertEqual(doc["error"]["code"], "readiness_missing")
        self.assertIn("Serena onboarding and the Graphify index stay unprepared", err.getvalue())
        self.assertIn("no credential for agent fake", err.getvalue())

    def test_the_job_secrets_never_reach_the_agent_unless_named(self) -> None:
        leaks = {"CI_JOB_TOKEN": "job-secret", "FAKE_AGENT_REPORT_ENV": "CI_JOB_TOKEN,NAMED_EXTRA,FAKE_AGENT_REPORT_ENV",
                 "NAMED_EXTRA": "named"}
        with mock.patch.dict(os.environ, leaks):
            code, doc = self.headless("--until", "preflight", "--agent-env", "NAMED_EXTRA")
        self.assertEqual(code, 0, doc)
        seen = json.loads((self.source / "fake-env.json").read_text())
        self.assertIsNone(seen["CI_JOB_TOKEN"])
        self.assertEqual(seen["NAMED_EXTRA"], "named")

    def test_an_unexpected_failure_while_reading_is_a_problem_and_the_stage_still_passes(self) -> None:
        folder = self.assets(**{"a.yaml": resource("something_else")})
        with mock.patch.object(headless.assets, "collect", side_effect=RuntimeError("boom")):
            code, doc = self.headless("--until", "assets", "--assets-dir", str(folder))
        self.assertEqual(code, 0, doc)
        self.assertIn("could not be processed (RuntimeError)", self.stage(doc, "assets")["message"])

    def test_an_explicit_storage_state_is_not_replaced_by_a_login(self) -> None:
        state = self.source.parent / "state.json"
        state.write_text(json.dumps({"cookies": [], "origins": []}), encoding="utf-8")
        folder = self.assets(**{"c.yaml": resource("cms_url", url="http://127.0.0.1:9", login="a", password="b")})
        code, doc = self.headless("--until", "assets", "--assets-dir", str(folder), "--storage-state", str(state), "--xp-host", "http://127.0.0.1:9")
        self.assertEqual(code, 0, doc)
        self.assertIn("not used", self.stage(doc, "assets")["message"])


class CredentialFallbackTests(HeadlessCase):
    """Several `agent_api_key` resources: probed in priority order, and switched when one stops answering."""

    assets, prepare_readiness, stage = AssetsStageTests.assets, AssetsStageTests.prepare_readiness, AssetsStageTests.stage

    def keys(self, **priorities: int) -> Path:
        files = {f"{name}.yaml": resource("agent_api_key", token=f"tok-{name}", agent="fake", priority=value)
                 for name, value in priorities.items()}
        return self.assets(**files)

    def calls(self) -> list[tuple[str, str]]:
        rows = (self.source / "fake-calls.log").read_text().splitlines()
        return [(row.split()[0], row.split()[1]) for row in rows]

    def test_the_probe_skips_a_dead_credential_and_uses_the_next_in_priority_order(self) -> None:
        folder = self.keys(a=1, b=2, c=3)
        with mock.patch.dict(os.environ, {"FAKE_AGENT_DEAD": "tok-a"}):
            code, doc = self.headless("--until", "agent:context", "--assets-dir", str(folder))
        self.assertEqual(code, 0, doc)
        message = self.stage(doc, "assets")["message"]
        self.assertIn("a.yaml, b.yaml, c.yaml", message)
        self.assertIn("credential 2 of 3 is in use", message)
        used = [token for token, _ in self.calls()]
        self.assertEqual(used[:2], ["tok-a", "tok-b"])  # the probes
        self.assertNotIn("tok-c", used)
        self.assertEqual(set(used[2:]), {"tok-b"})

    def test_one_credential_is_not_probed(self) -> None:
        code, doc = self.headless("--until", "agent:context", "--assets-dir", str(self.keys(a=1)))
        self.assertEqual(code, 0, doc)
        self.assertNotIn("Reply with the single word", (self.source / "fake-calls.log").read_text())

    def test_when_none_answers_the_agent_stages_are_skipped_and_the_cause_is_printed(self) -> None:
        self.prepare_readiness()
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"FAKE_AGENT_DEAD": "tok-a,tok-b"}), contextlib.redirect_stderr(err):
            code, doc = self.headless("--until", "check", "--assets-dir", str(self.keys(a=1, b=2)), "-q")
        self.assertEqual(code, 0, doc)
        self.assertEqual(self.stage(doc, "agent")["status"], "skipped")
        self.assertIn("none of the 2 agent_api_key credentials for agent fake answered", err.getvalue())

    def test_a_credential_that_runs_out_mid_run_hands_the_same_task_to_the_next(self) -> None:
        folder = self.keys(a=1, b=2)
        with mock.patch.dict(os.environ, {"FAKE_AGENT_DIE_ON": "tok-a:context.exclude"}):
            code, doc = self.headless("--until", "agent:context", "--assets-dir", str(folder))
        self.assertEqual(code, 0, doc)
        self.assertEqual(self.overlay()["exclude"], ["prototype"])
        task_calls = [(t, r) for t, r in self.calls() if r != "-" or t == "tok-a"]
        self.assertIn(("tok-b", "resumed"), task_calls)
        switched = [line for line in self.lines() if line.get("code") == "credential_switched"]
        self.assertEqual([line["message"] for line in switched], ["a.yaml -> b.yaml"])
        self.assertEqual(switched[0]["attempt"], 1)
        attempts = [line["attempt"] for line in self.lines() if line.get("task") == "context.exclude" and line["ok"] and line.get("log")]
        self.assertEqual(attempts, [1])  # the run that went on is still attempt 1: no fix attempt was used
        self.assertTrue(any(f.name.endswith("-context.exclude-1-c2.log") for f in (self.sidecar() / "reports" / "headless").iterdir()))

    def test_the_run_stops_with_credentials_exhausted_when_the_last_one_runs_out(self) -> None:
        folder = self.keys(a=1, b=2)
        with mock.patch.dict(os.environ, {"FAKE_AGENT_DIE_ON": "tok-a:context.exclude"}), \
                mock.patch.object(headless.Headless, "_probe", side_effect=[True, False, False]):
            code, doc = self.headless("--until", "agent:context", "--assets-dir", str(folder))
        self.assertEqual(code, 1)
        self.assertEqual(doc["error"]["code"], "credentials_exhausted")
        self.assertIn("finished tasks are kept", doc["error"]["fix"])

    def test_a_failure_the_credential_did_not_cause_is_not_a_switch(self) -> None:
        folder = self.keys(a=1, b=2)
        with mock.patch.object(headless.Headless, "_probe", return_value=True):
            code, doc = self.headless("--until", "agent:context", "--assets-dir", str(folder), mode="crash")
        self.assertEqual(code, 1)
        self.assertEqual(doc["error"]["code"], "agent_failed")

    def test_a_single_credential_that_dies_fails_as_before(self) -> None:
        folder = self.keys(a=1)
        with mock.patch.dict(os.environ, {"FAKE_AGENT_DIE_ON": "tok-a:context.exclude"}):
            code, doc = self.headless("--until", "agent:context", "--assets-dir", str(folder))
        self.assertEqual(code, 1)
        self.assertEqual(doc["error"]["code"], "agent_failed")

    def test_a_json_result_that_reports_an_error_fails_the_probe(self) -> None:
        self.assertTrue(headless._reported_error('{"is_error": true, "result": "limit"}'))
        self.assertFalse(headless._reported_error('{"is_error": false}'))
        self.assertFalse(headless._reported_error("ok"))


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
            "site_url": None, "cms_keys": None, "round2": None, "no_enrich": False,
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

    def test_the_agent_stage_runs_spec_enrich_after_the_required_tasks(self) -> None:
        driver = self._driver()
        with (
            mock.patch.object(driver, "_loop", return_value="ok: ran business") as loop,
            mock.patch.object(driver, "_kit", return_value={"state": "pending"}),
            mock.patch.object(driver, "_run_task") as task,
        ):
            self.assertEqual(driver._agent_stage(), "ok: ran business, spec.enrich")
        loop.assert_called_once_with("agent", only_context=False)
        task.assert_called_once_with("agent", "spec.enrich")

    def test_a_failed_spec_enrich_does_not_stop_the_agent_stage(self) -> None:
        for failure in (
            headless.StageFailed("agent_timeout", "claude ran over 5s on spec.enrich"),
            headless.Blocked("task_blocked", "spec.enrich wrote a blocker"),
        ):
            driver = self._driver()
            with (
                mock.patch.object(driver, "_loop", return_value="ok: ran business"),
                mock.patch.object(driver, "_kit", return_value={"state": "pending"}),
                mock.patch.object(driver, "_run_task", side_effect=failure),
            ):
                message = driver._agent_stage()
            self.assertEqual(message, f"ok: ran business; spec.enrich failed and was skipped: {failure}")

    def test_a_failed_required_task_still_stops_the_agent_stage(self) -> None:
        driver = self._driver()
        failure = headless.StageFailed("agent_failed", "business is still pending")
        with (
            mock.patch.object(driver, "_loop", side_effect=failure),
            mock.patch.object(driver, "_run_task") as task,
            self.assertRaises(headless.StageFailed),
        ):
            driver._agent_stage()
        task.assert_not_called()

    def test_the_agent_stage_skips_spec_enrich_when_done_or_turned_off(self) -> None:
        for driver, state in ((self._driver(), "done"), (self._driver(no_enrich=True), "pending")):
            with (
                mock.patch.object(driver, "_loop", return_value="ok (already done)"),
                mock.patch.object(driver, "_kit", return_value={"state": state}),
                mock.patch.object(driver, "_run_task") as task,
            ):
                self.assertEqual(driver._agent_stage(), "ok (already done)")
            task.assert_not_called()

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

    def test_claude_may_never_lift_the_kit_guards_in_either_mode(self) -> None:
        driver = headless.Headless(Namespace(
            source="/tmp", agent="claude", agent_permissions=None, allowed_tools=None,
            task_timeout=5, max_fix_attempts=2, storage_state=None))
        for permissions in ("allowlist", "bypass"):
            driver.s.permissions = permissions
            argv = driver._argv(driver.s.allowed_tools)
            denied = argv[argv.index("--disallowedTools") + 1]
            with self.subTest(permissions=permissions):
                for pattern in ("Bash(extractkit * --force*)", "Bash(extractkit * --allow-production*)", "Bash(extractkit headless*)"):
                    self.assertIn(pattern, denied)

    def test_the_agent_process_sees_only_what_it_needs_of_the_job_environment(self) -> None:
        job = {
            "PATH": "/bin", "HOME": "/home/x", "LC_ALL": "C", "HTTPS_PROXY": "http://p", "ANTHROPIC_BASE_URL": "u",
            "CI_JOB_TOKEN": "job-secret", "CI_DOCKER_TOKEN": "hub-secret", "AWS_SECRET_ACCESS_KEY": "aws-secret",
            "MY_EXTRA": "extra", "EXTRACTKIT_X": "y",
        }
        driver = headless.Headless(Namespace(
            source="/tmp", agent="claude", agent_permissions=None, allowed_tools=None, task_timeout=5,
            max_fix_attempts=2, storage_state=None, agent_env=["MY_EXTRA"]))
        with mock.patch.dict(os.environ, job, clear=True):
            seen = driver._env(agent=True, restrict=True)
            everything = driver._env()
        self.assertEqual(
            sorted(k for k in seen if k != "PATH"),
            ["ANTHROPIC_BASE_URL", "HOME", "HTTPS_PROXY", "LC_ALL", "MY_EXTRA"],
        )
        self.assertIn("CI_JOB_TOKEN", everything)

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
