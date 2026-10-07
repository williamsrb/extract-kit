"""Attachments a pipeline supplies: every file is read, and its content says what it is.

A pipeline keeps its credentials as attachments on one 1Password item (or as
files in a folder). No file name is fixed. Each file is opened by what it
holds: a 7z or zip archive (password-protected or not), a YAML file or a JSON
file. Every document is a resource, `resource.type` plus `resource.data`:

    agent_api_key  data.token and data.agent (the agent CLI it is for): that CLI's credential;
                   data.priority (a whole number, lower first, default 100) orders several
    cms_url        data.url, data.login, data.password: an XP admin login

Nothing here raises for a missing or unreadable file, a missing or wrong
password, or a login that is refused. Each is a line in `Bundle.problems` or
`Outcome.problems`, printed by the caller, and the steps that needed the
resource are skipped. A problem line never holds a secret: it names the file
and what went wrong, not what the file said.
"""

from __future__ import annotations

import atexit
import json
import os
import re
import shutil
import subprocess
import tempfile
from argparse import Namespace
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import cms_target, result, xp_login
from .common import Row

TYPE_AGENT = "agent_api_key"
TYPE_CMS = "cms_url"
DEFAULT_PRIORITY = 100
MAX_BYTES = 1 << 20
RUN_TIMEOUT = 60
SEVEN_ZIP_MAGIC = b"7z\xbc\xaf\x27\x1c"
ZIP_MAGIC = b"PK\x03\x04"
SEVEN_ZIP_BINARIES = ("7z", "7zz", "7za")


@dataclass(frozen=True)
class Resource:
    type: str
    data: dict
    source: str


@dataclass(frozen=True)
class Credential:
    """One usable agent token, in priority order. `token` is a secret: never print it."""

    source: str
    token: str = field(repr=False)


@dataclass
class Bundle:
    resources: list[Resource] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    files: int = 0

    def of_type(self, kind: str) -> list[Resource]:
        return [r for r in self.resources if r.type == kind]


@dataclass
class Outcome:
    """What the resources amounted to. `agent_env` holds a secret: never print it."""

    agent_env: dict[str, str] = field(default_factory=dict)
    credentials: list[Credential] = field(default_factory=list)
    drop_env: list[str] = field(default_factory=list)
    storage_state: Path | None = None
    notes: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def private_dir(prefix: str) -> Path:
    """A mode 0700 folder removed when the process exits."""
    folder = Path(tempfile.mkdtemp(prefix=prefix))
    atexit.register(shutil.rmtree, folder, ignore_errors=True)
    return folder


# --- collecting -------------------------------------------------------------------


def collect(
    *, directory: str | Path | None, op_vault: str | None, op_item: str | None,
    passwords: list[str], workdir: Path, environ: Mapping[str, str],
) -> Bundle:
    """Download the 1Password item's attachments and read the folder; parse all of it."""
    bundle = Bundle()
    if op_vault or op_item:
        if op_vault and op_item:
            _download_item(op_vault, op_item, workdir / "item", environ, bundle)
            _read_folder(workdir / "item", passwords, workdir, bundle)
        else:
            bundle.problems.append("1Password: set both the vault and the item; nothing was downloaded")
    if directory:
        path = Path(directory).expanduser()
        if path.is_dir():
            _read_folder(path, passwords, workdir, bundle)
        elif path.is_file():
            bundle.files += 1
            _read_file(path, path.name, passwords, workdir, bundle, nested=False)
        else:
            bundle.problems.append(f"attachments path {path} does not exist")
    return bundle


