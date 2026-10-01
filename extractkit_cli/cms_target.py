"""Classify XP hosts. Production is deny-by-default (FR-14)."""

from __future__ import annotations

from urllib.parse import urlparse

from .errors import ExtractkitError

BRANCHES = ("draft", "master")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
REVIEW_SUFFIX = ".k8s.seeds.no"


def normalize_url(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "http://" + text
    return text.rstrip("/")


def hostname_of(raw: str) -> str:
    parsed = urlparse(normalize_url(raw))
    return (parsed.hostname or "").lower()


def classify(raw: str) -> str:
    """Return local | review | production."""
    # Chromium reads `\` as `/`, so `prod\@localhost` would leave the host urlparse sees.
    if "\\" in raw or urlparse(normalize_url(raw)).username is not None:
        return "production"
    host = hostname_of(raw)
    if not host:
        return "production"
    if host in LOCAL_HOSTS or host.endswith(".localhost"):
        return "local"
    if host.endswith(REVIEW_SUFFIX):
        return "review"
    return "production"


def assert_allowed(raw: str, *, allow_production: bool, what: str) -> str:
    env = classify(raw)
    if env != "production":
        return env
    if allow_production:
        return "production"
    url = normalize_url(raw) or raw
    raise ExtractkitError(
        f"{what} {url} is a production host; runtime inventory is deny-by-default",
        "point --xp-host / --guillotine at localhost or a *.k8s.seeds.no "
        "review host; --allow-production is not used in the definition of done",
    )


def assert_branch(branch: str | None) -> str:
    value = (branch or "").strip()
    if value in BRANCHES:
        return value
    raise ExtractkitError(
        "enonic.cms requires --branch draft|master",
        "pass --branch draft (or master) when inventory.runtime runs",
        fix_args={"--branch": "draft"},
    )
