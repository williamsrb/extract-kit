"""Agent task registry: schema, render, order, done state and the `agent` commands."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from extractkit_cli import agent_tasks, check, manifest, schema
from extractkit_cli.errors import ExtractkitError
from tests.support import REPO, build_sidecar, run, valid_business

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
        self.assertEqual({t.id for t in tasks}, {"rules.name", "business", "spec.enrich"})
        for task in tasks:
            with self.subTest(task=task.id):
                self.assertTrue(task.prompt.is_file())
                self.assertIn(task.after, manifest.pipeline_ids(manifest.load("core")))
                for name in task.checks:
                    self.assertIn(name, check.NAMED_CHECKS)

    def test_order_is_rules_then_business_then_spec_enrich(self) -> None:
        self.assertEqual(
            [t.id for t in agent_tasks.ordered(manifest.load("enonic"))],
            ["rules.name", "business", "spec.enrich"],
        )

    def test_declared_fields(self) -> None:
        by_id = {t.id: t for t in agent_tasks.load()}
        self.assertEqual(by_id["rules.name"].done_check, "rules_named")
        self.assertEqual(by_id["rules.name"].rerun, ("run", "--from", "merge", "--until", "synthesis"))
        self.assertEqual(by_id["business"].promote, (("business/BUSINESS.md", "BUSINESS.md"),))
        self.assertEqual(by_id["business"].writes, ("business/BUSINESS.md",))
        self.assertTrue(by_id["spec.enrich"].optional)
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
        self.assertEqual(list(rows), ["rules.name", "business", "spec.enrich"])
        self.assertEqual(rows["rules.name"]["state"], "done")
        self.assertEqual(rows["business"]["state"], "pending")
        self.assertEqual(rows["business"]["missing_reads"], [])
        self.assertTrue(rows["spec.enrich"]["optional"])
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
        self.assertIn("rules.name, business, spec.enrich", result.stderr)

    def test_next_names_the_first_pending_task_and_points_at_show(self) -> None:
        result = run("agent", "next", "--out", str(self.out))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("next task business", result.stdout)
        self.assertIn(f"agent show business --out {self.out}", result.stdout)

    def test_next_json_and_done(self) -> None:
        out = self._copy()
        first = json.loads(run("agent", "next", "--out", str(out), "--json").stdout)
        self.assertEqual(first["next"]["id"], "business")
        self.assertEqual(first["pending"], ["business"])
        (out / "business").mkdir()
        (out / "business" / "BUSINESS.md").write_text(valid_business(), encoding="utf-8")
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
        self.assertEqual(payload["blocked"], [{"id": "business", "missing_reads": ["map/route-map.json"]}])
        text = run("agent", "next", "--out", str(out))
        self.assertEqual(text.returncode, 0)
        self.assertIn("business is waiting on map/route-map.json", text.stdout)

    def test_status_shows_eight_phases_with_the_agent_phase_current(self) -> None:
        result = run("status", "--out", str(self.out))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"→ 6 agent\s+pending business · skills: extract-agentic")
        self.assertRegex(result.stdout, r"· 7 check")
        self.assertRegex(result.stdout, r"· 8 promote")
        self.assertIn("next  [6/8] Agent is next:", result.stdout)
        self.assertIn("agent next --out", result.stdout)

    def test_status_returns_to_check_once_the_required_tasks_are_done(self) -> None:
        out = self._copy()
        (out / "business").mkdir()
        (out / "business" / "BUSINESS.md").write_text(valid_business(), encoding="utf-8")
        result = run("status", "--out", str(out))
        self.assertRegex(result.stdout, r"✓ 6 agent\s*\n")
        self.assertRegex(result.stdout, r"→ 7 check")
        self.assertIn("next  [7/8] Check the extract tree (CMS was not captured):", result.stdout)
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
