"""FR-14: production deny, required branch, mock Guillotine survey."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

from extractkit_cli import cms_target, manifest
from extractkit_cli.errors import ExtractkitError
from extractkit_cli.schema import validate
from steps.enonic.cms import context_for, resolve_cms, template_order
from tests.support import STATIC_UNTIL, copy_fixture, run, sidecar_run_dir

PAGE_AS_JSON = {
    "descriptor": "com.example.mini:mini-page",
    "type": "page",
    "path": "/",
    "regions": {
        "main": {
            "components": [
                {
                    "descriptor": "com.example.mini:mini-layout",
                    "type": "layout",
                    "path": "/main/0",
                    "regions": {
                        "grid": {
                            "components": [
                                {
                                    "descriptor": "com.example.mini:mini-part",
                                    "type": "part",
                                    "path": "/main/0/grid/0",
                                }
                            ]
                        }
                    },
                }
            ]
        }
    },
}

CS_SITE_BODY = {
    "id": "id-1",
    "data": [
        {
            "name": "siteConfig",
            "type": "PropertySet",
            "values": [{
                "set": [
                    {
                        "name": "config",
                        "type": "PropertySet",
                        "values": [{
                            "set": [
                                {
                                    "name": "tourplanUrl",
                                    "type": "String",
                                    "values": [{
                                        "v": "https://tourplan.example.test/api",
                                    }],
                                },
                                {
                                    "name": "tourplanPassword",
                                    "type": "String",
                                    "values": [{"v": "do-not-store"}],
                                },
                                {
                                    "name": "netaxeptEnv",
                                    "type": "String",
                                    "values": [{"v": "test"}],
                                },
                                {
                                    "name": "flywirePortal",
                                    "type": "PropertySet",
                                    "values": [{
                                        "set": [{
                                            "name": "env",
                                            "type": "String",
                                            "values": [{"v": "demo"}],
                                        }],
                                    }],
                                },
                            ],
                        }],
                    },
                ],
            }],
        },
    ],
}

CONFIGENV_HTML = """
<table><tbody>
<tr>
  <td id="key-1">env-travelSpecialistSyncEndpoint</td>
  <td id="value-1">https://sync.example.test/ingest</td>
</tr>
<tr>
  <td id="key-2">env-hostMap</td>
  <td id="value-2">/en=cms.example.test</td>
</tr>
<tr>
  <td id="key-3">env-simpleSecret</td>
  <td id="value-3">nope</td>
