"""US-003: every option has an `EXTRACTKIT_*` form, with CLI > env > file > default."""

from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from extractkit_cli import cli, envflags
from extractkit_cli.errors import ExtractkitError
from tests.support import copy_fixture, run


class EnvironmentTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.source = copy_fixture(Path(tmp.name))

    def _config(self, doc: dict) -> dict:
        return {row["name"]: row for row in doc["config"]}

    def _excluded(self, doc: dict) -> list:
        return yaml.safe_load((Path(doc["sidecar"]) / "MANIFEST.yaml").read_text())["exclude"]

    def _run(self, *args: str, env: dict[str, str]) -> tuple:
        result = run(*args, cwd=self.source, env=env)
        return result, (json.loads(result.stdout) if result.stdout.lstrip().startswith("{") else None)

    def test_required_source_and_scalars_come_from_the_environment(self) -> None:
        env = {"EXTRACTKIT_SOURCE": ".", "EXTRACTKIT_UNTIL": "static", "EXTRACTKIT_EXCLUDE": "docs,tools"}
        result, doc = self._run("run", "--json", env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        config = self._config(doc)
        for name in ("--source", "--until", "--exclude"):
            self.assertEqual(config[name]["origin"], "env", name)
        self.assertEqual(config["--exclude"]["value"], ["docs", "tools"])
        self.assertEqual(self._excluded(doc), ["docs", "tools"])

    def test_a_cli_repeatable_replaces_the_env_one(self) -> None:
        env = {"EXTRACTKIT_SOURCE": ".", "EXTRACTKIT_UNTIL": "static", "EXTRACTKIT_EXCLUDE": "docs,tools"}
        result, doc = self._run("run", "--json", "--exclude", "docs", env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self._config(doc)["--exclude"]["origin"], "cli")
        self.assertEqual(self._config(doc)["--exclude"]["value"], ["docs"])
        self.assertEqual(self._excluded(doc), ["docs"])

    def test_cli_beats_env_for_a_scalar(self) -> None:
        env = {"EXTRACTKIT_SOURCE": "does-not-exist", "EXTRACTKIT_UNTIL": "cms"}
        result, doc = self._run("run", "--json", "--source", ".", "--until", "static", env=env)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self._config(doc)["--until"]["origin"], "cli")
        self.assertEqual(self._config(doc)["--until"]["value"], "static")

    def test_json_from_the_environment(self) -> None:
        _result, doc = self._run("deps", env={"EXTRACTKIT_JSON": "yes"})
        self.assertEqual(doc["command"], "deps")

    def test_missing_required_option_is_still_an_argparse_error(self) -> None:
        result = run("run", cwd=self.source)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--source", result.stderr)

    def test_bad_boolean_is_bad_env(self) -> None:
        result, doc = self._run("deps", env={"EXTRACTKIT_QUIET": "maybe", "EXTRACTKIT_JSON": "1"})
        self.assertEqual(result.returncode, 1)
        self.assertEqual(doc["error"]["code"], "bad_env")
        self.assertIn("EXTRACTKIT_QUIET", doc["error"]["message"])

    def test_boolean_spellings(self) -> None:
        for raw, expected in (("1", True), ("TRUE", True), ("Yes", True), ("0", False), ("no", False)):
            with self.subTest(raw=raw):
                parser = cli.build_parser()
                envflags.apply_defaults(parser, {"EXTRACTKIT_QUIET": raw})
                args = parser.parse_args(["deps"])
                self.assertIs(args.quiet, expected)

    def test_forbidden_variables_fail_with_env_forbidden(self) -> None:
        for name in ("EXTRACTKIT_ALLOW_PRODUCTION", "EXTRACTKIT_FORCE"):
            with self.subTest(name=name):
                result, doc = self._run("deps", "--json", env={name: "1"})
                self.assertEqual(result.returncode, 1)
                self.assertEqual(doc["error"]["code"], "env_forbidden")
                self.assertIn(name, doc["error"]["message"])

    def test_forbidden_flags_get_no_env_default(self) -> None:
        parser = cli.build_parser()
        envflags.apply_defaults(parser, {"EXTRACTKIT_ALLOW_PRODUCTION": "1", "EXTRACTKIT_FORCE": "1"})
        args = parser.parse_args(["run", "--source", "."])
        self.assertFalse(args.allow_production)

    def test_every_long_option_has_an_env_name(self) -> None:
        names = set()
        for leaf in envflags._leaves(cli.build_parser()):
            for action in leaf._actions:
                if action.option_strings and (name := envflags.env_name(action)):
                    names.add(name)
        for expected in ("EXTRACTKIT_SOURCE", "EXTRACTKIT_BRANCH", "EXTRACTKIT_XP_HOST", "EXTRACTKIT_CMS_KEY",
                         "EXTRACTKIT_STORAGE_STATE", "EXTRACTKIT_RESOURCES", "EXTRACTKIT_JSON"):
            self.assertIn(expected, names)
        self.assertNotIn("EXTRACTKIT_ALLOW_PRODUCTION", names)
        self.assertNotIn("EXTRACTKIT_FORCE", names)

    def test_the_next_line_never_echoes_an_env_sourced_value(self) -> None:
        secret = str(self.source / "env-only-state.json")
        env = {"EXTRACTKIT_STORAGE_STATE": secret, "EXTRACTKIT_BRANCH": "draft"}
        result = run("run", "--source", ".", "--until", "static", cwd=self.source, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(secret, result.stdout + result.stderr)


class StorageStateJsonTests(unittest.TestCase):
    def _parse(self, extra: list[str], env: dict[str, str]) -> tuple:
        parser = cli.build_parser()
        envflags.apply_defaults(parser, env)
        raw = ["run", "--source", ".", *extra]
        args = parser.parse_args(raw)
        return args, raw

    def test_contents_become_a_private_temp_file_that_is_removed_at_exit(self) -> None:
        env = {"EXTRACTKIT_STORAGE_STATE_JSON": '{"cookies":[{"name":"s","value":"TOP-SECRET"}]}'}
        with mock.patch.object(envflags.atexit, "register") as register:
            args, raw = self._parse([], env)
            envflags.finish(args, raw, env)
        path = Path(args.storage_state)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(json.loads(path.read_text())["cookies"][0]["value"], "TOP-SECRET")
        self.assertEqual(args._origins["storage_state"], "env")
        cleanup, folder = register.call_args.args[0], register.call_args.args[1]
        cleanup(folder, ignore_errors=True)
        self.assertFalse(path.exists())

    def test_a_ci_file_variable_path_is_read_for_its_contents(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            given = Path(raw) / "STATE"
            given.write_text('{"cookies":[{"name":"s","value":"FROM-FILE"}]}', encoding="utf-8")
            env = {"EXTRACTKIT_STORAGE_STATE_JSON": str(given)}
            with mock.patch.object(envflags.atexit, "register") as register:
                args, argv = self._parse([], env)
                envflags.finish(args, argv, env)
        path = Path(args.storage_state)
        self.assertNotEqual(path, given)
        self.assertEqual(json.loads(path.read_text())["cookies"][0]["value"], "FROM-FILE")
        register.call_args.args[0](register.call_args.args[1], ignore_errors=True)

    def test_conflict_with_the_file_forms(self) -> None:
        env = {"EXTRACTKIT_STORAGE_STATE_JSON": "{}", "EXTRACTKIT_STORAGE_STATE": "/x.json"}
        args, raw = self._parse([], env)
        with self.assertRaises(ExtractkitError) as caught:
            envflags.finish(args, raw, env)
        self.assertEqual(caught.exception.code, "bad_env")
        env = {"EXTRACTKIT_STORAGE_STATE_JSON": "{}"}
        args, raw = self._parse(["--storage-state", "/x.json"], env)
        with self.assertRaises(ExtractkitError):
            envflags.finish(args, raw, env)

    def test_contents_never_reach_stdout_or_the_config_section(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            env = {"EXTRACTKIT_STORAGE_STATE_JSON": '{"cookies":[{"name":"s","value":"TOP-SECRET"}]}'}
            result = run("run", "--source", ".", "--until", "static", "--json", cwd=source, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("TOP-SECRET", result.stdout + result.stderr)
        config = {row["name"]: row for row in json.loads(result.stdout)["config"]}
        self.assertEqual(config["--storage-state"]["value"], "<redacted>")
        self.assertEqual(config["--storage-state"]["origin"], "env")


class RedactionTests(unittest.TestCase):
    def test_key_like_options_are_redacted_but_cms_key_is_not(self) -> None:
        self.assertTrue(envflags._is_secret("--api-key", "api_key", set()))
        self.assertTrue(envflags._is_secret("--token", "token", set()))
        self.assertFalse(envflags._is_secret("--cms-key", "cms_keys", set()))
        self.assertFalse(envflags._is_secret("--source", "source", set()))


if __name__ == "__main__":
    unittest.main()
