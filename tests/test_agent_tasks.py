"""Agent task registry: schema, render, order, done state and the `agent` commands."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from extractkit_cli import agent_tasks, check, manifest, schema
from extractkit_cli.errors import ExtractkitError
from tests.support import REPO, build_sidecar, run, write_agent_outputs

LLM = REPO / "docs" / "llm.md"
RULE = "VR-0123456789"


def _task_dir(parent: Path, task_id: str, *, prompt: str, **fields) -> Path:
    root = parent / "agent-tasks"
    folder = root / task_id
    folder.mkdir(parents=True)
    body = {"id": task_id, "title": "t", "after": "spec.kit", "reads": [], "writes": [], **fields}
    (folder / "task.yaml").write_text(json.dumps(body), encoding="utf-8")
    (folder / "prompt.md").write_text(prompt, encoding="utf-8")
    return root


def _rules(out: Path, *statuses: str, bucket: str = "business") -> None:
    (out / "rules").mkdir(parents=True, exist_ok=True)
    rules = [{"id": f"VR-{i:010x}", "bucket": bucket, "status": s} for i, s in enumerate(statuses)]
    (out / "rules" / "view-rules.json").write_text(json.dumps({"rules": rules}), encoding="utf-8")


class RegistryTests(unittest.TestCase):
    def test_shipped_tasks_load_and_validate(self) -> None:
        tasks = agent_tasks.load()
        self.assertEqual({t.id for t in tasks}, {
            "context.exclude", "context.live_config", "rules.name", "business",
            "constitution", "spec.enrich", "spec.review",
        })
        for task in tasks:
            with self.subTest(task=task.id):
                self.assertTrue(task.prompt.is_file())
                self.assertIn(task.after, manifest.pipeline_ids(manifest.load("core")))
                for name in task.checks:
                    self.assertIn(name, check.NAMED_CHECKS)

    def test_order_follows_the_pipeline_then_the_task_id(self) -> None:
        self.assertEqual(
            [t.id for t in agent_tasks.ordered(manifest.load("enonic"))],
            ["context.exclude", "context.live_config", "rules.name", "business",
             "constitution", "spec.enrich", "spec.review"],
        )

    def test_context_tasks_sit_after_the_slots_they_wait_for(self) -> None:
        by_id = {t.id: t for t in agent_tasks.load()}
        self.assertEqual(by_id["context.exclude"].after, "inventory.integrations")
        self.assertEqual(by_id["context.exclude"].done_check, "exclude_decided")
        self.assertEqual(by_id["context.exclude"].rerun, ("run", "--from", "static", "--until", "synthesis"))
        self.assertEqual(by_id["context.live_config"].after, "inventory.runtime")
        self.assertEqual(by_id["context.live_config"].done_check, "live_config_written")
        self.assertEqual(by_id["context.live_config"].rerun, ("step", "inventory.runtime"))
        for task_id in ("context.exclude", "context.live_config"):
            self.assertEqual(by_id[task_id].writes, ("context/profile.yaml",))
            self.assertEqual(by_id[task_id].checks, ("context_grounded",))

    def test_declared_fields(self) -> None:
        by_id = {t.id: t for t in agent_tasks.load()}
        self.assertEqual(by_id["rules.name"].done_check, "rules_named")
        self.assertEqual(by_id["rules.name"].rerun, ("run", "--from", "merge", "--until", "synthesis"))
        self.assertEqual(by_id["business"].promote, (("business/BUSINESS.md", "BUSINESS.md"),))
        self.assertEqual(by_id["business"].writes, ("business/BUSINESS.md",))
        self.assertTrue(by_id["spec.enrich"].optional)
        self.assertTrue(by_id["spec.review"].optional)
        self.assertEqual(by_id["spec.review"].writes, ("reports/spec-review.md",))
        self.assertEqual(by_id["spec.review"].promote, ())
        self.assertFalse(by_id["business"].optional)

    def test_schema_rejects_an_unknown_field_and_a_missing_one(self) -> None:
        good = {"id": "x", "title": "t", "after": "spec.kit", "reads": [], "writes": []}
        schema.validate(good, "agent-task")
        for bad in ({**good, "surprise": 1}, {k: v for k, v in good.items() if k != "after"},
                    {**good, "done_check": "nope"}):
            with self.assertRaises(ExtractkitError):
                schema.validate(bad, "agent-task")

    def test_prompts_open_with_the_invariants_verbatim(self) -> None:
        invariants = re.search(r"## Invariants\n\n(.*?)\n\n## Command sequence",
                               LLM.read_text(encoding="utf-8"), re.DOTALL).group(1)
        for task in agent_tasks.load():
            with self.subTest(task=task.id):
                self.assertIn(invariants, task.prompt.read_text(encoding="utf-8"))

    def test_folder_name_must_match_id(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = _task_dir(Path(raw), "a", prompt="x")
            (root / "a").rename(root / "b")
            with self.assertRaises(ExtractkitError):
                agent_tasks.load(root)


def _overlay(out: Path, **keys: object) -> None:
    (out / "context").mkdir(exist_ok=True)
    (out / "context" / "profile.yaml").write_text(
        "\n".join(f"{k}: {json.dumps(v)}" for k, v in {"extends": "enonic", **keys}.items()) + "\n",
        encoding="utf-8",
    )


class ContextTaskStateTests(unittest.TestCase):
    """`context.exclude` and `context.live_config` are done by their overlay key."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        _source, cls.template = build_sidecar(Path(cls._tmp.name))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def setUp(self) -> None:
        self._copy_dir = tempfile.TemporaryDirectory()
        self.out = Path(self._copy_dir.name) / "sidecar"
        shutil.copytree(self.template, self.out)
        write_agent_outputs(self.out)

    def tearDown(self) -> None:
        self._copy_dir.cleanup()

    def _pending(self) -> list[str]:
        return [t.id for t in agent_tasks.pending(self.out, manifest.load("enonic"))]

    def test_exclude_is_pending_until_the_overlay_has_the_key(self) -> None:
        _overlay(self.out)
        self.assertEqual(self._pending(), ["context.exclude"])
        self.assertEqual(agent_tasks.next_task(self.out, manifest.load("enonic")).id, "context.exclude")
        _overlay(self.out, exclude=[])
        self.assertEqual(self._pending(), [])

    def test_a_sidecar_without_a_context_phase_leaves_exclude_pending_and_blocked(self) -> None:
        shutil.rmtree(self.out / "context")
        self.assertEqual(self._pending(), ["context.exclude"])
        self.assertIsNone(agent_tasks.next_task(self.out, manifest.load("enonic")))

    def test_live_config_is_done_without_a_live_harvest(self) -> None:
        self.assertFalse((self.out / "inventory" / "live-config-candidates.json").exists())
        _overlay(self.out, exclude=[])
        self.assertEqual(self._pending(), [])

    def test_live_config_is_pending_while_candidates_exist_and_the_key_is_missing(self) -> None:
        (self.out / "inventory" / "live-config-candidates.json").write_text("[]\n", encoding="utf-8")
        (self.out / "inventory" / "runtime.json").write_text("{}\n", encoding="utf-8")
        _overlay(self.out, exclude=[])
        self.assertEqual(self._pending(), ["context.live_config"])
        self.assertEqual(agent_tasks.next_task(self.out, manifest.load("enonic")).id, "context.live_config")
        _overlay(self.out, exclude=[], live_config={})
        self.assertEqual(self._pending(), [])


