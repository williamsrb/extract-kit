"""enonic.baseline — visual and network baseline of surveyed pages via playwright-cli.

Optional. Local and review hosts only (same refusal as enonic.cms). A missing
binary or a failing command records a skip with a fix and never fails the run.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from extractkit_cli import cms_target
from extractkit_cli.common import load_json, load_yaml, write_text
from steps.enonic.cms import CmsConfig, resolve_cms
from steps.enonic.integrations import write_swagger_spec
from steps.enonic.live_config import is_secret

BINARY = "playwright-cli"
SESSION = "extractkit-baseline"
VIEWPORTS: tuple[tuple[str, int, int], ...] = (("desktop", 1440, 900), ("mobile", 390, 844))
TIMEOUT = 120
REQUEST_LINE = re.compile(r"^\s*\d+\.\s+\[(?P<method>[A-Z]+)\]\s+(?P<url>\S+)\s+=>\s+\[(?P<status>[^\]]+)\]")
REDACTED = "[redacted]"
_TAG = re.compile(r"<(?:meta|input)\b[^>]*>", re.IGNORECASE)
_TAG_NAME = re.compile(r"""\b(?:name|property|id)\s*=\s*(?P<q>['"])(?P<v>[^'"]*)(?P=q)""", re.IGNORECASE)
_TAG_VALUE = re.compile(r"""(?P<attr>\b(?:content|value)\s*=\s*)(?P<q>['"])[^'"]*(?P=q)""", re.IGNORECASE)
_SCRIPT_PAIR = re.compile(
    r"""(?P<key>(?P<kq>['"]?)(?P<k>[\w$.-]+)(?P=kq)\s*[:=]\s*)(?P<q>['"])(?P<v>(?:\\.|(?!(?P=q)).)*)(?P=q)""",
)
INSTALL_FIX = "npm install -g @playwright/cli, then rerun extractkit step inventory.baseline"
STATE_FIX = (
    "check that playwright-cli opens a browser (npm install -g @playwright/cli) and that the "
    "--storage-state file is a valid Playwright state, then rerun extractkit step inventory.baseline"
)


class CaptureError(Exception):
    pass


def slugify(path: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", path).strip("-").lower() or "root"


def base_url(cfg: CmsConfig, site_url: str | None) -> str:
    if site_url:
        return cms_target.normalize_url(site_url)
    return f"{cfg.host}/admin/site/preview/{cfg.project}/{cfg.branch}"


def page_url(base: str, path: str) -> str:
    return base + (path if path.startswith("/") else "/" + path)


def parse_requests(text: str) -> list[dict]:
    """`playwright-cli requests` lines -> method/url/status. Query strings are dropped."""
    rows: list[dict] = []
    for line in text.splitlines():
        match = REQUEST_LINE.match(line)
        if match:
            rows.append({
                "method": match.group("method"),
                "url": match.group("url").split("?", 1)[0],
                "status": match.group("status"),
            })
    return rows


def _pw(args: list[str], cwd: Path, *, session: str = SESSION) -> str:
    command = [BINARY, f"-s={session}", *args]
    try:
        result = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, check=False, timeout=TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CaptureError(f"{' '.join(args[:2])}: {exc}") from None
    if result.returncode != 0:
        detail = [ln.strip() for ln in (result.stdout + result.stderr).splitlines() if ln.strip()]
        raise CaptureError(f"{args[0]} failed: {' | '.join(detail[-5:])}")
    return result.stdout


def _capture_page(url: str, folder: Path, cwd: Path) -> tuple[dict[str, bool], list[dict], list[str]]:
    """Capture one page. Returns (written files, requests, failures)."""
    folder.mkdir(parents=True, exist_ok=True)
    written: dict[str, bool] = {}
    failures: list[str] = []
    requests: list[dict] = []
    for name, width, height in VIEWPORTS:
        shot = folder / f"{name}.png"
        try:
            _pw(["resize", str(width), str(height)], cwd)
            _pw(["goto", url], cwd)
            if name == "desktop":
                html = _pw(["--raw", "eval", "document.documentElement.outerHTML"], cwd)
                requests = parse_requests(_pw(["--raw", "requests", "--static"], cwd))
                write_text(folder / "page.html", redact_html(_unquote(html)))
                write_text(folder / "network.json", json.dumps(requests, indent=2))
                written["html"] = written["network"] = True
            _pw(["screenshot", f"--filename={shot}", "--full-page"], cwd)
            written[name] = shot.is_file()
            if not written[name]:
                failures.append(f"{name}.png was not written")
        except CaptureError as exc:
            failures.append(f"{name}: {exc}")
    return written, requests, failures


def redact_html(html: str) -> str:
    """Blank values whose meta/input name or inline-script key `is_secret` marks."""
    def secret(name: str) -> bool:
        return is_secret(name) or "csrf" in name.casefold()

    def tag(match: re.Match) -> str:
        name = _TAG_NAME.search(match.group(0))
        if not name or not secret(name.group("v")):
            return match.group(0)
        return _TAG_VALUE.sub(lambda m: f"{m.group('attr')}{m.group('q')}{REDACTED}{m.group('q')}", match.group(0))

    def pair(match: re.Match) -> str:
        if not secret(match.group("k")):
            return match.group(0)
        return f"{match.group('key')}{match.group('q')}{REDACTED}{match.group('q')}"

    return _SCRIPT_PAIR.sub(pair, _TAG.sub(tag, html))


def _unquote(raw: str) -> str:
    """`eval --raw` prints the page string JSON-encoded on its first line."""
    first = next((ln for ln in raw.splitlines() if ln.strip()), "")
    try:
        value = json.loads(first)
    except ValueError:
        return raw
    return value if isinstance(value, str) else raw


def _observed_hosts(pages: list[dict], own: set[str]) -> list[str]:
    hosts: set[str] = set()
    for page in pages:
        for request in page["requests"]:
            host = urlsplit(request["url"]).hostname or ""
            if host and host not in own:
                hosts.add(host)
    return sorted(hosts)


def _index(rows: list[dict], base: str, failure: str | None = None) -> str:
    lines = [
        "# Baseline",
        "",
        f"Captured through `{BINARY}` from `{base}`. Local or review hosts only.",
        "Screenshots are desktop 1440 and mobile 390; HTML is the rendered DOM.",
        "",
    ]
    if failure:
        lines += [
            "Not captured: the browser session did not start.",
            "",
            f"Failure: {failure}",
            f"Fix: {STATE_FIX}",
            "",
        ]
        return "\n".join(lines)
    if not rows:
        lines += ["No surveyed pages in `inventory/runtime.json`.", ""]
        return "\n".join(lines)
    lines += ["| path | folder | desktop | mobile | html | network |", "|---|---|---|---|---|---|"]
    for row in rows:
        mark = row["written"]
        lines.append(
            f"| `{row['path']}` | `{row['slug']}/` | "
            + " | ".join("yes" if mark.get(k) else "missing" for k in ("desktop", "mobile", "html", "network"))
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def _runtime_pages(ctx: Any) -> list[dict] | None:
    path = ctx.rel("inventory/runtime.json")
    if not path.is_file():
        return None
    seen: set[str] = set()
    pages: list[dict] = []
    for page in load_json(path, "inventory/runtime.json").get("pages") or []:
        if not isinstance(page, dict) or page.get("error"):
            continue
        target = str(page.get("path") or page.get("key") or "")
        if not target or target in seen:
            continue
        seen.add(target)
        pages.append({"path": target})
    return sorted(pages, key=lambda p: p["path"])


def _patch_observed_hosts(ctx: Any, hosts: list[str]) -> None:
    path = ctx.rel("integrations/openapi.yaml")
    if not hosts or not path.is_file():
        return
    spec = load_yaml(path, "integrations/openapi.yaml")
    spec["x-observed-hosts"] = hosts
    ctx.write_yaml("integrations/openapi.yaml", spec)
    dest = ctx.rel("integrations/swagger-ui")
    if dest.is_dir():
        ctx.plan.record(f"write {dest / 'spec.js'}")
        write_swagger_spec(dest, spec)


class EnonicBaselineStep:
    id = "enonic.baseline"
    requires = ("inventory/runtime.json",)
    produces = ("baseline/INDEX.md",)
    required = False

    def plan(self, _ctx: object) -> list[str]:
        return []

    def run(self, ctx: Any) -> None:
        cfg = resolve_cms(ctx)
        site_url = (ctx.cms or {}).get("site_url") or (ctx.profile.get("cms") or {}).get("site_url")
        if site_url:
            cms_target.assert_allowed(
                site_url, allow_production=cfg.allow_production, what="--site-url",
            )
        base = base_url(cfg, site_url)
        pages = _runtime_pages(ctx)
        if pages is None:
            ctx.record_skip(
                self.id, "no inventory/runtime.json to take page paths from",
                "run enonic.cms first: extractkit step inventory.runtime --profile enonic "
                "--source <legacy-checkout> --branch draft --storage-state <state.json>",
            )
            return
        if shutil.which(BINARY) is None:
            ctx.record_skip(self.id, f"{BINARY} is not on PATH", INSTALL_FIX)
            return
        if cfg.storage_state is None or not cfg.storage_state.expanduser().is_file():
            ctx.record_skip(
                self.id, "no readable --storage-state for the browser session",
                "pass --storage-state <playwright-state.json>",
            )
            return
        rows, failure = self._capture(ctx, cfg, base, pages)
        ctx.write_text("baseline/INDEX.md", _index(rows, base, failure))
        own = {urlsplit(base).hostname or "", urlsplit(cfg.host).hostname or ""}
        _patch_observed_hosts(ctx, _observed_hosts(rows, own))

    def _capture(self, ctx: Any, cfg: CmsConfig, base: str, pages: list[dict]) -> tuple[list[dict], str | None]:
        rows: list[dict] = []
        used: set[str] = set()
        with tempfile.TemporaryDirectory() as raw:
            cwd = Path(raw)
            try:
                _pw(["open"], cwd)
                _pw(["state-load", str(cfg.storage_state.expanduser().resolve())], cwd)
            except CaptureError as exc:
                ctx.record_skip(self.id, str(exc), STATE_FIX)
                self._close(cwd)
                return [], str(exc)
            for page in pages:
                slug = _unique(slugify(page["path"]), used)
                folder = ctx.rel(f"baseline/{slug}")
                ctx.plan.record(f"write {folder}/")
                written, requests, failures = _capture_page(page_url(base, page["path"]), folder, cwd)
                for failure in failures:
                    ctx.record_skip(
                        self.id, f"{page['path']} {failure}",
                        "check the page opens in the review XP with this storage-state, then rerun",
                    )
                rows.append({**page, "slug": slug, "written": written, "requests": requests})
            self._close(cwd)
        return rows, None

    @staticmethod
    def _close(cwd: Path) -> None:
        try:
            _pw(["close"], cwd)
        except CaptureError:
            pass

    def check(self, _ctx: object) -> list[str]:
        return []


def _unique(slug: str, used: set[str]) -> str:
    candidate, number = slug, 2
    while candidate in used:
        candidate = f"{slug}-{number}"
        number += 1
    used.add(candidate)
    return candidate
