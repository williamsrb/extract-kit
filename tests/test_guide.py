"""Guided output: phases, argv rewrite, body renderer, tips, next transitions."""

from __future__ import annotations

import os
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from extractkit_cli import guide, manifest
from extractkit_cli.errors import ExtractkitError
from extractkit_cli.runner import _bound_pipeline, _slice_pipeline
from tests.support import REPO, STATIC_UNTIL, copy_fixture, run

PLAIN = guide.Style(colour=False, unicode=True)


def _profile(phases: list[dict], pipeline=("a", "b", "c")) -> dict:
    return {"name": "t", "pipeline": list(pipeline), "adapters": {}, "phases": phases}


class PhaseModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.enonic = manifest.load("enonic")

    def test_resolve_by_id_and_number(self) -> None:
        self.assertEqual(guide.resolve_phase(self.enonic, "static").number, 2)
        self.assertEqual(guide.resolve_phase(self.enonic, "5").id, "synthesis")

    def test_resolve_unknown_is_none(self) -> None:
        self.assertIsNone(guide.resolve_phase(self.enonic, "nope"))
        self.assertIsNone(guide.resolve_phase(self.enonic, "9"))

    def test_command_phase_has_no_slots(self) -> None:
        check = guide.resolve_phase(self.enonic, "check")
        self.assertEqual((check.number, check.command, check.slots), (7, "check", ()))

    def test_agent_phase_sits_between_synthesis_and_check(self) -> None:
        agent = guide.resolve_phase(self.enonic, "agent")
        self.assertEqual((agent.number, agent.command, agent.slots), (6, "agent", ()))
        self.assertEqual(
            [p.id for p in guide.phases(self.enonic)][4:],
            ["synthesis", "agent", "check", "promote"],
        )

    def test_phase_of_slot(self) -> None:
        self.assertEqual(guide.phase_of(self.enonic, "inventory.runtime").id, "cms")

    def test_real_profiles_have_no_phase_problems(self) -> None:
        for name in manifest.available():
            self.assertEqual(guide.phase_problems(manifest.load(name)), [], name)

    def test_slot_in_no_phase(self) -> None:
        problems = guide.phase_problems(_profile([{"id": "x", "title": "X", "slots": ["a", "b"]}]))
        self.assertEqual(problems, ["pipeline slot 'c' is in no phase"])

    def test_slot_in_two_phases(self) -> None:
        problems = guide.phase_problems(_profile([
            {"id": "x", "title": "X", "slots": ["a", "b"]},
            {"id": "y", "title": "Y", "slots": ["b", "c"]},
        ]))
        self.assertEqual(problems, ["pipeline slot 'b' is in more than one phase: x, y"])

    def test_unknown_slot(self) -> None:
        problems = guide.phase_problems(_profile([
            {"id": "x", "title": "X", "slots": ["a", "b", "c", "zzz"]},
        ]))
        self.assertEqual(problems, ["phase 'x' names unknown slot 'zzz'"])

    def test_duplicate_id(self) -> None:
        problems = guide.phase_problems(_profile([
            {"id": "x", "title": "X", "slots": ["a"]},
            {"id": "x", "title": "X2", "slots": ["b", "c"]},
        ]))
        self.assertEqual(problems, ["phase id 'x' is declared twice"])


class SliceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = manifest.load("enonic")
        self.rows = _bound_pipeline(self.profile)

    def _slots(self, rows) -> list[str]:
        return [slot for slot, _ in rows]

    def test_until_static_stops_after_integrations(self) -> None:
        rows = _slice_pipeline(self.rows, None, "static", profile=self.profile)
        self.assertEqual(self._slots(rows)[-1], "inventory.integrations")
        self.assertEqual(len(rows), 7)

    def test_phase_range_equals_slot_range(self) -> None:
        by_phase = _slice_pipeline(self.rows, "merge", "synthesis", profile=self.profile)
        by_slot = _slice_pipeline(self.rows, "maps.merge", "report.compat", profile=self.profile)
        self.assertEqual(by_phase, by_slot)

    def test_step_phase_number_runs_every_slot(self) -> None:
        rows = _slice_pipeline(self.rows, None, None, only="2", profile=self.profile)
        self.assertEqual(len(rows), 7)

    def test_step_slot_id_keeps_single_slot(self) -> None:
        rows = _slice_pipeline(self.rows, None, None, only="maps.merge", profile=self.profile)
        self.assertEqual(rows, [("maps.merge", "maps.merge")])

    def test_command_phase_is_refused_with_command_fix(self) -> None:
        for token, fix in (
            ("7", "extractkit check --out <sidecar>"),
            ("agent", "extractkit agent next --out <sidecar>"),
        ):
            with self.subTest(token=token), self.assertRaises(ExtractkitError) as caught:
                _slice_pipeline(self.rows, token, None, profile=self.profile)
            self.assertIn(fix, caught.exception.fix)

    def test_unknown_token_lists_phases(self) -> None:
        with self.assertRaises(ExtractkitError) as caught:
            _slice_pipeline(self.rows, "nope", None, profile=self.profile)
        self.assertIn("static (2)", caught.exception.fix)


