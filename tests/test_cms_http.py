"""The CMS HTTP helpers keep the admin cookie and the production check on the host that was named."""

from __future__ import annotations

import http.server
import threading
import unittest
from urllib import request as urlrequest

from extractkit_cli.errors import ExtractkitError
from steps.enonic import cms

COOKIE = "JSESSIONID=SECRET-SESSION"


def serve(handler: type[http.server.BaseHTTPRequestHandler]) -> http.server.HTTPServer:
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class Quiet(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        pass


class RedirectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.seen: list[str | None] = []
        seen = self.seen

        class Target(Quiet):
            def do_GET(self) -> None:
                seen.append(self.headers.get("Cookie"))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"data": {}}')

            do_POST = do_GET

        self.target = serve(Target)
        port = self.target.server_address[1]
        self.addCleanup(self.target.server_close)
        self.addCleanup(self.target.shutdown)

        class Start(Quiet):
            to = f"http://localhost:{port}/x"

            def do_GET(self) -> None:
                self.send_response(302)
                self.send_header("Location", self.to)
                self.end_headers()

            do_POST = do_GET

        self.Start = Start

    def start(self, to: str | None = None) -> str:
        if to:
            self.Start.to = to
        server = serve(self.Start)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}/start"

    def test_a_redirect_to_another_host_is_refused_and_gets_no_cookie(self) -> None:
        with self.assertRaises(ExtractkitError) as raised:
            cms.http_get(self.start(), COOKIE)
        self.assertEqual(raised.exception.code, "redirect_refused")
        self.assertEqual(self.seen, [])

    def test_the_graphql_post_is_guarded_the_same_way(self) -> None:
        with self.assertRaises(ExtractkitError) as raised:
            cms.post_graphql(self.start(), "{ a }", COOKIE)
        self.assertEqual(raised.exception.code, "redirect_refused")
        self.assertEqual(self.seen, [])

    def test_a_redirect_on_the_same_host_is_followed_with_the_cookie(self) -> None:
        port = self.target.server_address[1]
        status, body = cms.http_get(self.start(to=f"http://127.0.0.1:{port}/final"), COOKIE)
        self.assertEqual((status, body), (200, b'{"data": {}}'))
        self.assertEqual(self.seen, [COOKIE])

    def test_https_never_falls_back_to_http(self) -> None:
        handler = cms._SameHostRedirects()
        req = urlrequest.Request("https://xp.example.test/a")
        with self.assertRaises(ExtractkitError):
            handler.redirect_request(req, None, 302, "Found", {}, "http://xp.example.test/b")

    def test_only_http_and_https_urls_are_opened(self) -> None:
        for url in ("file:///etc/passwd", "ftp://xp.example.test/"):
            with self.subTest(url=url), self.assertRaises(ExtractkitError):
                cms.http_get(url, COOKIE)


if __name__ == "__main__":
    unittest.main()
