"""O8: client rules live in an operator override; the kit and steps/enonic/ name no client."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

import yaml

from extractkit_cli import manifest
from tests.support import (
    AS_OVERLAY,
    REPO,
    as_profile,
    copy_fixture,
    install_override,
    run,
    sidecar_run_dir,
)
from tests.test_cms import PAGE_AS_JSON, _storage_state, graphql_server

BEFORE = REPO / "tests" / "fixtures" / "live-config-before-o8.json"
CLIENT_LITERALS = re.compile(
    r"netaxept|flywire|tourplan|travelspecialist|no\.seeds\.configenv", re.IGNORECASE,
)
# profiles/ holds the Config Env tool path on purpose: it is a seeds admin app, not client code.
PROFILE_LITERALS = re.compile(r"netaxept|flywire|tourplan|travelspecialist", re.IGNORECASE)


def _hits(paths: list[Path], pattern: re.Pattern[str]) -> list[str]:
    return [
        f"{path.relative_to(REPO)}:{number}: {line.strip()}"
        for path in paths
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]


class ClientProfileTests(unittest.TestCase):
    def test_no_client_literal_remains_in_the_generic_adapter(self) -> None:
        self.assertEqual(
            _hits(sorted((REPO / "steps" / "enonic").rglob("*.py")), CLIENT_LITERALS), [],
        )

    def test_the_kit_ships_no_client_profile(self) -> None:
        self.assertEqual(manifest.available(), ["core", "enonic", "php"])
        self.assertEqual(_hits(sorted((REPO / "profiles").glob("*.yaml")), PROFILE_LITERALS), [])

    def test_the_as_override_is_an_overlay_and_leaves_the_stack_alone(self) -> None:
        raw = yaml.safe_load(AS_OVERLAY.read_text(encoding="utf-8"))
        self.assertEqual(set(raw) - {"_comment"}, {"exclude", "live_config"})
        composed = as_profile()
        self.assertEqual(composed["adapters"], manifest.load("enonic")["adapters"])
        self.assertEqual(
            composed["live_config"]["configenv_path"],
            manifest.load("enonic")["live_config"]["configenv_path"],
        )

    def test_the_override_reproduces_the_pre_change_endpoints_byte_for_byte(self) -> None:
        expected = json.loads(BEFORE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            source = copy_fixture(parent)
            install_override(source)
            state = parent / "state.json"
            _storage_state(state)
            with graphql_server(PAGE_AS_JSON) as (_, url):
                result = run(
                    "step", "enonic.cms", "--source", str(source),
                    "--branch", "draft", "--xp-host", url, "--guillotine", url,
                    "--storage-state", str(state), "--cms-key", "/en",
                )
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                runtime = (sidecar_run_dir(source) / "inventory/runtime.json").read_text(encoding="utf-8")
            actual = json.loads(runtime.replace(url, "<HOST>"))
        for key in ("siteConfig", "configEnv", "endpoints", "configenv"):
            self.assertEqual(
                json.dumps(actual[key], sort_keys=True),
                json.dumps(expected[key], sort_keys=True),
                key,
            )


if __name__ == "__main__":
    unittest.main()
