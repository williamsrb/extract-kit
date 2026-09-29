"""YAML extends: parent-first lists, child replace, loop detection."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from extractkit_cli import manifest
from extractkit_cli.errors import ExtractkitError
from extractkit_cli.schema import validate


def _write_profiles(root: Path, files: dict[str, str]) -> None:
    directory = root / "profiles"
    directory.mkdir()
    for name, body in files.items():
        (directory / f"{name}.yaml").write_text(body, encoding="utf-8")


class ManifestTests(unittest.TestCase):
    def test_parent_first_lists_and_child_replace(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_profiles(root, {
                "core": (
                    "name: core\n"
                    "extends: null\n"
                    "todo: []\n"
                    "pipeline: [a, b]\n"
                    "adapters: {a: core.a, extra: null}\n"
                    "deps:\n"
                    "  - {provides: [python3]}\n"
                ),
                "child": (
                    "name: child\n"
                    "extends: core\n"
                    "todo:\n"
                    "  - bind extra\n"
                    "pipeline: [c]\n"
                    "adapters: {a: child.a, extra: child.extra}\n"
                ),
            })
            composed = manifest.load("child", kit_root=root)
            self.assertEqual(composed["pipeline"], ["a", "b", "c"])
            self.assertEqual(composed["todo"], ["bind extra"])
            self.assertEqual(
                composed["adapters"],
                {"a": "child.a", "extra": "child.extra"},
            )
            self.assertEqual(composed["lineage"], ["core", "child"])
            self.assertEqual(
                manifest.provided_binaries(composed),
                ["python3"],
            )

    def test_loop_detection_names_the_fix(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_profiles(root, {
                "one": "name: one\nextends: two\n",
                "two": "name: two\nextends: one\n",
            })
            with self.assertRaises(ExtractkitError) as caught:
                manifest.load("one", kit_root=root)
            self.assertIn("loops", str(caught.exception))
            self.assertIn("extends", caught.exception.fix or "")

    def test_missing_profile_lists_available(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_profiles(root, {"core": "name: core\nextends: null\n"})
            with self.assertRaises(ExtractkitError) as caught:
                manifest.load("nope", kit_root=root)
            self.assertIn("core", caught.exception.fix or "")

    def test_shipped_profiles_compose_and_match_schema(self) -> None:
        enonic = manifest.load("enonic")
        php = manifest.load("php")
        validate(enonic, "profile", what="enonic")
        validate(php, "profile", what="php")
        self.assertEqual(enonic["lineage"], ["core", "enonic"])
        self.assertEqual(
            enonic["adapters"]["inventory.descriptors"],
            "enonic.descriptors",
        )
        self.assertEqual(
            enonic["adapters"]["inventory.runtime"],
            "enonic.cms",
        )
        self.assertIsNone(php["adapters"]["inventory.descriptors"])
        self.assertTrue(manifest.unfinished_work(php))
        self.assertEqual(php["pipeline"], enonic["pipeline"])


if __name__ == "__main__":
    unittest.main()
