"""FR-14: production deny, required branch, mock Guillotine survey."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import urlparse

import yaml

from extractkit_cli import cms_target, manifest
from extractkit_cli.errors import ExtractkitError
from extractkit_cli.schema import validate
from steps.enonic.cms import context_for, resolve_cms, template_order
from tests.support import (
    STATIC_UNTIL,
    copy_fixture,
    install_override,
    run,
    sidecar_run_dir,
)

CONFIGENV_PATH = "/admin/tool/example.configenv/module-config"

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
def graphql_server(
    page: dict,
    *,
    usage: dict[str, int] | str | None = None,
    volume: bool = False,
    projects: list[dict] | None = None,
    configenv: bool = True,
) -> Iterator[tuple[list, str]]:
    """`usage`: per-descriptor totalCount, or "error" to fail every usage probe.

    `configenv=False` answers the Config Env tool with HTTP 404.
    """
    hits: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or "0")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            hits.append({"body": body, "cookie": self.headers.get("Cookie")})
            query = body.get("query") or ""
            if usage == "error" and "first: 0" in query:
                payload = {"errors": [{"message": "Unknown field"}]}
            elif volume and "aggregations:" in query:
                buckets = (
                    {"languages": {"buckets": [
                        {"key": "en", "docCount": 4}, {"key": "no", "docCount": 2},
                    ]}}
                    if "languages" in query
                    else {"types": {"buckets": [
                        {"key": "media:image", "docCount": 7}, {"key": "media:document", "docCount": 1},
                    ]}}
                )
                payload = {"data": {"guillotine": {"queryConnection": {
                    "totalCount": 8 if "media" in query else 6,
                    "aggregationsAsJson": json.dumps(buckets),
                }}}}
            elif volume and "type = 'com.example.mini:mini-article'" in query:
                payload = {"data": {"guillotine": {"queryConnection": {"totalCount": 12}}}}
            elif "components." in query and "queryConnection" in query:
                if usage == "error":
                    payload = {"errors": [{"message": "Unknown field components"}]}
                else:
                    key = query.split("descriptor = '")[1].split("'")[0]
                    count = (usage or {}).get(key, 0)
                    payload = {"data": {"guillotine": {
                        "queryConnection": {"totalCount": count},
                    }}}
            elif "queryConnection" in query:
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
            if parsed.path.endswith("/cs/project/list") and projects is not None:
                raw = json.dumps(projects).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            if configenv and ("configenv" in parsed.path or parsed.path.endswith("module-config")):
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

    def test_a_configured_suffix_is_review(self) -> None:
        with mock.patch.dict(os.environ, {"EXTRACTKIT_REVIEW_SUFFIXES": ".review.example.test"}):
            self.assertEqual(cms_target.classify("https://app.review.example.test"), "review")
            self.assertEqual(cms_target.classify("https://app.example.test"), "production")

    def test_no_suffix_is_review_by_default(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(cms_target.classify("https://app.review.example.test"), "production")

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
                "run", "--profile", "enonic", "--source", str(source),
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--branch", result.stdout + result.stderr)

    def test_mock_guillotine_writes_runtime_and_round2(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            source = copy_fixture(parent)
            install_override(source)
            state = parent / "state.json"
            _storage_state(state)
            with graphql_server(PAGE_AS_JSON) as (hits, url):
                result = run(
                    "step", "enonic.cms", "--profile", "enonic",
                    "--source", str(source),
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

    def _run_cms(self, parent: Path, source: Path, url: str, configenv: bool = False) -> dict:
        state = parent / "state.json"
        _storage_state(state)
        result = run(
            "step", "enonic.cms", "--profile", "enonic",
            "--source", str(source), "--branch", "draft",
            "--xp-host", url, "--guillotine", url,
            "--storage-state", str(state), "--cms-key", "/en",
            *(["--configenv", f"{url}{CONFIGENV_PATH}"] if configenv else []),
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        runtime = sidecar_run_dir(source) / "inventory" / "runtime.json"
        payload = json.loads(runtime.read_text(encoding="utf-8"))
        validate(payload, "runtime-inventory")
        return payload

    def test_usage_probe_counts_page_layout_and_part(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            source = copy_fixture(parent)
            with graphql_server(PAGE_AS_JSON, usage={"com.example.mini:mini-part": 7}) as (hits, url):
                payload = self._run_cms(parent, source, url)
            self.assertEqual(payload["usageProbe"], "ok")
            self.assertEqual(payload["usage"], {
                "com.example.mini:layout:mini-layout": 0,
                "com.example.mini:page:mini-page": 0,
                "com.example.mini:part:mini-part": 7,
            })
            probes = [h for h in hits if "components." in h["body"]["query"]]
            self.assertEqual(len(probes), 3)
            self.assertIn("first: 0", probes[0]["body"]["query"])
            self.assertNotIn("mini-macro", json.dumps(payload["usage"]))

    def test_usage_probe_graphql_error_degrades_to_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            source = copy_fixture(parent)
            with graphql_server(PAGE_AS_JSON, usage="error") as (hits, url):
                payload = self._run_cms(parent, source, url)
            self.assertEqual(payload["usageProbe"], "unsupported")
            self.assertEqual(set(payload["usage"].values()), {None})
            probes = [h for h in hits if "components." in h["body"]["query"]]
            self.assertEqual(len(probes), 1)

    def test_content_volume_counts_languages_media_and_projects(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            source = copy_fixture(parent)
            projects = [{"name": "en"}, {"name": "no", "parent": "en"}]
            with graphql_server(PAGE_AS_JSON, volume=True, projects=projects) as (hits, url):
                self._run_cms(parent, source, url)
            out = sidecar_run_dir(source) / "inventory"
            doc = json.loads((out / "content-volume.json").read_text())
            validate(doc, "content-volume")
            totals = {row["type"]: row["total"] for row in doc["types"]}
            self.assertEqual(totals["com.example.mini:mini-article"], 12)
            self.assertEqual(totals["portal:site"], 0)
            self.assertEqual(doc["languages"], [
                {"language": "en", "count": 4}, {"language": "no", "count": 2},
            ])
            self.assertEqual(doc["media"]["total"], 8)
            self.assertEqual(doc["media"]["byType"][0], {"type": "media:image", "count": 7})
            self.assertEqual(doc["projects"], [{"name": "en"}, {"name": "no", "parent": "en"}])
            self.assertNotIn("projectsReason", doc)
            md = (out / "content-volume.md").read_text()
            self.assertIn("| `com.example.mini:mini-article` | 12 |", md)
            self.assertIn("| no | en |", md)
            probes = [h for h in hits if "first: 0" in h["body"]["query"] and "type = " in h["body"]["query"]]
            self.assertTrue(probes)

    def test_content_volume_project_list_404_writes_null_with_status(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            source = copy_fixture(parent)
            with graphql_server(PAGE_AS_JSON, volume=True) as (_hits, url):
                self._run_cms(parent, source, url)
            doc = json.loads((sidecar_run_dir(source) / "inventory/content-volume.json").read_text())
            validate(doc, "content-volume")
            self.assertIsNone(doc["projects"])
            self.assertEqual(doc["projectsReason"], "HTTP 404")

    def test_content_volume_unsupported_queries_are_unknown_not_zero(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            source = copy_fixture(parent)
            with graphql_server(PAGE_AS_JSON, usage="error") as (_hits, url):
                self._run_cms(parent, source, url)
            doc = json.loads((sidecar_run_dir(source) / "inventory/content-volume.json").read_text())
            validate(doc, "content-volume")
            self.assertEqual({row["total"] for row in doc["types"]}, {None})
            self.assertIsNone(doc["languages"])
            self.assertIsNone(doc["media"]["total"])
            self.assertIn("unknown", (sidecar_run_dir(source) / "inventory/content-volume.md").read_text())

    def test_enonic_profile_reads_config_env_from_the_given_url(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            source = copy_fixture(parent)
            with graphql_server(PAGE_AS_JSON) as (_hits, url):
                payload = self._run_cms(parent, source, url, configenv=True)
            self.assertEqual(payload["configenv"], f"{url}{CONFIGENV_PATH}")
            self.assertEqual(len(payload["configEnv"]), 3)
            self.assertEqual(
                [e["provider"] for e in payload["endpoints"]],
                ["env-travelSpecialistSyncEndpoint"],
            )
            manifest_doc = yaml.safe_load((sidecar_run_dir(source) / "MANIFEST.yaml").read_text())
            self.assertEqual(manifest_doc["skips"], [])

    def test_missing_config_env_tool_is_a_recorded_skip(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            source = copy_fixture(parent)
            with graphql_server(PAGE_AS_JSON, configenv=False) as (_hits, url):
                payload = self._run_cms(parent, source, url, configenv=True)
            self.assertEqual(payload["configEnv"], [])
            manifest_doc = yaml.safe_load((sidecar_run_dir(source) / "MANIFEST.yaml").read_text())
            skips = {row["step"]: row for row in manifest_doc["skips"]}
            self.assertIn("HTTP 404", skips["enonic.cms.configenv"]["reason"])
            self.assertIn("--configenv", skips["enonic.cms.configenv"]["fix"])

    def test_a_profile_without_a_config_env_path_has_no_default_url(self) -> None:
        ctx = SimpleNamespace(
            profile={"name": "t", "cms": {"host": "http://localhost:8080", "project": "en"}},
            cms={"branch": "draft", "cms_keys": ["/en"]},
        )
        self.assertEqual(resolve_cms(ctx).configenv, "")

    def _candidates(self, source: Path) -> list[dict]:
        path = sidecar_run_dir(source) / "inventory" / "live-config-candidates.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_live_config_candidates_list_url_and_hostmap_keys(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            source = copy_fixture(parent)
            with graphql_server(PAGE_AS_JSON) as (_hits, url):
                self._run_cms(parent, source, url, configenv=True)
            rows = {(r["origin"], r["key"]): r for r in self._candidates(source)}
            self.assertEqual(rows[("configEnv", "env-hostMap")]["kind"], "hostmap")
            self.assertFalse(rows[("configEnv", "env-hostMap")]["covered"])
            self.assertEqual(rows[("configEnv", "env-travelSpecialistSyncEndpoint")]["kind"], "url")
            self.assertTrue(rows[("configEnv", "env-travelSpecialistSyncEndpoint")]["covered"])
            site_url = [r for r in rows.values() if r["key"].endswith("tourplanUrl")]
            self.assertEqual([r["kind"] for r in site_url], ["url"])
            self.assertFalse(site_url[0]["covered"])
            keys = " ".join(r["key"].casefold() for r in rows.values())
            self.assertNotIn("simplesecret", keys)
            self.assertNotIn("password", keys)
            self.assertNotIn("netaxeptenv", keys)

    def test_candidates_are_covered_once_the_rules_name_the_key(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            source = copy_fixture(parent)
            override = source / ".extractkit"
            override.mkdir()
            (override / "profile.yaml").write_text(
                "live_config:\n  hostmap_keys: [env-hostmap]\n  site_url_keys: [tourplanurl]\n",
                encoding="utf-8",
            )
            with graphql_server(PAGE_AS_JSON) as (_hits, url):
                self._run_cms(parent, source, url, configenv=True)
            rows = {r["key"]: r for r in self._candidates(source)}
            self.assertTrue(rows["env-hostMap"]["covered"])
            self.assertTrue(next(r for k, r in rows.items() if k.endswith("tourplanUrl"))["covered"])

    def test_explicit_configenv_flag_still_harvests_without_a_client_profile(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            source = copy_fixture(parent)
            state = parent / "state.json"
            _storage_state(state)
            with graphql_server(PAGE_AS_JSON) as (_hits, url):
                result = run(
                    "step", "enonic.cms", "--profile", "enonic", "--source", str(source),
                    "--branch", "draft", "--xp-host", url, "--guillotine", url,
                    "--storage-state", str(state), "--cms-key", "/en",
                    "--configenv", f"{url}/admin/tool/example/module-config",
                )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            payload = json.loads((sidecar_run_dir(source) / "inventory/runtime.json").read_text())
            self.assertEqual(len(payload["configEnv"]), 3)
            self.assertEqual(
                [e["provider"] for e in payload["endpoints"]],
                ["env-travelSpecialistSyncEndpoint"],
            )

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
                "live_config": {"configenv_path": "/admin/tool/example/module-config"},
            },
            cms={"branch": "draft"},
        )
        cfg = resolve_cms(ctx)
        self.assertEqual(cfg.round2, ["home"])
        self.assertEqual(cfg.sample_per_type, 3)
        self.assertTrue(cfg.guillotine.endswith("/admin/site/preview/en/draft"))
        self.assertNotIn("com.example.app/graphql", cfg.guillotine)
        self.assertTrue(
            cfg.configenv.endswith("/admin/tool/example/module-config"),
        )

    def test_cms_patches_openapi_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            source = copy_fixture(parent)
            install_override(source)
            state = parent / "state.json"
            _storage_state(state)
            static = run(
                "run", "--profile", "enonic", "--source", str(source),
                *STATIC_UNTIL,
            )
            self.assertEqual(static.returncode, 0, static.stderr + static.stdout)
            with graphql_server(PAGE_AS_JSON) as (_hits, url):
                result = run(
                    "step", "enonic.cms", "--profile", "enonic",
                    "--source", str(source),
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
            self.assertIn("x-observed-endpoints", spec)
            self.assertNotIn("do-not-store", spec)
            spec_js = (
                out / "integrations" / "swagger-ui" / "spec.js"
            ).read_text(encoding="utf-8")
            self.assertIn("https://tourplan.example.test/api", spec_js)
            self.assertNotIn("do-not-store", spec_js)


if __name__ == "__main__":
    unittest.main()