def _download_item(vault: str, item: str, dest: Path, environ: Mapping[str, str], bundle: Bundle) -> None:
    op = shutil.which("op")
    if op is None:
        bundle.problems.append("1Password: the op CLI is not installed; the item was not downloaded")
        return
    listed = _run([op, "item", "get", item, "--vault", vault, "--format", "json"], environ)
    if listed.returncode != 0:
        bundle.problems.append(f"1Password: could not read item {item!r} in vault {vault!r}: {_first_line(listed.stderr)}")
        return
    try:
        files = json.loads(listed.stdout).get("files") or []
    except (ValueError, AttributeError):
        bundle.problems.append(f"1Password: item {item!r} did not answer with JSON")
        return
    if not files:
        bundle.problems.append(f"1Password: item {item!r} has no attachments")
        return
    dest.mkdir(parents=True, exist_ok=True)
    for index, entry in enumerate(files):
        name = str(entry.get("name") or "") if isinstance(entry, dict) else ""
        if not name:
            bundle.problems.append(f"1Password: attachment {index + 1} has no name; skipped")
            continue
        target = dest / f"{index:02d}-{re.sub(r'[^\w.-]+', '_', name)}"
        got = _run([op, "read", "--out-file", str(target), f"op://{vault}/{item}/{name}"], environ)
        if got.returncode != 0:
            bundle.problems.append(f"1Password: could not download {name}: {_first_line(got.stderr)}")


def _read_folder(folder: Path, passwords: list[str], workdir: Path, bundle: Bundle) -> None:
    for path in sorted(p for p in folder.rglob("*") if p.is_file() and not p.is_symlink()):
        bundle.files += 1
        _read_file(path, path.relative_to(folder).as_posix(), passwords, workdir, bundle, nested=False)


def _read_file(path: Path, display: str, passwords: list[str], workdir: Path, bundle: Bundle, *, nested: bool) -> None:
    try:
        if path.stat().st_size > MAX_BYTES:
            bundle.problems.append(f"{display}: skipped, larger than {MAX_BYTES} bytes")
            return
        raw = path.read_bytes()
    except OSError as exc:
        bundle.problems.append(f"{display}: could not be read ({exc.strerror or 'I/O error'})")
        return
    if raw.startswith((SEVEN_ZIP_MAGIC, ZIP_MAGIC)):
        if nested:
            bundle.problems.append(f"{display}: skipped, an archive inside an archive")
        else:
            _read_archive(path, display, passwords, workdir, bundle)
        return
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        bundle.problems.append(f"{display}: ignored, not text and not a 7z or zip archive")
        return
    _parse_text(text, display, bundle)


def _read_archive(path: Path, display: str, passwords: list[str], workdir: Path, bundle: Bundle) -> None:
    seven = next((found for name in SEVEN_ZIP_BINARIES if (found := shutil.which(name))), None)
    if seven is None:
        bundle.problems.append(f"{display}: skipped, 7z is not installed")
        return
    for password in (None, *passwords):
        out = Path(tempfile.mkdtemp(prefix="unpack-", dir=workdir))
        # A wrong password can leave half-written files, so only an exit 0 is trusted.
        command = [seven, "x", "-y", "-bd", "-bso0", "-bsp0", f"-o{out}", *([f"-p{password}"] if password is not None else []), "--", str(path)]
        if _run(command, None).returncode == 0:
            members = sorted(p for p in out.rglob("*") if p.is_file() and not p.is_symlink())
            if not members:
                bundle.problems.append(f"{display}: the archive is empty")
            for member in members:
                _read_file(member, f"{display}/{member.relative_to(out).as_posix()}", passwords, workdir, bundle, nested=True)
            return
        shutil.rmtree(out, ignore_errors=True)
    tried = f"none of the {len(passwords)} supplied password(s) opens it" if passwords else "no password was supplied"
    bundle.problems.append(f"{display}: could not be opened; if it is password-protected, {tried}, otherwise it is damaged")


