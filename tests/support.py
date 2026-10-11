"""Shared test helpers. Copy fixtures to a temp dir so sidecars never hit the kit."""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "tests" / "fixtures" / "enonic-mini"

# Preflight (`deps`, `doctor --source`) installs the kit into $HOME. Every CLI
# subprocess gets a throwaway HOME so the suite never links into the real one.
TEST_HOME = Path(tempfile.mkdtemp(prefix="extractkit-home-"))
atexit.register(shutil.rmtree, TEST_HOME, ignore_errors=True)

from extractkit_cli import install as _install

_install.install(home=TEST_HOME)

# `devkit` is a required dependency; the suite gets a stub instead of the real one.
_STUB_DEVKIT = TEST_HOME / ".local" / "bin" / "devkit"
_STUB_DEVKIT.parent.mkdir(parents=True, exist_ok=True)
shutil.copy(REPO / "tests" / "fixtures" / "fake_devkit.py", _STUB_DEVKIT)
_STUB_DEVKIT.chmod(0o755)

# Subprocess runs go through the installed launcher, the way an operator runs
# the kit: they exercise the detached copy, not the working tree.
CLI = [sys.executable, str(_install.launcher_path(TEST_HOME))]


# The CLI refuses to run from the kit, so a test with no source of its own runs here.
TEST_CWD = TEST_HOME / "cwd"
TEST_CWD.mkdir(exist_ok=True)


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        **os.environ,
        "HOME": str(TEST_HOME),
        "PATH": f"{TEST_HOME / '.local' / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
    }
    for name in [n for n in env if n.startswith("EXTRACTKIT_")]:
        del env[name]
    env.update(extra or {})
    return env


def run(
    *args: str, cwd: Path | None = None, env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*CLI, *args], cwd=cwd or TEST_CWD, capture_output=True, text=True, check=False,
        env=_env(env),
    )


