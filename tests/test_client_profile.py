"""O8: client rules live in profiles/as.yaml; steps/enonic/ names no client."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

import yaml

from extractkit_cli import manifest
from tests.support import REPO, copy_fixture, run, sidecar_run_dir
from tests.test_cms import PAGE_AS_JSON, _storage_state, graphql_server

BEFORE = REPO / "tests" / "fixtures" / "live-config-before-o8.json"
CLIENT_LITERALS = re.compile(
    r"netaxept|flywire|tourplan|travelspecialist|no\.seeds\.configenv", re.IGNORECASE,
)


class ClientProfileTests(unittest.TestCase):
    def test_no_client_literal_remains_in_the_generic_adapter(self) -> None:
        hits = [
            f"{path.relative_to(REPO)}:{number}: {line.strip()}"
            for path in sorted((REPO / "steps" / "enonic").rglob("*.py"))
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if CLIENT_LITERALS.search(line)
        ]
        self.assertEqual(hits, [])

    def test_as_extends_enonic_without_an_adapters_key(self) -> None:
        raw = yaml.safe_load((REPO / "profiles" / "as.yaml").read_text(encoding="utf-8"))
        self.assertEqual(raw["extends"], "enonic")
        self.assertNotIn("adapters", raw)
        self.assertEqual(manifest.load("as")["adapters"], manifest.load("enonic")["adapters"])
        self.assertEqual(manifest.load("enonic")["live_config"], {})

    def test_as_profile_reproduces_the_pre_change_endpoints_byte_for_byte(self) -> None:
        expected = json.loads(BEFORE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            source = copy_fixture(parent)
            state = parent / "state.json"
            _storage_state(state)
            with graphql_server(PAGE_AS_JSON) as (_hits, url):
                result = run(
                    "step", "enonic.cms", "--profile", "as", "--source", str(source),
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