class RewriteTests(unittest.TestCase):
    def test_flag_value_replaced(self) -> None:
        argv = ["run", "--profile", "enonic", "--until", "static"]
        self.assertEqual(
            guide.rewrite(argv, set={"--until": "merge"}),
            ["run", "--profile", "enonic", "--until", "merge"],
        )

    def test_inline_flag_keeps_its_form(self) -> None:
        argv = ["run", "--profile=enonic", "--until=static"]
        self.assertEqual(
            guide.rewrite(argv, set={"--until": "merge"}),
            ["run", "--profile=enonic", "--until=merge"],
        )

    def test_boolean_add_and_remove(self) -> None:
        argv = ["run", "--tasks", "--profile", "enonic"]
        self.assertEqual(
            guide.rewrite(argv, set={"--force": None}, drop=("--tasks",)),
            ["run", "--profile", "enonic", "--force"],
        )

    def test_clustered_short_flags_take_no_value(self) -> None:
        argv = ["run", "-vq", "--profile", "enonic", "--source", "legacy"]
        self.assertEqual(
            guide.rewrite(argv, command="resume"),
            ["resume", "-vq", "--profile", "enonic", "--source", "legacy"],
        )

    def test_subcommand_swap_drops_positional(self) -> None:
        argv = ["step", "static", "--profile", "enonic", "--source", "legacy"]
        self.assertEqual(
            guide.rewrite(argv, command="resume"),
            ["resume", "--profile", "enonic", "--source", "legacy"],
        )

    def test_default_only_when_absent(self) -> None:
        argv = ["status", "--source", "legacy"]
        self.assertEqual(
            guide.rewrite(argv, command="resume",
                          default={"--profile": "enonic", "--source": "other"}),
            ["resume", "--profile", "enonic", "--source", "legacy"],
        )

    def test_path_under_cwd_becomes_relative(self) -> None:
        out = Path.cwd() / "legacy" / ".extract" / "run1"
        self.assertEqual(
            guide.rewrite(["check"], set={"--out": str(out)}),
            ["check", "--out", "legacy/.extract/run1"],
        )

    def test_join_quotes_spaces_but_not_placeholders(self) -> None:
        tokens = ["./extractkit", "run", "--source", "my legacy",
                  "--storage-state", "<playwright-state.json>"]
        self.assertEqual(
            guide.join(tokens),
            "./extractkit run --source 'my legacy' --storage-state <playwright-state.json>",
        )

    def test_prog_display_relative_launcher(self) -> None:
        cwd = os.getcwd()
        try:
            os.chdir(REPO)
            with mock.patch.object(guide.shutil, "which", return_value=None):
                self.assertEqual(guide.prog_display(str(REPO / "extractkit")), "./extractkit")
            self.assertEqual(guide.prog_display("-c"), "extractkit")
        finally:
            os.chdir(cwd)

    def test_prog_display_is_bare_once_installed_on_path(self) -> None:
        link = str(REPO / "extractkit")
        with mock.patch.object(guide.shutil, "which", return_value=link):
            self.assertEqual(guide.prog_display(link), "extractkit")
            self.assertEqual(guide.prog_display("extractkit"), "extractkit")