def run_checkout(
    *args: str, cwd: Path | None = None, env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the checkout's own `extractkit`, as `./extractkit` does inside the kit repo."""
    return subprocess.run(
        [sys.executable, str(REPO / "extractkit"), *args], cwd=cwd or REPO,
        capture_output=True, text=True, check=False, env=_env(env),
    )


def copy_fixture(parent: Path) -> Path:
    dest = parent / "legacy"
    shutil.copytree(FIXTURE, dest)
    return dest


AS_OVERLAY = REPO / "tests" / "fixtures" / "profiles" / "as.yaml"


def install_override(source: Path, overlay: Path = AS_OVERLAY) -> Path:
    """Copy `overlay` to `<source>/.extractkit/profile.yaml`, the operator override."""
    dest = source / ".extractkit" / "profile.yaml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(overlay, dest)
    return dest


def as_profile() -> dict:
    """The enonic stack with the AS fixture composed on top, as a run would see it."""
    from extractkit_cli import manifest

    with tempfile.TemporaryDirectory() as raw:
        source = Path(raw)
        install_override(source)
        return manifest.compose_overlays(manifest.load("enonic"), None, source)[0]


def git_init(path: Path) -> None:
    subprocess.run(
        ["git", "init"], cwd=path, check=True, capture_output=True, text=True,
    )
    subprocess.run(
        ["git", "add", "."], cwd=path, check=True, capture_output=True, text=True,
    )
    subprocess.run(
        [
            "git", "-c", "user.email=kit@example.test", "-c", "user.name=kit",
            "commit", "-m", "init",
        ],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )


def porcelain(path: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def sidecar_run_dir(source: Path) -> Path:
    extract = source / ".extract"
    runs = [p for p in extract.iterdir() if p.is_dir() and p.name != ".gitignore"]
    if not runs:
        raise AssertionError(f"no run directory under {extract}")
    return max(runs, key=lambda p: p.name)


STATIC_UNTIL = ("--until", "inventory.integrations")


def build_sidecar(parent: Path) -> tuple[Path, Path]:
    """Fixture checkout plus a sidecar run through spec.kit (no CMS)."""
    source = copy_fixture(parent)
    for args in (
        ("--until", "inventory.integrations"),
        ("--from", "maps.merge", "--until", "spec.kit"),
    ):
        extra = ("--out", str(sidecar_run_dir(source))) if "--from" in args else ()
        result = run("run", "--profile", "enonic", "--source", str(source), *extra, *args)
        if result.returncode != 0:
            raise AssertionError(result.stderr + result.stdout)
    return source, sidecar_run_dir(source)


BUSINESS_SECTIONS = (
    "Purpose and audience", "Actors", "Capabilities", "Business flow",
    "Business rules by capability", "Glossary", "Integrations", "Open questions",
)


def valid_constitution() -> str:
    """A constitution/project.md that passes `check` on the fixture sidecar."""
    return """## Product

The mini site serves articles to visitors.

Evidence: `com.example.mini:content-type:mini-article`

## Stack

- Enonic XP site application.

Evidence: `xp/src/main/resources/site/site.xml:1`

## Architecture

Pages are assembled from parts and layouts _(inferred)_.

Evidence: `com.example.mini:part:mini-part`, `content`

## Conventions

- One folder per component under `site/`.

Evidence: `xp/src/main/resources/site/site.xml:1`

## Integrations

None found.

Evidence: `xp/src/main/resources/site/site.xml:1`

## Delivery

Built from `xp/`.

Evidence: `xp/src/main/resources/site/site.xml:1`

## Invariants

- Articles keep a title.

Evidence: `com.example.mini:content-type:mini-article`

## Open questions

None.
"""


def valid_capabilities() -> str:
    """The business/capabilities.json that goes with `valid_business`."""
    return """{
  "schema": "extractkit.capabilities/v1",
  "capabilities": [
    {"id": "article-publishing", "title": "Article publishing"},
    {"id": "page-rendering", "title": "Page rendering"},
    {"id": "platform-and-operations", "title": "Platform and operations"}
  ]
}
"""


def valid_capability_spec(title: str = "Article publishing") -> str:
    """A spec-kit capability spec that passes `check` on the fixture sidecar."""
    return f"""# Feature Specification: {title}

## User Scenarios & Testing

### User Story 1 - Editors publish an article (Priority: P1)

An editor saves an article with a title.

**Why this priority**: Every page needs an article.

**Independent Test**: Save an article with a title and read it back.

**Acceptance Scenarios**:

1. **Given** an editor, **When** they save an article without a title, **Then** it is refused.

## Requirements

- **FR-001**: System MUST require a title on every article.
- **FR-002**: System MUST let an article link to other articles.

## Key Entities

- Article: a title and links to related articles.

## Success Criteria

- SC-001: An article without a title is never stored.

## Edge Cases

- An article that links to itself.

## Evidence

- FR-001: `xp/src/main/resources/site/content-types/mini-article/mini-article.xml:5`
- FR-002: `xp/src/main/resources/site/content-types/mini-article/mini-article.xml:13`, `com.example.mini:content-type:mini-article`
"""


def valid_domain_file(title: str = "Article publishing") -> str:
    """A domain/<capability>.md that passes `check` on the fixture sidecar."""
    return f"""# {title}

## State machines

- An article is created, then published when an editor saves it. Evidence: `xp/src/main/resources/site/content-types/mini-article/mini-article.xml:5`

## Formulas

None found in the extracted module facts.

## External calls

- The mini library reads one external API. Evidence: `xp/src/main/resources/lib/mini-http.js:4`

## Emails

None found in the extracted module facts.

## Scheduled and external jobs

- A cron job sweeps bookings every day at 06:00 (`miniCron`). Evidence: `xp/src/main/resources/cron/mini-cron/index.js:11`

## Idempotency and retries

None found in the extracted module facts.
"""


def valid_do_not_port() -> str:
    return """# Do not port

## Security behavior

- **DNP-001** The service answers without checking the caller. Reason: anyone can post. Capability: `platform-and-operations`. Evidence: `xp/src/main/resources/services/mini-script-only/mini-script-only.js:1`

## Defects

None found.

## Dead code

None found.
"""


def write_agent_outputs(out: Path) -> None:
    """The files the required `business` and `constitution` tasks write."""
    (out / "business").mkdir(exist_ok=True)
    (out / "business" / "BUSINESS.md").write_text(valid_business(), encoding="utf-8")
    (out / "business" / "capabilities.json").write_text(valid_capabilities(), encoding="utf-8")
    for capability in ("article-publishing", "page-rendering", "platform-and-operations"):
        (out / "domain").mkdir(exist_ok=True)
        (out / "domain" / f"{capability}.md").write_text(valid_domain_file(), encoding="utf-8")
        (out / "spec-kit" / "specs" / capability).mkdir(parents=True, exist_ok=True)
        (out / "spec-kit" / "specs" / capability / "spec.md").write_text(valid_capability_spec(), encoding="utf-8")
    (out / "reports").mkdir(exist_ok=True)
    (out / "reports" / "do-not-port.md").write_text(valid_do_not_port(), encoding="utf-8")
    (out / "spec-kit" / "constitution").mkdir(parents=True, exist_ok=True)
    (out / "spec-kit" / "constitution" / "project.md").write_text(valid_constitution(), encoding="utf-8")


def valid_business() -> str:
    """A BUSINESS.md that passes `check` on the fixture sidecar."""
    return """# Business flow

## Purpose and audience

The mini site serves articles to visitors.

## Actors

- Visitor: reads pages.
- Editor: writes articles _(inferred)_.

Evidence: `com.example.mini:content-type:mini-article`

## Capabilities

### Article publishing

Editors maintain articles with titles and related links.

Evidence: `com.example.mini:content-type:mini-article`, `content`

### Page rendering

Pages are assembled from parts and layouts.

Evidence: `com.example.mini:part:mini-part`

### Platform and operations

The site runs on Enonic XP with a scheduled sweep job.

Evidence: `com.example.mini:layout:mini-layout`

## Business flow

A visitor opens a page (`presentation`), which renders parts _(inferred)_.

Evidence: `xp/src/main/resources/site/site.xml:1`

## Business rules by capability

No named business rules were extracted.

## Glossary

- Article: the mini-article content type.

## Integrations

None found.

## Open questions

- Which editors publish articles? _(inferred)_

Evidence: `com.example.mini:site:site`
"""
