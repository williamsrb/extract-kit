"""`xp_login` logs in to an XP 8 or XP 7 admin from any URL and writes a storage state the kit accepts."""

from __future__ import annotations

import http.server
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from extractkit_cli import resources, xp_login
from steps.enonic import cms

XP8 = "/admin/_/idprovider/system"
XP7 = "/admin/tool/_/idprovider/system"
PASSWORD = "not-a-real-password"


def serve(*paths: str) -> http.server.HTTPServer:
    """An idprovider answering only on `paths`; the login is su / PASSWORD."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            known = self.path in paths
            ok = known and body == {"action": "login", "user": "su", "password": PASSWORD}
            self.send_response(200 if known else 404)
            self.send_header("Content-Type", "application/json")
            if ok:
                self.send_header("Set-Cookie", "JSESSIONID=abc123; Path=/; HttpOnly")
            self.end_headers()
            self.wfile.write(json.dumps({"authenticated": ok, "message": "bad login"}).encode())

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class LoginUrlTests(unittest.TestCase):
    def test_any_url_on_the_instance_tries_xp8_then_xp7(self) -> None:
        for target in ("https://xp.example.test", "xp.example.test/", "https://xp.example.test/admin/site/preview/en/draft?a=1"):
            with self.subTest(target=target):
                self.assertEqual(xp_login.login_urls(target), [f"https://xp.example.test{XP8}", f"https://xp.example.test{XP7}"])

    def test_an_id_provider_url_is_the_only_one_tried(self) -> None:
        self.assertEqual(
            xp_login.login_urls("http://localhost:8080/admin/tool/_/idprovider/ldap?x=1"),
            ["http://localhost:8080/admin/tool/_/idprovider/ldap"],
        )

    def test_a_url_that_is_not_http_is_refused(self) -> None:
        for target in ("", "file:///etc/passwd", "ftp://xp.example.test"):
            with self.subTest(target=target), self.assertRaises(xp_login.LoginError):
                xp_login.login_urls(target)


class LoginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="xp-login-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def target(self, server: http.server.HTTPServer) -> str:
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def test_an_xp8_instance(self) -> None:
        jar = xp_login.login(self.target(serve(XP8)), "su", PASSWORD)
        self.assertEqual({c.name: c.value for c in jar}, {"JSESSIONID": "abc123"})

    def test_an_xp7_instance_answers_404_on_the_xp8_path(self) -> None:
        jar = xp_login.login(self.target(serve(XP7)), "su", PASSWORD)
        self.assertEqual({c.name: c.value for c in jar}, {"JSESSIONID": "abc123"})

    def test_a_refused_login_names_the_paths_and_never_the_password(self) -> None:
        with self.assertRaises(xp_login.LoginError) as raised:
            xp_login.login(self.target(serve(XP8, XP7)), "su", "wrong-one")
        self.assertIn(XP8, str(raised.exception))
        self.assertIn("bad login", str(raised.exception))
        self.assertNotIn("wrong-one", str(raised.exception))

    def test_an_unreachable_host_is_a_login_error(self) -> None:
        server = serve(XP8)
        target = self.target(server)
        server.shutdown()
        server.server_close()
        with self.assertRaises(xp_login.LoginError):
            xp_login.login(target, "su", PASSWORD)

    def test_the_storage_state_is_private_and_readable_by_the_kit(self) -> None:
        state = self.tmp / "sub" / "state.json"
        xp_login.write_storage_state(xp_login.login(self.target(serve(XP8)), "su", PASSWORD), state)
        self.assertEqual(state.stat().st_mode & 0o777, 0o600)
        cookie = json.loads(state.read_text())["cookies"][0]
        self.assertEqual((cookie["name"], cookie["value"], cookie["httpOnly"]), ("JSESSIONID", "abc123", True))
        self.assertEqual(cms.cookies_from_storage_state(state), "JSESSIONID=abc123")
        self.assertIn("127.0.0.1", resources._cookie_domains(state))


if __name__ == "__main__":
    unittest.main()