</tr>
</tbody></table>
"""


def _storage_state(path: Path) -> None:
    path.write_text(
        json.dumps({
            "cookies": [
                {
                    "name": "JSESSIONID",
                    "value": "test-session",
                    "domain": "127.0.0.1",
                    "path": "/",
                }
            ],
            "origins": [],
        }),
        encoding="utf-8",
    )


@contextmanager
def graphql_server(page: dict) -> Iterator[tuple[list, str]]:
    hits: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or "0")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            hits.append({"body": body, "cookie": self.headers.get("Cookie")})
            query = body.get("query") or ""
            if "queryConnection" in query:
                payload = {
                    "data": {
                        "guillotine": {
                            "queryConnection": {"totalCount": 0, "edges": []},
                        }
                    }
                }
            elif "getChildren" in query:
                payload = {"data": {"guillotine": {"getChildren": []}}}
            else:
                payload = {
                    "data": {
                        "guillotine": {
                            "get": {
                                "_id": "id-1",
                                "_path": "/en",
                                "type": "portal:site",
                                "displayName": "EN",
                                "pageAsJson": page,
                                "components": [{"path": "/", "type": "page"}],
                            }
                        }
                    }
                }
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if "content/content" in parsed.path:
                payload = json.dumps(CS_SITE_BODY).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if "configenv" in parsed.path or parsed.path.endswith("module-config"):
                raw = CONFIGENV_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            self.send_error(404)

        def log_message(self, *_args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield hits, f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()


class CmsTargetTests(unittest.TestCase):
    def test_localhost_is_local(self) -> None:
        self.assertEqual(cms_target.classify("http://localhost:8080"), "local")
        self.assertEqual(cms_target.classify("http://127.0.0.1:8080"), "local")

    def test_k8s_seeds_is_review(self) -> None:
        self.assertEqual(
            cms_target.classify("https://as.review.k8s.seeds.no"),
            "review",
        )

    def test_production_is_refused(self) -> None:
        with self.assertRaises(ExtractkitError) as caught:
            cms_target.assert_allowed(
                "https://www.authentic-scandinavia.com",
                allow_production=False,
                what="--xp-host",
            )
        self.assertIn("deny-by-default", str(caught.exception))

    def test_allow_production_classifies_but_is_not_default(self) -> None:
        env = cms_target.assert_allowed(
            "https://www.authentic-scandinavia.com",
            allow_production=True,
            what="--xp-host",
        )
        self.assertEqual(env, "production")

    def test_branch_must_be_draft_or_master(self) -> None:
        with self.assertRaises(ExtractkitError):
            cms_target.assert_branch(None)
        with self.assertRaises(ExtractkitError):
            cms_target.assert_branch("live")
        self.assertEqual(cms_target.assert_branch("draft"), "draft")

    def test_shipped_enonic_cms_is_localhost(self) -> None:
        enonic = manifest.load("enonic")
        self.assertEqual(enonic["cms"]["host"], "http://localhost:8080")
        self.assertEqual(enonic["cms"]["sample_per_type"], 3)
        self.assertNotIn("authentic-scandinavia", json.dumps(enonic))
        self.assertEqual(enonic["adapters"]["inventory.runtime"], "enonic.cms")
        self.assertIn("inventory.runtime", enonic["pipeline"])


class TemplateOrderTests(unittest.TestCase):
    def test_region_order(self) -> None:
        self.assertEqual(
            template_order(PAGE_AS_JSON),
            [
                "com.example.mini:mini-page",
                "com.example.mini:mini-layout",
                "com.example.mini:mini-part",
            ],
        )

    def test_context_matches_static_kind(self) -> None:
        index = {
            "mini-page": {"kind": "page", "name": "mini-page"},
            "com.example.mini:mini-page": {"kind": "page", "name": "mini-page"},
        }
        self.assertEqual(context_for("/en", PAGE_AS_JSON, index, {}), "page")


class CmsCliTests(unittest.TestCase):
    def test_missing_branch_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            result = run(
                "step", "enonic.cms", "--profile", "enonic",
                "--source", str(source),
            )
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("--branch", combined)

    def test_production_host_refused_on_cli(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            result = run(
                "step", "enonic.cms", "--profile", "enonic",
                "--source", str(source),
                "--branch", "draft",
                "--xp-host", "https://www.authentic-scandinavia.com",
                "--guillotine",
                "https://www.authentic-scandinavia.com/admin/site/preview/en/draft",
            )
        self.assertNotEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn("deny-by-default", combined)

    def test_full_run_without_branch_refuses_cms(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = copy_fixture(Path(raw))
            result = run(
                "run", "--profile", "enonic", "--source", str(source), "--apply",
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--branch", result.stdout + result.stderr)

    def test_mock_guillotine_writes_runtime_and_round2(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            source = copy_fixture(parent)
            state = parent / "state.json"
            _storage_state(state)
            with graphql_server(PAGE_AS_JSON) as (hits, url):
                result = run(
                    "step", "enonic.cms", "--profile", "enonic",
                    "--source", str(source), "--apply",
                    "--branch", "draft",
                    "--xp-host", url,
                    "--guillotine", url,
                    "--storage-state", str(state),
                    "--cms-key", "/en",
                    "--round2", "page",
                )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            gets = [
                hit for hit in hits
                if "get(key" in ((hit["body"] or {}).get("query") or "")
            ]
            self.assertEqual(len(gets), 2)
            self.assertEqual(gets[0]["cookie"], "JSESSIONID=test-session")
            self.assertIn("/en", gets[0]["body"]["query"])
            out = sidecar_run_dir(source)
            runtime_path = out / "inventory" / "runtime.json"
            payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            validate(payload, "runtime-inventory")
            self.assertEqual(payload["env"], "local")
            self.assertEqual(payload["branch"], "draft")
            self.assertEqual(payload["host"], url)
            self.assertEqual(payload["guillotine"], url)
            self.assertNotIn("authentic-scandinavia", json.dumps(payload))
            pages = payload["pages"]
            self.assertEqual([p["round"] for p in pages], [1, 2])
            self.assertEqual(pages[0]["context"], "page")
            self.assertEqual(
                pages[0]["templateOrder"],
                [
                    "com.example.mini:mini-page",
                    "com.example.mini:mini-layout",
                    "com.example.mini:mini-part",
                ],
            )
            blob = json.dumps(payload)
            self.assertNotIn("do-not-store", blob)
            self.assertNotIn("nope", blob)
            urls = {row["url"] for row in payload["endpoints"]}
            self.assertIn("https://tourplan.example.test/api", urls)
            self.assertIn("https://sync.example.test/ingest", urls)
            self.assertIn("https://cms.example.test", urls)
            self.assertTrue(any("test.epayment.nets.eu" in u for u in urls))
            self.assertIn(
                "https://api-platform-sandbox.flywire.com", urls,
            )
            survey_path = out / "inventory" / "content-survey.json"
            survey = json.loads(survey_path.read_text(encoding="utf-8"))
            validate(survey, "content-survey")
            self.assertEqual(survey["samplePerType"], 3)
            types = {row["type"] for row in survey["types"]}
            self.assertIn("com.example.mini:mini-article", types)
            self.assertIn("portal:site", types)
            resolved = json.loads(
                (out / "inventory" / "content-survey-resolved.json").read_text(
                    encoding="utf-8",
                )
            )
            validate(resolved, "content-survey-resolved")
            self.assertEqual(len(resolved["rule"]), 3)
            self.assertTrue((out / "inventory" / "content-survey.md").is_file())
            self.assertTrue(
                (out / "inventory" / "content-survey-resolved.md").is_file(),
            )
            self.assertEqual(pages[0]["resolve"], "customized")

    def test_missing_guillotine_and_project_refuses(self) -> None:
        ctx = SimpleNamespace(
            profile={"name": "t", "cms": {"host": "http://localhost:8080"}},
            cms={"branch": "draft"},
        )
        with self.assertRaises(ExtractkitError) as caught:
            resolve_cms(ctx)
        self.assertIn("Guillotine", str(caught.exception))

    def test_profile_round2_is_loaded(self) -> None:
        ctx = SimpleNamespace(
            profile={
                "name": "t",
                "round2": ["home"],
                "cms": {
                    "host": "http://localhost:8080",
                    "project": "en",
                    "keys": ["/en"],
                },
            },
            cms={"branch": "draft"},
        )
        cfg = resolve_cms(ctx)
        self.assertEqual(cfg.round2, ["home"])
        self.assertEqual(cfg.sample_per_type, 3)
        self.assertTrue(cfg.guillotine.endswith("/admin/site/preview/en/draft"))
        self.assertNotIn("no.seeds.as/graphql", cfg.guillotine)
        self.assertTrue(
            cfg.configenv.endswith("/admin/tool/no.seeds.configenv/module-config"),
        )

    def test_cms_patches_openapi_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            source = copy_fixture(parent)
            state = parent / "state.json"
            _storage_state(state)
            static = run(
                "run", "--profile", "enonic", "--source", str(source),
                "--apply", *STATIC_UNTIL,
            )
            self.assertEqual(static.returncode, 0, static.stderr + static.stdout)
            with graphql_server(PAGE_AS_JSON) as (_hits, url):
                result = run(
                    "step", "enonic.cms", "--profile", "enonic",
                    "--source", str(source), "--apply",
                    "--out", str(sidecar_run_dir(source)),
                    "--branch", "draft",
                    "--xp-host", url,
                    "--guillotine", url,
                    "--storage-state", str(state),
                    "--cms-key", "/en",
                )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            out = sidecar_run_dir(source)
            spec = (out / "integrations" / "openapi.yaml").read_text(encoding="utf-8")
            self.assertIn("https://tourplan.example.test/api", spec)
            self.assertIn("x-production-endpoints", spec)
            self.assertNotIn("do-not-store", spec)
            spec_js = (
                out / "integrations" / "swagger-ui" / "spec.js"
            ).read_text(encoding="utf-8")
            self.assertIn("https://tourplan.example.test/api", spec_js)
            self.assertNotIn("do-not-store", spec_js)


if __name__ == "__main__":
    unittest.main()