def _parse_text(text: str, display: str, bundle: Bundle) -> None:
    try:
        doc = json.loads(text) if text.lstrip()[:1] in ("{", "[") else yaml.safe_load(text)
    except json.JSONDecodeError as exc:
        bundle.problems.append(f"{display}: not valid JSON (line {exc.lineno})")
        return
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        bundle.problems.append(f"{display}: not valid YAML" + (f" (line {mark.line + 1})" if mark else ""))
        return
    except (ValueError, RecursionError):
        # YAML raises a bare ValueError for a date like 2027-02-30; a deep nest overflows the parser.
        bundle.problems.append(f"{display}: a value in it cannot be read (an impossible date, or nested too deep)")
        return
    res = doc.get("resource") if isinstance(doc, dict) else None
    if not (isinstance(res, dict) and isinstance(res.get("type"), str) and isinstance(res.get("data"), dict)):
        bundle.problems.append(f"{display}: ignored, not a resource (it needs resource.type and resource.data)")
        return
    bundle.resources.append(Resource(res["type"], res["data"], display))


def _run(command: list[str], environ: Mapping[str, str] | None) -> subprocess.CompletedProcess:
    """Run a tool with no terminal, so a missing password fails at once instead of prompting."""
    try:
        return subprocess.run(
            command, capture_output=True, text=True, stdin=subprocess.DEVNULL,
            timeout=RUN_TIMEOUT, env=dict(environ) if environ is not None else None, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(command, 1, "", type(exc).__name__)


def _first_line(text: str) -> str:
    return (text.strip().splitlines() or ["no detail"])[0][:200]


# --- using the resources ----------------------------------------------------------


def resolve(
    bundle: Bundle, *, agent: str, entry: Mapping, xp_host: str | None, want_state: bool, state_dir: Path,
) -> Outcome:
    """Turn the resources into the agent's credential and, if wanted, an XP storage state."""
    outcome = Outcome(problems=list(bundle.problems))
    _agent_credential(bundle, agent, entry, outcome)
    if want_state:
        _storage_state(bundle, xp_host, state_dir, outcome)
    if not want_state and bundle.of_type(TYPE_CMS):
        outcome.notes.append(f"{TYPE_CMS}: not used, a storage state is supplied or no xp host is set")
    for kind in sorted({r.type for r in bundle.resources} - {TYPE_AGENT, TYPE_CMS}):
        outcome.notes.append(f"{kind}: not used by this kit")
    return outcome


def _agent_credential(bundle: Bundle, agent: str, entry: Mapping, outcome: Outcome) -> None:
    var = entry.get("api_key_env")
    mine = []
    for resource in bundle.of_type(TYPE_AGENT):
        target = resource.data.get("agent")
        if not isinstance(target, str) or not target.strip():
            outcome.problems.append(f"{resource.source}: {TYPE_AGENT} needs data.agent, the agent CLI it is for")
        elif target.strip() == agent:
            mine.append(resource)
    usable = []
    for resource in mine:
        token = resource.data.get("token")
        if not (isinstance(token, str) and token.strip()):
            outcome.problems.append(f"{resource.source}: {TYPE_AGENT} has no token")
            continue
        priority = resource.data.get("priority", DEFAULT_PRIORITY)
        if isinstance(priority, bool) or not isinstance(priority, int):
            outcome.problems.append(f"{resource.source}: {TYPE_AGENT} priority must be a whole number; {DEFAULT_PRIORITY} was used")
            priority = DEFAULT_PRIORITY
        usable.append((priority, resource, token.strip()))
    if not usable:
        return
    if not var:
        outcome.problems.append(f"agent {agent} declares no api_key_env in extractkit.yaml; its {TYPE_AGENT} was not used")
        return
    usable.sort(key=lambda item: item[0])  # stable: equal priorities keep file order
    outcome.credentials = [Credential(resource.source, token) for _, resource, token in usable]
    first = outcome.credentials[0]
    outcome.agent_env[str(var)] = first.token
    outcome.drop_env = [str(name) for name in entry.get("conflicting_env") or []]
    outcome.notes.append(f"{TYPE_AGENT} from {first.source} for {agent} ({var})")
    if len(usable) > 1:
        outcome.notes.append(f"{len(usable)} {TYPE_AGENT} resources fit {agent}, in this order: {', '.join(c.source for c in outcome.credentials)}")


def _storage_state(bundle: Bundle, xp_host: str | None, state_dir: Path, outcome: Outcome) -> None:
    if not bundle.of_type(TYPE_CMS):
        outcome.notes.append(f"no {TYPE_CMS} resource, so no XP login")
        return
    wanted = cms_target.hostname_of(xp_host) if xp_host else ""
    for resource in bundle.of_type(TYPE_CMS):
        url, user, password = (resource.data.get(k) for k in ("url", "login", "password"))
        if not all(isinstance(v, str) and v.strip() for v in (url, user, password)):
            outcome.problems.append(f"{resource.source}: {TYPE_CMS} needs url, login and password")
            continue
        host = cms_target.hostname_of(url)
        if wanted and host != wanted:
            outcome.notes.append(f"{TYPE_CMS} from {resource.source} is for {host or 'no host'}, not {wanted}")
            continue
        if cms_target.classify(url) == "production":
            outcome.problems.append(f"{resource.source}: login refused, {host or 'this url'} is not a local or review host")
            continue
        try:
            jar = xp_login.login(url, user, password)
        except xp_login.LoginError as exc:
            outcome.problems.append(f"{resource.source}: login to {host} failed: {exc}")
            continue
        path = state_dir / "storage-state.json"
        try:
            xp_login.write_storage_state(jar, path)
        except OSError as exc:
            outcome.problems.append(f"{resource.source}: logged in to {host} but the storage state could not be written ({exc.strerror or 'I/O error'})")
            return
        outcome.storage_state = path
        outcome.notes.append(f"{TYPE_CMS} from {resource.source}: logged in to {host}")
        return


# --- `extractkit assets` ----------------------------------------------------------


def cmd_assets(args: Namespace) -> int:
    """Read the attachments and say what they hold, without printing a secret. Never fails on a bad file."""
    from . import headless

    name = getattr(args, "agent", None) or headless.DEFAULT_AGENT
    entry = headless.agent_table().get(name, {})
    passwords = password_values(getattr(args, "assets_password_env", None))
    state_out = Path(args.storage_state_out).expanduser() if getattr(args, "storage_state_out", None) else None
    with tempfile.TemporaryDirectory(prefix="extractkit-assets-") as work:
        bundle = collect(
            directory=args.assets_dir, op_vault=args.op_vault, op_item=args.op_item,
            passwords=passwords, workdir=Path(work), environ=os.environ,
        )
        outcome = resolve(
            bundle, agent=name, entry=entry, xp_host=getattr(args, "xp_host", None),
            want_state=state_out is not None, state_dir=private_dir("extractkit-state-") if state_out else Path(work),
        )
    written = None
    if outcome.storage_state and state_out:
        try:
            xp_login.write_private(state_out, outcome.storage_state.read_text(encoding="utf-8"))
            written = state_out
        except OSError as exc:
            outcome.problems.append(f"{state_out}: the storage state could not be written ({exc.strerror or 'I/O error'})")
    print(f"assets: {bundle.files} file(s), {len(bundle.resources)} resource(s)")
    for resource in bundle.resources:
        print(_row(Row(resource.type, "ok", resource.source)))
    for note in outcome.notes:
        print(f"  note     {note}")
    for problem in outcome.problems:
        print(_row(Row("problem", "warn", problem, required=False)))
    result.note_problems(outcome.problems)
    result.note_extra(
        files=bundle.files, resources=[{"type": r.type, "source": r.source} for r in bundle.resources],
        notes=outcome.notes, storage_state=str(written) if written else None,
    )
    return 0


def password_values(names: list[str] | None) -> list[str]:
    """The passphrases held by the named environment variables; an unset one is skipped."""
    return [os.environ[n] for n in names or [] if os.environ.get(n)]


def _row(row: Row) -> str:
    result.note_row(row)
    return f"  {row.state:8s} {row.name:14s} {row.detail}".rstrip()