class RenderTests(unittest.TestCase):
    def test_substitutes_the_four_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = _task_dir(Path(raw), "a", prompt="{sidecar}|{source}|{profile}|{run_id}")
            (task,) = agent_tasks.load(root)
            out = Path(raw) / "legacy" / ".extract" / "run1"
            out.mkdir(parents=True)
            self.assertEqual(
                agent_tasks.render(task, out, profile="enonic"),
                f"{out}|{Path(raw) / 'legacy'}|enonic|run1",
            )

    def test_unknown_placeholder_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = _task_dir(Path(raw), "a", prompt="{sidecar} {nope}")
            (task,) = agent_tasks.load(root)
            with self.assertRaises(ExtractkitError) as caught:
                agent_tasks.render(task, Path(raw))
            self.assertIn("{nope}", str(caught.exception))

    def test_shipped_prompts_render(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            for task in agent_tasks.load():
                with self.subTest(task=task.id):
                    text = agent_tasks.render(task, Path(raw))
                    self.assertNotRegex(text, r"\{(sidecar|source|profile|run_id)\}")


class DoneStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.by_id = {t.id: t for t in agent_tasks.load()}

    def test_rules_name_needs_view_rules(self) -> None:
        self.assertFalse(agent_tasks.is_done(self.by_id["rules.name"], self.out))

    def test_rules_name_waits_for_an_extracted_business_rule(self) -> None:
        _rules(self.out, "named", "extracted")
        self.assertFalse(agent_tasks.is_done(self.by_id["rules.name"], self.out))

    def test_rules_name_is_done_once_every_business_rule_is_named(self) -> None:
        _rules(self.out, "named", "confirmed")
        self.assertTrue(agent_tasks.is_done(self.by_id["rules.name"], self.out))

    def test_presentational_rules_do_not_block(self) -> None:
        _rules(self.out, "extracted", bucket="presentational")
        self.assertTrue(agent_tasks.is_done(self.by_id["rules.name"], self.out))

    def test_review_md_alone_proves_nothing(self) -> None:
        (self.out / "rules").mkdir()
        (self.out / "rules" / "review.md").write_text("# Rule review\n", encoding="utf-8")
        self.assertFalse(agent_tasks.is_done(self.by_id["rules.name"], self.out))

    def test_business_is_done_when_its_file_exists(self) -> None:
        self.assertFalse(agent_tasks.is_done(self.by_id["business"], self.out))
        (self.out / "business").mkdir()
        (self.out / "business" / "BUSINESS.md").write_text("# x\n", encoding="utf-8")
        self.assertTrue(agent_tasks.is_done(self.by_id["business"], self.out))

    def test_spec_enrich_is_optional_and_never_pending(self) -> None:
        self.assertFalse(agent_tasks.is_done(self.by_id["spec.enrich"], self.out))
        self.assertNotIn("spec.enrich", [t.id for t in agent_tasks.pending(self.out)])

    def test_spec_enrich_is_done_while_its_report_is_newer_than_every_spec(self) -> None:
        task = self.by_id["spec.enrich"]
        spec = self.out / "spec-kit" / "specs" / "content" / "spec.md"
        spec.parent.mkdir(parents=True)
        spec.write_text("# x\n", encoding="utf-8")
        report = self.out / "reports" / "spec-enrich.md"
        report.parent.mkdir()
        report.write_text("# Spec enrich\nStatus: complete\n", encoding="utf-8")
        os.utime(spec, (1000, 1000))
        os.utime(report, (2000, 2000))
        self.assertTrue(agent_tasks.is_done(task, self.out))
        os.utime(spec, (3000, 3000))
        self.assertFalse(agent_tasks.is_done(task, self.out))

    def test_a_spec_enrich_report_without_the_complete_line_is_a_ledger_not_a_finish(self) -> None:
        task = self.by_id["spec.enrich"]
        spec = self.out / "spec-kit" / "specs" / "content" / "spec.md"
        spec.parent.mkdir(parents=True)
        spec.write_text("# x\n", encoding="utf-8")
        report = self.out / "reports" / "spec-enrich.md"
        report.parent.mkdir()
        report.write_text("# Spec enrich\nStatus: in progress\n- content/spec.md FR-1\n", encoding="utf-8")
        os.utime(spec, (1000, 1000))
        os.utime(report, (2000, 2000))
        self.assertFalse(agent_tasks.is_done(task, self.out))

    def test_spec_review_is_optional_and_never_pending(self) -> None:
        task = self.by_id["spec.review"]
        self.assertFalse(agent_tasks.is_done(task, self.out))
        self.assertNotIn("spec.review", [t.id for t in agent_tasks.pending(self.out)])
        (self.out / "reports").mkdir()
        (self.out / "reports" / "spec-review.md").write_text("# Spec review\n\nNo findings.\n", encoding="utf-8")
        self.assertTrue(agent_tasks.is_done(task, self.out))
        self.assertNotIn("spec.review", [t.id for t in agent_tasks.pending(self.out)])
        self.assertEqual(agent_tasks.promotions(self.out), [])

    def test_promotions_follow_the_registry(self) -> None:
        self.assertEqual(agent_tasks.promotions(self.out), [])
        (self.out / "business").mkdir()
        (self.out / "business" / "BUSINESS.md").write_text("# x\n", encoding="utf-8")
        self.assertEqual(
            agent_tasks.promotions(self.out),
            [(self.out / "business" / "BUSINESS.md", Path("BUSINESS.md"))],
        )


class AgentCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.source, cls.out = build_sidecar(Path(cls._tmp.name))

    def _copy(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dest = Path(tmp.name) / "sidecar"
        shutil.copytree(self.out, dest)
        return dest

    def test_list_json_shape(self) -> None:
        result = run("agent", "list", "--out", str(self.out), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["next"], "business")
        rows = {t["id"]: t for t in payload["tasks"]}
        self.assertEqual(list(rows), [
            "context.exclude", "context.live_config", "rules.name", "business",
            "constitution", "spec.enrich", "spec.review",
        ])
        self.assertEqual(rows["context.exclude"]["state"], "done")
        self.assertEqual(rows["context.live_config"]["state"], "done")
        self.assertEqual(rows["rules.name"]["state"], "done")
        self.assertEqual(rows["business"]["state"], "pending")
        self.assertEqual(rows["business"]["missing_reads"], [])
        self.assertTrue(rows["spec.enrich"]["optional"])
        self.assertTrue(rows["spec.review"]["optional"])
        self.assertEqual(rows["rules.name"]["rerun"], ["run", "--from", "merge", "--until", "synthesis"])

    def test_list_text(self) -> None:
        result = run("agent", "list", "--out", str(self.out))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"rules\.name\s+done")
        self.assertRegex(result.stdout, r"business\s+pending, next")
        self.assertRegex(result.stdout, r"spec\.enrich\s+optional")

    def test_show_prints_the_prompt_with_real_paths_and_inputs(self) -> None:
        result = run("agent", "show", "business", "--out", str(self.out))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"`{self.out}`", result.stdout)
        self.assertIn(f"`{self.source}`", result.stdout)
        self.assertNotRegex(result.stdout, r"\{(sidecar|source|profile|run_id)\}")
        self.assertIn(f"- {self.out / 'map' / 'bounded-contexts.json'}", result.stdout)

    def test_show_json(self) -> None:
        payload = json.loads(run("agent", "show", "business", "--out", str(self.out), "--json").stdout)
        self.assertEqual(payload["id"], "business")
        self.assertIn("## Invariants", payload["prompt"])
        self.assertTrue(all(i["exists"] for i in payload["inputs"]))
        self.assertEqual(payload["writes"], ["business/BUSINESS.md"])

    def test_show_unknown_task_names_the_available_ones(self) -> None:
        result = run("agent", "show", "nope", "--out", str(self.out))
        self.assertEqual(result.returncode, 1)
        self.assertIn("rules.name, business, constitution, spec.enrich, spec.review", result.stderr)

    def test_show_spec_review_renders_and_lists_the_missing_business_input(self) -> None:
        result = run("agent", "show", "spec.review", "--out", str(self.out))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"`{self.out}`", result.stdout)
        self.assertNotRegex(result.stdout, r"\{(sidecar|source|profile|run_id)\}")
        self.assertIn("business/BUSINESS.md  (missing)", result.stdout)

    def test_next_names_the_first_pending_task_and_points_at_show(self) -> None:
        result = run("agent", "next", "--out", str(self.out))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("next task business", result.stdout)
        self.assertIn(f"agent show business --out {self.out}", result.stdout)

    def test_next_json_and_done(self) -> None:
        out = self._copy()
        first = json.loads(run("agent", "next", "--out", str(out), "--json").stdout)
        self.assertEqual(first["next"]["id"], "business")
        self.assertEqual(first["pending"], ["business", "constitution"])
        write_agent_outputs(out)
        done = json.loads(run("agent", "next", "--out", str(out), "--json").stdout)
        self.assertEqual((done["next"], done["pending"], done["blocked"]), (None, [], []))
        text = run("agent", "next", "--out", str(out))
        self.assertIn("no required task is pending", text.stdout)
        self.assertIn(f"check --out {out}", text.stdout)

    def test_next_reports_a_task_whose_inputs_are_missing_instead_of_skipping_it(self) -> None:
        out = self._copy()
        (out / "map" / "route-map.json").unlink()
        payload = json.loads(run("agent", "next", "--out", str(out), "--json").stdout)
        self.assertIsNone(payload["next"])
        self.assertEqual(payload["blocked"], [
            {"id": "business", "missing_reads": ["map/route-map.json"]},
            {"id": "constitution", "missing_reads": ["business/BUSINESS.md", "map/route-map.json"]},
        ])
        text = run("agent", "next", "--out", str(out))
        self.assertEqual(text.returncode, 0)
        self.assertIn("business is waiting on map/route-map.json", text.stdout)

    def test_status_shows_nine_phases_with_the_agent_phase_current(self) -> None:
        result = run("status", "--out", str(self.out))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"→ 7 agent\s+pending business, constitution · skills: extract-agentic")
        self.assertRegex(result.stdout, r"· 8 check")
        self.assertRegex(result.stdout, r"· 9 promote")
        self.assertIn("next  [7/9] Agent is next:", result.stdout)
        self.assertIn("agent next --out", result.stdout)

    def test_status_returns_to_check_once_the_required_tasks_are_done(self) -> None:
        out = self._copy()
        write_agent_outputs(out)
        result = run("status", "--out", str(out))
        self.assertRegex(result.stdout, r"✓ 7 agent\s*\n")
        self.assertRegex(result.stdout, r"→ 8 check")
        self.assertIn("next  [8/9] Check the extract tree (CMS was not captured):", result.stdout)
        self.assertIn("or add CMS data and rebuild merge and synthesis:", result.stdout)

    def test_run_from_agent_is_refused_and_names_the_command(self) -> None:
        result = run("run", "--profile", "enonic", "--source", str(self.source), "--from", "agent")
        self.assertEqual(result.returncode, 1)
        self.assertIn("agent phase", result.stderr)
        self.assertIn("extractkit agent next --out <sidecar>", result.stderr)

    def test_step_agent_is_refused_too(self) -> None:
        result = run("step", "agent", "--profile", "enonic", "--source", str(self.source))
        self.assertEqual(result.returncode, 1)
        self.assertIn("extractkit agent next --out <sidecar>", result.stderr)

    def test_doctor_accepts_the_agent_phase(self) -> None:
        result = run("doctor", "--profile", "enonic")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
