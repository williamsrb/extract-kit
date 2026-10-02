"""The context phase: stack detection, the build scope, and the overlay it writes."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from extractkit_cli import context
from extractkit_cli.errors import ExtractkitError
from tests.support import (
    AS_OVERLAY,
    STATIC_UNTIL,
    build_sidecar,
    copy_fixture,
    run,
    sidecar_run_dir,
)
from tests.test_cms import PAGE_AS_JSON, _storage_state, graphql_server

CI = "build:\n  script:\n    - cd xp && ./gradlew build\n"


def as_like(parent: Path) -> Path:
    """The fixture plus a CI build that names `xp`, and two folders no build names."""
    source = copy_fixture(parent)
    (source / ".gitlab-ci.yml").write_text(CI, encoding="utf-8")
    (source / "prototype").mkdir()
    (source / "prototype" / "index.html").write_text("<p>old</p>\n", encoding="utf-8")
    (source / "external").mkdir()
    (source / "external" / "cron.php").write_text("<?php\n", encoding="utf-8")
    return source


def overlay_of(out: Path) -> dict:
    return yaml.safe_load((out / "context" / "profile.yaml").read_text(encoding="utf-8"))


class DetectStackTests(unittest.TestCase):
    def test_the_enonic_fixture_is_enonic(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            self.assertEqual(context.detect_stack(copy_fixture(Path(raw))), "enonic")

    def test_composer_json_at_the_root_is_php(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            (Path(raw) / "composer.json").write_text("{}\n", encoding="utf-8")
            self.assertEqual(context.detect_stack(Path(raw)), "php")

    def test_an_excluded_folder_does_not_count(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            self.assertEqual(context.detect_stack(source), "enonic")
            with self.assertRaises(ExtractkitError):
                context.detect_stack(source, ["xp"])

    def test_no_marker_names_the_profile_flag(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(ExtractkitError) as caught:
                context.detect_stack(Path(raw))
            self.assertEqual(caught.exception.fix_args, {"--profile": "enonic"})

    def test_markers_for_both_stacks_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            (source / "composer.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaises(ExtractkitError) as caught:
                context.detect_stack(source)
            self.assertIn("more than one stack", str(caught.exception))
            self.assertEqual(caught.exception.fix_args, {"--profile": "enonic"})

    def test_run_without_a_marker_fails_with_a_profile_fix(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = run("run", "--source", raw, *STATIC_UNTIL)
        self.assertEqual(result.returncode, 1)
        self.assertIn("no stack marker", result.stderr)
        self.assertIn("--profile enonic", result.stderr)


class ContextCommandTests(unittest.TestCase):
    def test_out_of_scope_folders_are_reported_and_not_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = as_like(Path(raw))
            result = run("context", "--source", str(source))
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            out = sidecar_run_dir(source)
            found = json.loads((out / "context" / "build-scope.json").read_text(encoding="utf-8"))
            self.assertEqual(found["entry_points"], [".gitlab-ci.yml"])
            self.assertEqual(found["in_scope"], ["xp"])
            self.assertEqual(found["out_of_scope"], ["external", "prototype"])
            overlay = overlay_of(out)
            self.assertEqual(overlay["extends"], "enonic")
            self.assertNotIn("exclude", overlay)
            self.assertIn("context.exclude", result.stdout)

    def test_a_source_with_no_build_file_has_nothing_to_decide(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            result = run("context", "--source", str(source))
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(overlay_of(sidecar_run_dir(source))["exclude"], [])

    def test_a_build_with_nothing_outside_it_has_nothing_to_decide(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            (source / ".gitlab-ci.yml").write_text(CI, encoding="utf-8")
            run("context", "--source", str(source))
            self.assertEqual(overlay_of(sidecar_run_dir(source))["exclude"], [])

    def test_a_rerun_refreshes_the_scope_and_keeps_the_agents_keys(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = as_like(Path(raw))
            run("context", "--source", str(source))
            out = sidecar_run_dir(source)
            decided = overlay_of(out)
            decided["exclude"] = ["prototype"]
            decided["live_config"] = {"site_url_keys": ["x"]}
            (out / "context" / "profile.yaml").write_text(yaml.safe_dump(decided), encoding="utf-8")
            (source / "external" / "cron.php").unlink()
            (source / "external").rmdir()
            result = run("context", "--source", str(source), "--out", str(out))
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            again = overlay_of(out)
            self.assertEqual(again["exclude"], ["prototype"])
            self.assertEqual(again["live_config"], {"site_url_keys": ["x"]})
            found = json.loads((out / "context" / "build-scope.json").read_text(encoding="utf-8"))
            self.assertEqual(found["out_of_scope"], ["prototype"])

    def test_the_context_phase_cannot_be_stepped(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = run("step", "context", "--source", str(copy_fixture(Path(raw))))
        self.assertEqual(result.returncode, 1)
        self.assertIn("extractkit context --source", result.stderr)


class RunWithoutProfileTests(unittest.TestCase):
    def test_run_detects_the_stack_and_records_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = as_like(Path(raw))
            result = run("run", "--source", str(source), *STATIC_UNTIL)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            out = sidecar_run_dir(source)
            manifest = yaml.safe_load((out / "MANIFEST.yaml").read_text(encoding="utf-8"))
            self.assertEqual(manifest["source"]["profile"], "enonic")
            self.assertEqual(manifest["context"]["layers"], [str(out / "context" / "profile.yaml")])
            self.assertEqual(overlay_of(out)["extends"], "enonic")
            self.assertNotIn("exclude", overlay_of(out))
            status = run("status", "--source", str(source))
            self.assertIn("✓ 2 context", status.stdout)

    def test_an_explicit_profile_wins_over_detection(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            (source / "composer.json").write_text("{}\n", encoding="utf-8")
            result = run("run", "--profile", "enonic", "--source", str(source), *STATIC_UNTIL)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_resume_writes_the_overlay_a_step_run_left_out(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            first = run("step", "inventory.descriptors", "--profile", "enonic", "--source", str(source))
            self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
            out = sidecar_run_dir(source)
            self.assertFalse((out / "context").exists())
            result = run("resume", "--source", str(source), "--out", str(out), *STATIC_UNTIL)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(overlay_of(out)["extends"], "enonic")


class OperatorSurfaceTests(unittest.TestCase):
    def test_next_points_at_context_exclude_while_it_is_undecided(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = as_like(Path(raw))
            self.assertEqual(run("run", "--source", str(source), *STATIC_UNTIL).returncode, 0)
            out = sidecar_run_dir(source)
            before = run("status", "--source", str(source))
            self.assertIn("agent show context.exclude", before.stdout)
            self.assertIn("continue the pipeline without it", before.stdout)
            overlay = overlay_of(out)
            overlay["exclude"] = ["prototype"]
            (out / "context" / "profile.yaml").write_text(yaml.safe_dump(overlay), encoding="utf-8")
            after = run("status", "--source", str(source))
        self.assertNotIn("agent show context.exclude", after.stdout)
        self.assertIn("CMS needs a local XP", after.stdout)

    def test_the_agent_names_context_exclude_then_check_accepts_the_decision(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = as_like(Path(raw))
            run("run", "--source", str(source), *STATIC_UNTIL)
            out = sidecar_run_dir(source)
            nxt = json.loads(run("agent", "next", "--out", str(out), "--json").stdout)
            self.assertEqual(nxt["next"]["id"], "context.exclude")
            shown = run("agent", "show", "context.exclude", "--out", str(out))
            self.assertIn(str(out / "context" / "build-scope.json"), shown.stdout)
            overlay = overlay_of(out)
            overlay["exclude"] = ["prototype"]
            (out / "context" / "profile.yaml").write_text(yaml.safe_dump(overlay), encoding="utf-8")
            nxt = json.loads(run("agent", "next", "--out", str(out), "--json").stdout)
            self.assertNotEqual((nxt["next"] or {}).get("id"), "context.exclude")

    def test_doctor_names_the_stack_it_would_detect(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            result = run("doctor", "--source", str(source))
        self.assertIn("stack", result.stdout)
        self.assertIn("enonic (detected from xp/src/main/resources/application.xml)", result.stdout)

    def test_doctor_warns_when_no_stack_can_be_detected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = run("doctor", "--source", raw)
        self.assertIn("no src/main/resources/application.xml", result.stdout)

    def test_profile_show_with_a_sidecar_prints_the_composed_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = as_like(Path(raw))
            run("run", "--source", str(source), *STATIC_UNTIL)
            out = sidecar_run_dir(source)
            overlay = overlay_of(out)
            overlay["exclude"] = ["prototype"]
            (out / "context" / "profile.yaml").write_text(yaml.safe_dump(overlay), encoding="utf-8")
            shown = json.loads(run("profile", "show", "enonic", "--out", str(out)).stdout)
            plain = json.loads(run("profile", "show", "enonic").stdout)
        self.assertEqual(shown["exclude"], ["prototype"])
        self.assertEqual(shown["overlays"], [str(out / "context" / "profile.yaml")])
        self.assertNotIn("overlays", plain)


# Source lines in the shape AS writes them: the Netaxept host is a template literal.
SOURCE_FILES = {
    "lib/modules/checkout/netaxept.js": (
        "const host = `https://${env === 'test' ? 'test.' : ''}epayment.nets.eu`;\n"
        "const paths = ['/Netaxept/Register.aspx', '/Netaxept/Process.aspx',\n"
        "  '/Netaxept/Query.aspx', '/terminal/default.aspx'];\n"
    ),
    "lib/modules/checkout/flywire.js": (
        "const sandbox = 'https://api-platform-sandbox.flywire.com';\n"
        "const live = 'https://api-platform.flywire.com';\n"
        "const providers = ['Tourplan', 'TravelSpecialist', 'Flywire'];\n"
    ),
    "lib/util/configuration/index.js": "const map = config[`${prefix}-hostMap`].split(',');\n",
    "xp/src/main/resources/site/site.xml": (
        "<input name=\"tourplanUrl\"/><input name=\"netaxeptEnv\"/>"
        "<field name=\"flywirePortal\"/>\n"
    ),
}


class GroundingTests(unittest.TestCase):
    def _sidecar(self, parent: Path, overlay: dict) -> Path:
        source, out = parent / "src", parent / "out"
        for rel, text in SOURCE_FILES.items():
            (source / rel).parent.mkdir(parents=True, exist_ok=True)
            (source / rel).write_text(text, encoding="utf-8")
        (out / "context").mkdir(parents=True)
        (out / "inventory").mkdir()
        (out / "MANIFEST.yaml").write_text(
            yaml.safe_dump({"source": {"path": str(source), "profile": "enonic"}}), encoding="utf-8",
        )
        (out / "context" / "build-scope.json").write_text(
            json.dumps({"out_of_scope": ["external", "prototype"]}), encoding="utf-8",
        )
        (out / "inventory" / "runtime.json").write_text(json.dumps({
            "siteConfig": [],
            "configEnv": [{"key": "env-hostMap", "value": "/en=cms.example.test"}],
        }), encoding="utf-8")
        (out / "context" / "profile.yaml").write_text(yaml.safe_dump(overlay), encoding="utf-8")
        return out

    def _as_overlay(self, **changes: object) -> dict:
        overlay = yaml.safe_load(AS_OVERLAY.read_text(encoding="utf-8"))
        overlay["extends"] = "enonic"
        overlay["exclude"] = ["prototype"]
        overlay.update(changes)
        return overlay

    def test_the_as_facts_are_grounded_in_the_source_and_the_live_config(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = self._sidecar(Path(raw), self._as_overlay())
            self.assertEqual(context.grounding_gaps(out), [])

    def test_an_overlay_with_nothing_to_ground_is_clean(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = self._sidecar(Path(raw), {"extends": "enonic", "exclude": []})
            self.assertEqual(context.grounding_gaps(out), [])
        self.assertEqual(context.grounding_gaps(Path("/nonexistent/sidecar")), [])

    def test_an_invented_key_is_named(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            live = self._as_overlay()["live_config"]
            live["site_url_keys"] = ["tourplanurl", "inventedurl"]
            gaps = context.grounding_gaps(self._sidecar(Path(raw), self._as_overlay(live_config=live)))
        self.assertEqual(len(gaps), 1, gaps)
        self.assertIn("context/profile.yaml", gaps[0])
        self.assertIn("'inventedurl'", gaps[0])

    def test_an_invented_url_path_and_host_are_named(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            live = self._as_overlay()["live_config"]
            live["env_endpoints"][0]["urls"].append("/Netaxept/Invented.aspx")
            live["env_endpoints"][0]["origins"]["test"] = "https://test.invented.example"
            gaps = context.grounding_gaps(self._sidecar(Path(raw), self._as_overlay(live_config=live)))
        self.assertEqual(len(gaps), 2, gaps)
        self.assertTrue(any("'/Netaxept/Invented.aspx'" in g for g in gaps))
        self.assertTrue(any("invented.example" in g for g in gaps))

    def test_an_exclude_outside_the_build_scope_is_named(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = self._sidecar(Path(raw), self._as_overlay(exclude=["prototype", "xp"]))
            gaps = context.grounding_gaps(out)
        self.assertEqual(len(gaps), 1, gaps)
        self.assertIn("exclude 'xp'", gaps[0])

    def test_a_malformed_live_config_is_refused_with_the_overlay_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = self._sidecar(Path(raw), {"extends": "enonic", "live_config": {"site_url_keys": "x"}})
            gaps = context.grounding_gaps(out)
        self.assertEqual(len(gaps), 1)
        self.assertIn("context/profile.yaml", gaps[0])

    def test_check_fails_on_an_ungrounded_overlay_and_ignores_the_operator_override(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source, out = build_sidecar(Path(raw))
            self.assertEqual(run("check", "--out", str(out)).returncode, 0)
            (source / ".extractkit").mkdir()
            (source / ".extractkit" / "profile.yaml").write_text(
                "live_config:\n  site_url_keys: [notinthesource]\n", encoding="utf-8",
            )
            self.assertEqual(run("check", "--out", str(out)).returncode, 0)
            overlay = overlay_of(out)
            overlay["live_config"] = {"site_url_keys": ["alsonotthere"]}
            (out / "context" / "profile.yaml").write_text(yaml.safe_dump(overlay), encoding="utf-8")
            result = run("check", "--out", str(out))
        self.assertEqual(result.returncode, 1)
        self.assertIn("'alsonotthere'", result.stdout)


BEFORE = AS_OVERLAY.parent.parent / "live-config-before-o8.json"


class AsReconstructionTests(unittest.TestCase):
    """`run` with no profile, then the two agent decisions, rebuilds what the old as profile gave."""

    def _stub_agents_source(self, source: Path) -> None:
        """Put the AS-shaped lines inside the build (xp/), where the agent would find them."""
        resources = source / "xp" / "src" / "main" / "resources"
        for rel, text in SOURCE_FILES.items():
            # The fixture keeps its own site.xml; the field names ride in a sibling file.
            target = resources / ("lib/site-fields.xml" if rel.endswith("site.xml") else rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")

    def test_context_and_the_agent_tasks_rebuild_the_as_profile(self) -> None:
        expected = json.loads(BEFORE.read_text(encoding="utf-8"))
        agent_live = yaml.safe_load(AS_OVERLAY.read_text(encoding="utf-8"))["live_config"]
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            source = as_like(parent)
            self._stub_agents_source(source)
            state = parent / "state.json"
            _storage_state(state)
            with graphql_server(PAGE_AS_JSON) as (_hits, url):
                cms = [
                    "--branch", "draft", "--xp-host", url, "--guillotine", url,
                    "--storage-state", str(state), "--cms-key", "/en",
                ]
                first = run("run", "--source", str(source), *STATIC_UNTIL)
                self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
                out = sidecar_run_dir(source)
                scope_doc = json.loads((out / "context" / "build-scope.json").read_text(encoding="utf-8"))
                self.assertEqual(scope_doc["out_of_scope"], ["external", "prototype"])
                self.assertEqual(self._next(out), "context.exclude")

                # The agent keeps external/ (product cron scripts) and drops prototype/.
                self._write_overlay(out, exclude=["prototype"])
                rerun = run("run", "--source", str(source), "--out", str(out),
                            "--from", "static", "--until", "inventory.integrations")
                self.assertEqual(rerun.returncode, 0, rerun.stderr + rerun.stdout)
                recorded = yaml.safe_load((out / "MANIFEST.yaml").read_text(encoding="utf-8"))
                self.assertEqual(recorded["exclude"], ["prototype"])

                step = ["step", "inventory.runtime", "--source", str(source), "--out", str(out), *cms]
                self.assertEqual(run(*step).returncode, 0)
                self.assertEqual(self._next(out), "context.live_config")
                self.assertTrue((out / "inventory" / "live-config-candidates.json").is_file())

                # The agent writes the rules the source and the candidates support.
                self._write_overlay(out, live_config=agent_live)
                self.assertEqual(context.grounding_gaps(out), [])
                result = run(*step)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                runtime = (out / "inventory" / "runtime.json").read_text(encoding="utf-8")
                actual = json.loads(runtime.replace(url, "<HOST>"))
            for key in ("siteConfig", "configEnv", "endpoints", "configenv"):
                self.assertEqual(
                    json.dumps(actual[key], sort_keys=True),
                    json.dumps(expected[key], sort_keys=True),
                    key,
                )
            self.assertNotIn(self._next(out), ("context.exclude", "context.live_config"))
            merged = run("run", "--source", str(source), "--out", str(out),
                         "--from", "maps.merge", "--until", "spec.kit")
            self.assertEqual(merged.returncode, 0, merged.stderr + merged.stdout)
            checked = run("check", "--out", str(out))
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)

    def _next(self, out: Path) -> str | None:
        found = json.loads(run("agent", "next", "--out", str(out), "--json").stdout)
        return (found["next"] or {}).get("id")

    def _write_overlay(self, out: Path, **keys: object) -> None:
        overlay = overlay_of(out)
        overlay.update(keys)
        (out / "context" / "profile.yaml").write_text(yaml.safe_dump(overlay), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
