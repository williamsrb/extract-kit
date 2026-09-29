"""Live Site Config / Config Env harvest — URLs as metadata, secrets dropped."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from steps.enonic import live_config


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
        record = live_config.site_config_record("/en", "id-1", payload)
        self.assertEqual(
            record["fields"]["siteConfig.config.tourplanUrl"],
            "https://tourplan.example.test/api",
        )
        self.assertIn("siteConfig.config.tourplanPassword", record["redacted"])
        self.assertNotIn("secret", str(record["fields"]))
        endpoints = live_config.endpoints_from_site_fields(
            record["fields"], content_key="/en",
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
        endpoints = live_config.endpoints_from_config_env(items)
        urls = {row["url"] for row in endpoints}
        self.assertIn("https://sync.example.test/ingest", urls)
        self.assertIn("https://cms.example.test", urls)
        self.assertNotIn("nope", str(endpoints))

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