class RendererTests(unittest.TestCase):
    def _report(self, out: Path, extra_writes: int = 0) -> guide.Report:
        actions = [
            guide.Action(None, f"write {out.parent / '.gitignore'} (*)"),
            guide.Action("map.code", "skip map.code: no graft/ index (fix: run graft build)"),
            guide.Action("enonic.descriptors", f"write {out / 'inventory/static.json'}"),
            guide.Action("maps.normalize", f"write {out / 'map/project-map.json'}"),
            guide.Action("maps.normalize", f"write {out / 'map/component-map.json'}"),
            guide.Action("maps.normalize", f"write {out / 'map/content-model.json'}"),
            guide.Action("maps.normalize", f"write {out / 'map/route-map.json'}"),
            guide.Action("enonic.docs", "harvest 2 source doc file(s) into docs/harvest/"),
            guide.Action("enonic.docs", f"write {out / 'docs/harvest/INDEX.md'}"),
            guide.Action(None, f"write {out / 'MANIFEST.yaml'}"),
        ]
        actions.extend(
            guide.Action("enonic.docs", f"write {out / f'docs/harvest/x{i}.md'}")
            for i in range(extra_writes)
        )
        return guide.Report(
            profile=manifest.load("enonic"),
            out=out,
            out_existed=False,
            rows=[
                ("map.code", "map.code"),
                ("inventory.descriptors", "enonic.descriptors"),
                ("maps.normalize", "maps.normalize"),
                ("inventory.docs", "enonic.docs"),
            ],
            actions=actions,
            skips=[{"step": "map.code", "reason": "no graft/ index", "fix": "run graft build"}],
        )

    def test_compact_body_exact_text(self) -> None:
        out = Path("/nowhere/legacy/.extract/run1")
        lines, truncated = guide.render_body(self._report(out), verbose=False, style=PLAIN)
        self.assertEqual(lines, [
            "extractkit · enonic · sidecar /nowhere/legacy/.extract/run1 (new)",
            "",
            "[2/8] Static inventory",
            "  – map.code               skipped: no graft/ index",
            "  ✓ inventory.descriptors  inventory/static.json",
            (
                "  ✓ maps.normalize         map/project-map.json, map/component-map.json, "
                "map/content-model.json, +1 more"
            ),
            "",
            "[4/8] Merge",
            "  ✓ inventory.docs         docs/harvest/INDEX.md",
            "  8 files written",
        ])
        self.assertTrue(truncated)

    def test_summary_does_not_count(self) -> None:
        out = Path("/nowhere/run1")
        actions = self._report(out).actions
        self.assertEqual(guide.write_count(actions), 8)

    def test_tips_skip_fix_then_verbose_hint(self) -> None:
        out = Path("/nowhere/run1")
        report = self._report(out)
        _, truncated = guide.render_body(report, verbose=False, style=PLAIN)
        self.assertEqual(
            guide.tips(report, truncated),
            ["map.code: run graft build", "Add -v to list every path."],
        )

    def test_no_tips_when_nothing_triggers(self) -> None:
        report = self._report(Path("/nowhere/run1"))
        report.skips = []
        self.assertEqual(guide.tips(report, False), [])

    def test_verbose_lists_every_action_and_setup(self) -> None:
        out = Path("/nowhere/run1")
        lines, truncated = guide.render_body(self._report(out), verbose=True, style=PLAIN)
        text = "\n".join(lines)
        self.assertFalse(truncated)
        self.assertIn("      harvest 2 source doc file(s) into docs/harvest/", text)
        self.assertIn("      write /nowhere/run1/map/route-map.json", text)
        self.assertIn("setup\n      write /nowhere/.gitignore (*)", text)

    def test_ascii_glyph_fallback(self) -> None:
        style = guide.Style(colour=False, unicode=False)
        self.assertEqual(style.glyph("done").strip(), "ok")
        self.assertEqual(style.glyph("skip"), "skip")

    def test_colour_only_when_enabled(self) -> None:
        self.assertNotIn("\033", PLAIN.glyph("done"))
        self.assertIn("\033[32m", guide.Style(colour=True, unicode=True).glyph("done"))


class NextTransitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = manifest.load("enonic")
        self.out = Path("/nowhere/legacy/.extract/run1")

    def _args(self, *argv: str, **extra) -> Namespace:
        return Namespace(argv=list(argv), prog_display="./extractkit", **extra)

    def _run(self, state: str, *argv: str) -> guide.Suggestion:
        args = self._args(*(argv or ("run", "--profile", "enonic", "--source", "legacy",
                                     "--until", "static")))
        return guide.next_for("run", state, args, self.profile, self.out)

    def test_cms_next_adds_branch_and_storage_state(self) -> None:
        s = self._run("cms")
        self.assertEqual(guide.join(s.argv), (
            "./extractkit resume --profile enonic --source legacy "
            "--out /nowhere/legacy/.extract/run1 --branch draft "
            "--storage-state <playwright-state.json>"
        ))
        self.assertEqual(s.alt_reason, "continue without CMS")
        self.assertEqual(guide.join(s.alt_argv), (
            "./extractkit run --profile enonic --source legacy "
            "--out /nowhere/legacy/.extract/run1 --from merge --until synthesis"
        ))

    def test_cms_next_keeps_existing_state_file(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".json") as state:
            s = self._run("cms", "run", "--profile", "enonic", "--source", "legacy",
                          "--branch", "master", "--storage-state", state.name)
        joined = guide.join(s.argv)
        self.assertIn(f"--branch master --storage-state {state.name}", joined)
        self.assertNotIn("<playwright-state.json>", joined)
        self.assertNotIn("--branch", guide.join(s.alt_argv))

    def test_other_next_is_resume_without_range(self) -> None:
        s = self._run("other:maps.merge", "run", "--profile", "enonic", "--source", "legacy",
                      "--from", "cms", "--until", "cms", "--branch", "draft")
        self.assertEqual(s.reason, "[4/8] Merge is next:")
        self.assertEqual(guide.join(s.argv), (
            "./extractkit resume --profile enonic --source legacy --branch draft "
            "--out /nowhere/legacy/.extract/run1"
        ))
        self.assertIsNone(s.alt_argv)

    def test_offline_route_suggests_check_or_cms_rebuild(self) -> None:
        with mock.patch("extractkit_cli.agent_tasks.pending", return_value=[]):
            s = self._run("offline", "run", "--profile", "enonic", "--source", "legacy",
                          "--out", "x", "--from", "merge", "--until", "synthesis")
        self.assertEqual(guide.join(s.argv), "./extractkit check --out /nowhere/legacy/.extract/run1")
        self.assertEqual(guide.join(s.alt_argv), (
            "./extractkit run --profile enonic --source legacy "
            "--out /nowhere/legacy/.extract/run1 --from cms --until synthesis "
            "--branch draft --storage-state <playwright-state.json>"
        ))

    def test_complete_suggests_check(self) -> None:
        with mock.patch("extractkit_cli.agent_tasks.pending", return_value=[]):
            s = self._run("complete")
        self.assertEqual(guide.join(s.argv), "./extractkit check --out /nowhere/legacy/.extract/run1")
        self.assertIsNone(s.alt_argv)

    def test_complete_and_offline_point_at_the_agent_while_a_task_is_pending(self) -> None:
        for state in ("complete", "offline"):
            with self.subTest(state=state):
                s = self._run(state)
                self.assertEqual(s.reason, "[6/8] Agent is next:")
                self.assertEqual(
                    guide.join(s.argv),
                    "./extractkit agent next --out /nowhere/legacy/.extract/run1",
                )
                self.assertEqual(s.alt_reason, "skip to check")
                self.assertEqual(
                    guide.join(s.alt_argv),
                    "./extractkit check --out /nowhere/legacy/.extract/run1",
                )

    def test_other_states_ignore_the_agent(self) -> None:
        s = self._run("cms")
        self.assertIn("resume", guide.join(s.argv))

    def test_status_derives_source_from_sidecar(self) -> None:
        args = self._args("next", "--out", str(self.out))
        s = guide.next_for("status", "other:maps.merge", args, self.profile, self.out)
        self.assertEqual(guide.join(s.argv), (
            "./extractkit resume --profile enonic --source /nowhere/legacy "
            "--out /nowhere/legacy/.extract/run1"
        ))

    def test_status_outside_extract_uses_placeholder(self) -> None:
        out = Path("/nowhere/sidecar")
        args = self._args("status", "--out", str(out), "--profile", "enonic")
        with mock.patch("extractkit_cli.agent_tasks.pending", return_value=[]):
            s = guide.next_for("status", "complete", args, self.profile, out)
        self.assertEqual(guide.join(s.argv), "./extractkit check --out /nowhere/sidecar")
        s = guide.next_for("status", "other:maps.merge", args, self.profile, out)
        self.assertIn("--source <legacy-checkout>", guide.join(s.argv))

    def test_check_clean_suggests_promote(self) -> None:
        args = self._args("check", "--out", str(self.out))
        s = guide.next_for("check", "clean", args, out=self.out)
        self.assertEqual(guide.join(s.argv), (
            "./extractkit promote --source /nowhere/legacy --out /nowhere/legacy/.extract/run1"
        ))

    def test_check_problems_suggests_rerun(self) -> None:
        args = self._args("check", "--out", str(self.out))
        s = guide.next_for("check", "problems", args, out=self.out)
        self.assertEqual(s.reason, "re-run after fixing the problems above")
        self.assertEqual(guide.join(s.argv), "./extractkit check --out /nowhere/legacy/.extract/run1")

    def test_promote_suggests_git_status(self) -> None:
        s = guide.next_for("promote", "done", self._args("promote"),
                           source=Path("/nowhere/legacy"))
        self.assertEqual(guide.join(s.argv), "git -C /nowhere/legacy status")

    def test_doctor_and_deps_pick_a_runnable_profile(self) -> None:
        for command, argv, profile in (
            ("doctor", ["doctor"], None),
            ("doctor", ["doctor", "--profile", "php"], "php"),
            ("deps", ["deps", "--profile", "enonic"], "enonic"),
            ("deps", ["deps"], "core"),
        ):
            s = guide.next_for(command, "clean", self._args(*argv, profile=profile))
            self.assertEqual(guide.join(s.argv), (
                "./extractkit run --profile enonic --source <legacy-checkout> --until static"
            ), argv)

    def test_clean_doctor_with_a_source_runs_that_source(self) -> None:
        args = self._args("doctor", "--profile", "enonic", "--source", "legacy",
                          profile="enonic", source="legacy")
        s = guide.next_for("doctor", "clean", args)
        self.assertEqual(guide.join(s.argv), (
            "./extractkit run --profile enonic --source legacy --until static"
        ))

    def test_doctor_problems_have_no_next(self) -> None:
        self.assertIsNone(guide.next_for("doctor", "problems", self._args("doctor")))

    def test_doctor_problems_with_a_fix_point_at_it_and_a_rerun(self) -> None:
        args = self._args("doctor", "--profile", "enonic", "--source", "legacy", "-q")
        s = guide.next_for("doctor", "problems", args, fix="run `graft build` in legacy")
        self.assertEqual(s.reason, "run `graft build` in legacy, then re-run:")
        self.assertEqual(guide.join(s.argv), (
            "./extractkit doctor --profile enonic --source legacy -q"
        ))


class CliOutputTests(unittest.TestCase):
    def test_missing_branch_prints_pasteable_fix(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            result = run("run", "--profile", "enonic", "--source", str(source))
        self.assertEqual(result.returncode, 1)
        self.assertIn("error: enonic.cms requires --branch", result.stderr)
        self.assertIn(
            f"fix:   $ extractkit run --profile enonic --source {source} --branch draft",
            result.stderr,
        )
        self.assertIn("hint:  pass --branch draft", result.stderr)

    def test_piped_run_has_no_ansi_and_ends_with_next(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            result = run("run", "--profile", "enonic", "--source", str(source), *STATIC_UNTIL)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("\033", result.stdout)
        self.assertIn("[2/8] Static inventory", result.stdout)
        self.assertIn("tip   map.code:", result.stdout)
        self.assertIn("next  [3/8] CMS needs a local XP", result.stdout)
        self.assertIn("  or continue without CMS:", result.stdout)

    def test_quiet_suppresses_tips_only(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            result = run("run", "--profile", "enonic", "--source", str(source),
                         *STATIC_UNTIL, "-q")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("tip ", result.stdout)
        self.assertIn("next  ", result.stdout)


if __name__ == "__main__":
    unittest.main()
