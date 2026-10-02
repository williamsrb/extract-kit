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


class OverlayTests(unittest.TestCase):
    def _layers(self, raw: str, generated: str | None, override: str | None):
        root = Path(raw)
        out, source = root / "out", root / "src"
        if generated is not None:
            (out / "context").mkdir(parents=True)
            (out / "context" / "profile.yaml").write_text(generated, encoding="utf-8")
        if override is not None:
            (source / ".extractkit").mkdir(parents=True)
            (source / ".extractkit" / "profile.yaml").write_text(override, encoding="utf-8")
        base = manifest.load("enonic")
        return manifest.compose_overlays(base, out, source)

    def test_no_layer_leaves_the_stack_profile_alone(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            composed, layers = self._layers(raw, None, None)
            self.assertEqual(layers, [])
            self.assertEqual(composed, manifest.load("enonic"))

    def test_layers_compose_in_order_and_the_override_wins(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            composed, layers = self._layers(
                raw,
                "extends: enonic\nexclude: [prototype]\nlive_config:\n  site_url_keys: [a]\n  hostmap_keys: [h]\n",
                "exclude: [legacy]\nlive_config:\n  site_url_keys: [b]\n",
            )
            self.assertEqual([Path(p).parts[-2:] for p in layers], [
                ("context", "profile.yaml"), (".extractkit", "profile.yaml"),
            ])
            self.assertEqual(composed["exclude"], ["prototype", "legacy"])
            self.assertEqual(composed["live_config"], {
                **manifest.load("enonic")["live_config"],
                "site_url_keys": ["b"], "hostmap_keys": ["h"],
            })

    def test_an_overlay_cannot_rebind_the_stack(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(ExtractkitError) as caught:
                self._layers(raw, "adapters: {map.code: null}\n", None)
            self.assertIn("adapters", str(caught.exception))
            self.assertIn("context", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
