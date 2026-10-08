"""Help contract, profile show, and doctor on shipped types."""

from __future__ import annotations

import json
import unittest

from tests.support import run


class HelpContractTests(unittest.TestCase):
    GROUPS = ("profile", "kb")

    def test_bare_equals_help(self) -> None:
        bare, helped = run(), run("--help")
        self.assertEqual(bare.returncode, 0)
        self.assertEqual(helped.returncode, 0)
        self.assertEqual(bare.stdout, helped.stdout)

    def test_every_group_bare_equals_help(self) -> None:
        for group in self.GROUPS:
            with self.subTest(group=group):
                bare, helped = run(group), run(group, "--help")
                self.assertEqual(bare.returncode, 0, bare.stderr)
                self.assertEqual(bare.stdout, helped.stdout)

    def test_unknown_subcommand_is_usage_on_stderr_exit_2(self) -> None:
        result = run("bogus")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("usage:", result.stderr)

    def test_unknown_flag_on_bare_is_not_exit_0(self) -> None:
        result = run("--nope")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments", result.stderr)


class ProfileCommandTests(unittest.TestCase):
    def test_list_includes_all_three_types(self) -> None:
        result = run("profile", "list")
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("core", "enonic", "php"):
            self.assertIn(name, result.stdout)

    def test_show_enonic_and_php(self) -> None:
        enonic = run("profile", "show", "enonic")
        php = run("profile", "show", "php")
        self.assertEqual(enonic.returncode, 0, enonic.stderr)
        self.assertEqual(php.returncode, 0, php.stderr)
        enonic_json = json.loads(enonic.stdout)
        php_json = json.loads(php.stdout)
        self.assertEqual(enonic_json["name"], "enonic")
        self.assertEqual(
            enonic_json["adapters"]["inventory.descriptors"],
            "enonic.descriptors",
        )
        self.assertEqual(
            enonic_json["adapters"]["inventory.runtime"],
            "enonic.cms",
        )
        self.assertIsNone(php_json["adapters"]["inventory.descriptors"])
        self.assertTrue(php_json["todo"])

    def test_doctor_default_is_clean(self) -> None:
        result = run("doctor")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_deps_core_finds_python3(self) -> None:
        result = run("deps", "--profile", "core")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("python3", result.stdout)


if __name__ == "__main__":
    unittest.main()
