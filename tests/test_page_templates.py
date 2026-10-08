"""Enonic-only page-template resolve order and SAMPLE_PER_TYPE cap."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from extractkit_cli.schema import validate
from steps.enonic import page_templates as pt
from tests.support import copy_fixture, run, sidecar_run_dir
from tests.test_cms import CONFIGENV_HTML, CS_SITE_BODY, PAGE_AS_JSON, _storage_state

ARTICLE_TYPE = "com.example.mini:mini-article"
ARTICLE_PAGE = {
    "descriptor": "com.example.mini:mini-page",
    "type": "page",
    "regions": {
        "main": {
            "components": [
                {
                    "descriptor": "com.example.mini:mini-layout",
                    "type": "layout",
                    "path": "/main/0",
                }
            ]
        }
    },
}
FORBIDDEN_PAGE = {
    "descriptor": "com.example.mini:forbidden",
    "type": "page",
    "regions": {"main": {"components": []}},
}


def _tmpl(
    path: str,
    supports: list[str],
    page: dict,
    folder_index: int,
) -> pt.PageTemplate:
    return pt.parse_template(
        {
            "_path": path,
            "_id": path,
            "dataAsJson": {"supports": supports},
            "pageAsJson": page,
        },
        folder_index,
    )


class PageTemplateUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.templates = [
            _tmpl(
                "/en/_templates/article",
                [ARTICLE_TYPE],
                ARTICLE_PAGE,
                0,
            ),
            _tmpl(
                "/en/_templates/default-template",
                ["portal:site"],
                PAGE_AS_JSON,
                1,
            ),
            _tmpl(
                "/en/_templates/forbidden-page",
                [ARTICLE_TYPE, "portal:site", "base:folder"],
                FORBIDDEN_PAGE,
                2,
            ),
        ]

    def test_sample_per_type_default_is_three(self) -> None:
        self.assertEqual(pt.SAMPLE_PER_TYPE, 3)
        self.assertEqual(pt.sample_per_type({}), 3)
        self.assertEqual(pt.sample_per_type({"sample_per_type": 3}), 3)
        self.assertEqual(pt.sample_per_type({"sample_per_type": 5}), 5)
        self.assertEqual(
            pt.sample_per_type({"sample_per_type": 5}, {"sample_per_type": 2}),
            2,
        )

    def test_cap_nodes_keeps_first_n(self) -> None:
        nodes = [{"i": i} for i in range(8)]
        self.assertEqual(len(pt.cap_nodes(nodes, 3)), 3)
        self.assertEqual(pt.cap_nodes(nodes, 3)[-1]["i"], 2)

    def test_customized_beats_implicit_and_forbidden(self) -> None:
        page = {
            "descriptor": "com.example.mini:mini-page",
            "regions": {"main": {"components": [{"descriptor": "x:y"}]}},
        }
        result = pt.resolve_page(ARTICLE_TYPE, page, self.templates)
        self.assertEqual(result.source, "customized")
        self.assertTrue(result.customized)
        self.assertIsNone(result.template_path)
        self.assertEqual(result.implicit_path, "/en/_templates/article")
        self.assertEqual(
            list(result.implicit_paths),
            ["/en/_templates/article", "/en/_templates/forbidden-page"],
        )

    def test_explicit_template_beats_implicit(self) -> None:
        page = {"template": "/en/_templates/forbidden-page"}
        result = pt.resolve_page(ARTICLE_TYPE, page, self.templates)
        self.assertEqual(result.source, "explicit-page-template")
        self.assertEqual(result.template_path, "/en/_templates/forbidden-page")
        self.assertEqual(result.effective.get("descriptor"), "com.example.mini:forbidden")

    def test_implicit_first_folder_match_not_catch_all(self) -> None:
        result = pt.resolve_page(ARTICLE_TYPE, {}, self.templates)
        self.assertEqual(result.source, "implicit-page-template")
        self.assertEqual(result.template_path, "/en/_templates/article")
        self.assertNotEqual(result.template_path, "/en/_templates/forbidden-page")
        self.assertEqual(
            result.effective.get("descriptor"),
            "com.example.mini:mini-page",
        )

    def test_site_uses_default_template_not_forbidden(self) -> None:
        result = pt.resolve_page("portal:site", {}, self.templates)
        self.assertEqual(result.source, "implicit-page-template")
        self.assertEqual(result.template_path, "/en/_templates/default-template")

    def test_no_match_is_none(self) -> None:
        result = pt.resolve_page("com.example.app:orphan", {}, self.templates)
        self.assertEqual(result.source, "none")
        self.assertEqual(result.effective, {})

    def test_guillotine_page_template_field_is_not_explicit(self) -> None:
        page = {}
        result = pt.resolve_page(ARTICLE_TYPE, page, self.templates)
        self.assertEqual(result.explicit, None)
        self.assertEqual(result.source, "implicit-page-template")

    def test_content_type_ids_are_app_name_plus_portal_extras(self) -> None:
        ids = pt.content_type_ids([
            {"kind": "content-type", "app": "com.example.mini", "name": "mini-article"},
            {"kind": "part", "app": "com.example.mini", "name": "mini-part"},
        ])
        self.assertEqual(
            ids,
            [
                ARTICLE_TYPE,
                "portal:site",
                "portal:page-template",
                "portal:fragment",
            ],
        )

    def test_compact_and_edges(self) -> None:
        tree = pt.compact_page(PAGE_AS_JSON)
        self.assertIsNotNone(tree)
        self.assertEqual(tree["descriptor"], "com.example.mini:mini-page")
        edges = pt.component_edges([tree])
        pairs = {(e["parent"], e["child"]) for e in edges}
        self.assertIn(("com.example.mini:mini-page", "com.example.mini:mini-layout"), pairs)


@contextmanager
def implicit_survey_server() -> Iterator[tuple[list, list, str]]:
    posts: list[dict] = []
    gets: list[str] = []
    templates = {
        "/en/_templates/article": {
            "_id": "t-article",
            "_path": "/en/_templates/article",
            "_name": "article",
            "type": "portal:page-template",
            "displayName": "Article",
            "dataAsJson": {"supports": [ARTICLE_TYPE]},
            "pageAsJson": ARTICLE_PAGE,
        },
        "/en/_templates/default-template": {
            "_id": "t-default",
            "_path": "/en/_templates/default-template",
            "_name": "default-template",
            "type": "portal:page-template",
            "displayName": "Default",
            "dataAsJson": {"supports": ["portal:site"]},
            "pageAsJson": PAGE_AS_JSON,
        },
        "/en/_templates/forbidden-page": {
            "_id": "t-forbidden",
            "_path": "/en/_templates/forbidden-page",
            "_name": "forbidden-page",
            "type": "portal:page-template",
            "displayName": "Forbidden",
            "dataAsJson": {"supports": [ARTICLE_TYPE, "portal:site"]},
            "pageAsJson": FORBIDDEN_PAGE,
        },
    }
    articles = [
        {
            "_id": "a-custom",
            "_path": "/en/articles/custom",
            "displayName": "Custom",
            "type": ARTICLE_TYPE,
            "pageAsJson": ARTICLE_PAGE,
        },
        {
            "_id": "a-one",
            "_path": "/en/articles/one",
            "displayName": "One",
            "type": ARTICLE_TYPE,
            "pageAsJson": {},
        },
        {
            "_id": "a-two",
            "_path": "/en/articles/two",
            "displayName": "Two",
            "type": ARTICLE_TYPE,
            "pageAsJson": {},
        },
        {
            "_id": "a-three-dropped",
            "_path": "/en/articles/three",
            "displayName": "Three",
            "type": ARTICLE_TYPE,
            "pageAsJson": {},
        },
    ]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or "0")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            posts.append(body)
            query = body.get("query") or ""
            if "queryConnection" in query:
                if ARTICLE_TYPE in query:
                    payload = {
                        "data": {
                            "guillotine": {
                                "queryConnection": {
                                    "totalCount": 4,
                                    "edges": [{"node": row} for row in articles],
                                }
                            }
                        }
                    }
                else:
                    payload = {
                        "data": {
                            "guillotine": {
                                "queryConnection": {"totalCount": 0, "edges": []},
                            }
                        }
                    }
            elif "getChildren" in query:
                payload = {
                    "data": {
                        "guillotine": {
                            "getChildren": [
                                {
                                    "_path": path,
                                    "type": "portal:page-template",
                                    "_name": row["_name"],
                                }
                                for path, row in templates.items()
                            ]
                        }
                    }
                }
            else:
                key = "/en"
                marker = 'get(key: "'
                if marker in query:
                    key = query.split(marker, 1)[1].split('"', 1)[0]
                if key in templates:
                    got = templates[key]
                else:
                    got = {
                        "_id": "id-1",
                        "_path": "/en",
                        "type": "portal:site",
                        "displayName": "EN",
                        "pageAsJson": {},
                        "components": [],
                    }
                payload = {"data": {"guillotine": {"get": got}}}
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            gets.append(self.path)
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
        yield posts, gets, f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()


class ImplicitSurveyCliTests(unittest.TestCase):
    def test_implicit_templates_fill_template_order_and_pin_cs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            source = copy_fixture(parent)
            state = parent / "state.json"
            _storage_state(state)
            with implicit_survey_server() as (_posts, gets, url):
                result = run(
                    "step", "enonic.cms", "--profile", "enonic",
                    "--source", str(source),
                    "--branch", "draft",
                    "--xp-host", url,
                    "--guillotine", url,
                    "--storage-state", str(state),
                    "--cms-key", "/en",
                )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            cs_gets = [path for path in gets if "content/content" in path]
            self.assertEqual(len(cs_gets), 1)
            out = sidecar_run_dir(source)
            runtime = json.loads(
                (out / "inventory" / "runtime.json").read_text(encoding="utf-8"),
            )
            by_key = {row["key"]: row for row in runtime["pages"]}
            site = by_key["/en"]
            self.assertEqual(site["resolve"], "implicit-page-template")
            self.assertEqual(
                site["resolvedTemplate"],
                "/en/_templates/default-template",
            )
            self.assertEqual(
                site["templateOrder"],
                [
                    "com.example.mini:mini-page",
                    "com.example.mini:mini-layout",
                    "com.example.mini:mini-part",
                ],
            )
            custom = by_key["/en/articles/custom"]
            self.assertEqual(custom["resolve"], "customized")
            implicit = by_key["/en/articles/one"]
            self.assertEqual(implicit["resolve"], "implicit-page-template")
            self.assertEqual(
                implicit["resolvedTemplate"],
                "/en/_templates/article",
            )
            self.assertNotIn("/en/articles/three", by_key)
            resolved = json.loads(
                (out / "inventory" / "content-survey-resolved.json").read_text(
                    encoding="utf-8",
                ),
            )
            validate(resolved, "content-survey-resolved")
            self.assertEqual(
                resolved["templatesFolderOrder"][-1],
                "/en/_templates/forbidden-page",
            )
            article_row = next(
                row for row in resolved["types"] if row["type"] == ARTICLE_TYPE
            )
            self.assertEqual(article_row["totalCount"], 4)
            self.assertEqual(len(article_row["sampled"]), 3)
            self.assertEqual(article_row["sampled"][0]["resolve"], "customized")
            self.assertEqual(
                article_row["sampled"][1]["resolvedTemplate"],
                "/en/_templates/article",
            )


if __name__ == "__main__":
    unittest.main()
