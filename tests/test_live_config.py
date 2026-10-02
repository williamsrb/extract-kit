"""Live Site Config / Config Env harvest — URLs as metadata, secrets dropped."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from extractkit_cli.errors import ExtractkitError
from steps.enonic import live_config
from tests.support import as_profile

AS_RULES = live_config.rules_from_profile(as_profile())


class LiveConfigTests(unittest.TestCase):
    def test_site_config_urls_and_redaction(self) -> None:
        payload = {
            "data": [
                {
                    "name": "siteConfig",
                    "values": [{
                        "set": [{
                            "name": "config",
                            "values": [{
                                "set": [
                                    {
                                        "name": "tourplanUrl",
                                        "values": [{"v": "https://tourplan.example.test/api"}],
                                    },
                                    {
                                        "name": "tourplanPassword",
                                        "values": [{"v": "secret"}],
                                    },
                                    {
                                        "name": "netaxeptEnv",
                                        "values": [{"v": "test"}],
                                    },
                                ],
                            }],
                        }],
                    }],
                },
            ],
        }
        record = live_config.site_config_record("/en", "id-1", payload, AS_RULES)
        self.assertEqual(
            record["fields"]["siteConfig.config.tourplanUrl"],
            "https://tourplan.example.test/api",
        )
        self.assertIn("siteConfig.config.tourplanPassword", record["redacted"])
        self.assertNotIn("secret", str(record["fields"]))
        endpoints = live_config.endpoints_from_site_fields(
            record["fields"], content_key="/en", rules=AS_RULES,
        )
        urls = {row["url"] for row in endpoints}
        self.assertIn("https://tourplan.example.test/api", urls)
        self.assertTrue(any("test.epayment.nets.eu/Netaxept/Register" in u for u in urls))

    def test_configenv_html_and_hostmap(self) -> None:
        html = """
        <td id="key-a">env-travelSpecialistSyncEndpoint</td>
        <td id="value-a">https://sync.example.test/ingest</td>
        <td id="key-b">env-hostMap</td>
        <td id="value-b">/en=cms.example.test</td>
        <td id="key-c">env-simpleSecret</td>
        <td id="value-c">nope</td>
        """
        items = live_config.parse_configenv_html(html)
        secrets = [i for i in items if i.get("redacted") == "true"]
        self.assertEqual(secrets[0]["key"], "env-simpleSecret")
        endpoints = live_config.endpoints_from_config_env(items, AS_RULES)
        urls = {row["url"] for row in endpoints}
        self.assertIn("https://sync.example.test/ingest", urls)
        self.assertIn("https://cms.example.test", urls)
        self.assertNotIn("nope", str(endpoints))

    def test_empty_rules_infer_nothing_from_site_config(self) -> None:
        fields = {
            "siteConfig.config.tourplanUrl": "https://tourplan.example.test/api",
            "siteConfig.config.netaxeptEnv": "test",
        }
        rules = live_config.rules_from_profile({"live_config": {}})
        self.assertEqual(live_config.endpoints_from_site_fields(fields, content_key="/en", rules=rules), [])
        self.assertEqual(live_config.slim_integration_fields(fields, rules), {})
        self.assertEqual(live_config.default_configenv_url("http://h", rules), "")

    def test_generic_endpoint_suffix_survives_without_rules(self) -> None:
        rules = live_config.Rules()
        fields = {"app.syncEndpoint": "https://x.example.test", "app.other": "v"}
        self.assertEqual(live_config.slim_integration_fields(fields, rules), {"app.syncEndpoint": "https://x.example.test"})

    def test_env_rule_maps_value_to_origin_default_and_paths(self) -> None:
        rules = live_config.rules_from_profile({"live_config": {
            "env_endpoints": [{
                "provider": "Pay", "key": "mode", "path": "payments",
                "origins": {"sandbox": "https://sandbox.example.test"},
                "default": "https://live.example.test", "urls": ["/a", "/b"],
            }],
            "providers": {"pay": "Pay"},
            "configenv_path": "/admin/tool/x",
        }})
        sandbox = live_config.endpoints_from_site_fields(
            {"cfg.payments.mode": "Sandbox", "cfg.other.mode": "x"}, content_key="/k", rules=rules,
        )
        self.assertEqual([e["url"] for e in sandbox], [
            "https://sandbox.example.test/a", "https://sandbox.example.test/b",
        ])
        self.assertEqual(sandbox[0]["source"], "siteConfig:/k:cfg.payments.mode=Sandbox")
        live = live_config.endpoints_from_site_fields({"cfg.payments.mode": "prod"}, content_key="/k", rules=rules)
        self.assertEqual(live[0]["url"], "https://live.example.test/a")
        self.assertEqual(live_config.default_configenv_url("http://h", rules), "http://h/admin/tool/x")

    def test_malformed_table_names_a_fix(self) -> None:
        for bad in (
            {"live_config": ["x"]},
            {"live_config": {"site_url_keys": "tourplanurl"}},
            {"live_config": {"env_endpoints": [{"provider": "P"}]}},
            {"live_config": {"providers": ["a"]}},
        ):
            with self.assertRaises(ExtractkitError) as caught:
                live_config.rules_from_profile(bad)
            self.assertIn("docs/profiles.md", caught.exception.fix)

    def test_patch_openapi_is_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "openapi.yaml"
            path.write_text(
                "openapi: '3.1.0'\ninfo: {title: t, version: v}\n"
                "x-production-endpoints: []\npaths: {}\n",
                encoding="utf-8",
            )
            spec = live_config.patch_openapi(path, [{
                "provider": "Tourplan",
                "direction": "outbound",
                "url": "https://tourplan.example.test/api",
                "source": "siteConfig:/en:tourplanUrl",
            }])
            self.assertIsNotNone(spec)
            assert spec is not None
            self.assertEqual(
                spec["x-production-endpoints"][0]["url"],
                "https://tourplan.example.test/api",
            )


if __name__ == "__main__":
    unittest.main()
