"""Log in to an Enonic XP admin and keep the session as a Playwright storage state.

XP 8 serves the system id provider at `/admin/_/idprovider/system` and XP 7 at
`/admin/tool/_/idprovider/system`; both take the same JSON body. The target is
any http(s) URL on the instance: its origin is used and both paths are tried,
unless the URL already names an id provider (`.../idprovider/<name>`), which is
then the only one tried. No host or project name is built in.
"""

from __future__ import annotations

import http.client
import json
import os
import urllib.error
import urllib.request
from http.cookiejar import Cookie, CookieJar
from pathlib import Path
from urllib.parse import urlparse, urlunparse

TIMEOUT = 20
# XP 8 first, then XP 7.
IDPROVIDER_PATHS = ("/admin/_/idprovider/system", "/admin/tool/_/idprovider/system")


class LoginError(Exception):
    """A login that did not give a session. The message never holds the password."""


def login_urls(target: str) -> list[str]:
    raw = target.strip()
    if not raw:
        raise LoginError("the url is empty")
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise LoginError(f"the url must be http(s) with a host, not {parsed.scheme or 'a bare string'}")
    if "/idprovider/" in parsed.path:
        return [urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))]
    return [f"{parsed.scheme}://{parsed.netloc}{path}" for path in IDPROVIDER_PATHS]


def login(target: str, user: str, password: str) -> CookieJar:
    """The session cookies of `user` on the instance at `target`, or LoginError."""
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    body = {"action": "login", "user": user, "password": password}
    failures: list[str] = []
    for url in login_urls(target):
        path = urlparse(url).path
        status, payload, detail = _post(opener, url, body)
        if payload and payload.get("authenticated") is True:
            if not len(jar):
                raise LoginError(f"{path}: logged in but no session cookie was set")
            return jar
        reason = payload.get("message") or "login refused" if payload else detail
        failures.append(f"{path} answered {status or 'no response'}: {reason}")
    raise LoginError("; ".join(failures))


def _post(opener: urllib.request.OpenerDirector, url: str, body: dict) -> tuple[int, dict | None, str]:
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            raw, status = response.read(), response.status
    except urllib.error.HTTPError as exc:
        raw, status = exc.read(), exc.code
    except (OSError, http.client.HTTPException) as exc:
        return 0, None, str(getattr(exc, "reason", None) or exc)
    text = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(text) if text else None
    except ValueError:
        payload = None
    first_line = (text.strip().splitlines() or [""])[0][:120]
    return status, payload if isinstance(payload, dict) else None, first_line


def storage_cookie(cookie: Cookie) -> dict:
    return {
        "name": cookie.name,
        "value": cookie.value,
        "domain": cookie.domain,
        "path": cookie.path or "/",
        "expires": cookie.expires if cookie.expires is not None else -1,
        "httpOnly": cookie.has_nonstandard_attr("HttpOnly"),
        "secure": bool(cookie.secure),
        "sameSite": "Lax",
    }


def write_storage_state(jar: CookieJar, path: Path) -> None:
    """A mode 0600 Playwright storage state; the session cookies are credentials."""
    state = {"cookies": [storage_cookie(c) for c in jar], "origins": []}
    write_private(path, json.dumps(state, indent=2))


def write_private(path: Path, text: str) -> None:
    """Create the file as 0600 from the start, so no one can read it before a chmod."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(path, 0o600)
