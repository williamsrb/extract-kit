"""`extractkit headless` — run the whole extract with no human, for a pipeline.

This is the only module that starts an agent CLI process. Every other command
never calls a model. Headless runs the documented procedure (`docs/llm.md`) as
twelve stages, each one a call to `extractkit` as a subprocess with `--json`, so
it uses the same contract an external agent uses and does not depend on PATH:

    install > assets > preflight > doctor > static > agent:context > cms >
    agent:live_config > synthesis > agent > check > promote (only --promote)

The `assets` stage reads the attachments a pipeline supplies (`assets.py`) and
never fails the run: a missing or unreadable attachment is printed, and the
stages that needed it are skipped.

Preflight builds the graft index directly and asks the agent CLI for Serena
onboarding and the Graphify index. An agent task runs in a fresh agent process
in the source folder, with the rendered prompt behind `headless/preamble.md`;
then its `rerun`, then `check`. After the required tasks the agent stage runs
the optional `spec.enrich`, unless `--no-enrich`. A `check` failure feeds the
problems back to a new process, up to `--max-fix-attempts` times. Where a
prompt says "ask the operator", the agent writes
`<sidecar>/reports/blockers/<task id>.md` instead, and headless stops with
exit 3.

Exit codes: 0 every stage passed, 1 a stage failed, 3 a blocker file exists
(a human is needed). Headless never passes `--allow-production` and never runs
`promote --force`. The analyst gates do not change: no agent ticks a review box.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path

from . import (
    agent_tasks,
    assets,
    context,
    guide,
    install,
    live,
    outtree,
    progress,
    readiness,
    result,
    runner,
)
from .common import REPO_ROOT, load_kit_identity
from .errors import ExtractkitError

STAGES = (
    "install", "assets", "preflight", "doctor", "static", "agent:context", "cms",
    "agent:live_config", "synthesis", "agent", "check", "promote",
)
HEADLESS_DIR = REPO_ROOT / "headless"
DEFAULT_AGENT = "claude"
ENRICH = "spec.enrich"
GRAFT_TIMEOUT = 600
HEARTBEAT = 30
PROGRESS_COMMANDS = ("run", "step", "resume")
CMS_VALUES = (
    ("--branch", "branch"), ("--xp-host", "xp_host"), ("--guillotine", "guillotine"),
    ("--project", "project"), ("--storage-state", "storage_state"),
    ("--configenv", "configenv"), ("--site-url", "site_url"),
)
CMS_LISTS = (("--cms-key", "cms_keys"), ("--round2", "round2"))
# What opens the vault never reaches a child process.
VAULT_TOKEN_PREFIX = "OP_SERVICE_ACCOUNT_TOKEN"
NO_AGENT_CREDENTIAL = "skipped: no agent credential (see the assets stage)"
PROBE_PROMPT = "Reply with the single word: ok"
PROBE_TIMEOUT = 90
RESUMED_NOTE = (
    "\n\n## Resumed\n\nA previous agent run on this task stopped before it finished, because its credential "
    "ran out. The files this task writes may be half-written. Read what is already there and complete it; "
    "do not start over and do not redo what is already correct.\n"
)
# The agent process sees these and what its `agents:` entry names, not the rest of the job environment.
AGENT_ENV_NAMES = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LANGUAGE", "TERM", "COLORTERM", "NO_COLOR", "TMPDIR", "TZ",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "no_proxy", "all_proxy",
    "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
})
AGENT_ENV_PREFIXES = ("LC_", "XDG_", "NODE_", "SSL_", "PLAYWRIGHT_")


class StageFailed(Exception):
    """A stage stopped the run. `exit` is 1, or 3 when a human is needed."""

    exit = 1

    def __init__(self, code: str, message: str, fix: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.fix = fix


class Blocked(StageFailed):
    exit = 3


class AgentExit(StageFailed):
    """The agent CLI ran and exited non-zero. The only failure a credential switch can cure."""


def stage_id(value: str) -> str:
    if value not in STAGES:
        raise argparse.ArgumentTypeError(f"{value!r} is not a stage; use one of: {', '.join(STAGES)}")
    return value


def agent_table() -> dict[str, dict]:
    """The `agents:` block of `extractkit.yaml`. Tests patch this function to add a fake agent."""
    table = load_kit_identity().get("agents") or {}
    return {str(name): dict(entry) for name, entry in table.items() if isinstance(entry, dict)}


def render_prompt(path: Path, **values: str) -> str:
    text = path.read_text(encoding="utf-8")
    unknown = sorted({m for m in agent_tasks.PLACEHOLDER.findall(text) if m not in values})
    if unknown:
        raise ExtractkitError(
            f"{path.name} uses unknown placeholder(s): " + ", ".join("{" + n + "}" for n in unknown),
            "use only the placeholders its renderer supplies",
        )
    return agent_tasks.PLACEHOLDER.sub(lambda m: values[m.group(1)], text)


# --- the JSONL log ---------------------------------------------------------------


class RunLog:
    """`<sidecar>/reports/headless.jsonl` and the agent logs next to it.

    Before the sidecar exists, lines and agent logs wait in a temp folder and
    move into `reports/` when `attach` is called. A run that stops before any
    sidecar exists keeps those logs as `<source>/extract/headless-*.log`.
    """

    def __init__(self, source: Path) -> None:
        self.source = source
        self.out: Path | None = None
        self.lines: list[dict] = []
        self.pending: Path | None = None

    def agent_log(self, stage: str, task: str, attempt: int, credential: int = 0) -> Path:
        name = f"{stage.replace(':', '-')}-{task}-{attempt}" + (f"-c{credential + 1}" if credential else "") + ".log"
        if self.out is None and self.pending is None:
            self.pending = Path(tempfile.mkdtemp(prefix="extractkit-headless-"))
        base = (self.out / "reports" / "headless") if self.out else self.pending
        base.mkdir(parents=True, exist_ok=True)
        return base / name

    def rel(self, path: Path | None) -> str | None:
        return f"reports/headless/{path.name}" if path else None

    def where(self, path: Path) -> str:
        """Where the log ends up once the run closes, for a fix message."""
        if self.out is not None:
            return str(self.out / "reports" / "headless" / path.name)
        return str(self._kept(path.name))

    def _kept(self, name: str) -> Path:
        # Files, not a folder, so they are never taken for a run.
        return self.source / outtree.HEADLESS_DIRNAME / f"headless-{name}"

    def attach(self, out: Path) -> None:
        if self.out == out:
            return
        self.out = out
        target = out / "reports" / "headless"
        target.mkdir(parents=True, exist_ok=True)
        if self.pending is not None:
            for item in sorted(self.pending.iterdir()):
                shutil.move(str(item), str(target / item.name))
        for line in self.lines:
            self._write(line)

    def add(self, **fields: object) -> dict:
        line = {"ts": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **fields}
        self.lines.append(line)
        if self.out:
            self._write(line)
        return line

    def _write(self, line: dict) -> None:
        path = self.out / "reports" / "headless.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")

    def close(self) -> None:
        if self.pending is None:
            return
        logs = sorted(self.pending.iterdir())
        if self.out is None and logs:
            (self.source / outtree.HEADLESS_DIRNAME).mkdir(parents=True, exist_ok=True)
            for item in logs:
                shutil.move(str(item), str(self._kept(item.name)))
        shutil.rmtree(self.pending, ignore_errors=True)


# --- the run ---------------------------------------------------------------------


@dataclass
class StageRecord:
    id: str
    ok: bool
    status: str
    exit: int
    code: str | None
    message: str
    duration_s: float
    log: str | None = None

    def as_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class _Settings:
    agent: str
    entry: dict
    permissions: str
    model: str | None
    effort: str | None
    allowed_tools: list[str]
    preflight_tools: list[str]
    timeout: int
    max_fix: int
    online: bool


class Headless:
    def __init__(self, args: Namespace) -> None:
        self.args = args
        self.source = outtree.resolve_source(args.source)
        if not os.access(self.source, os.W_OK | os.X_OK):
            raise ExtractkitError(
                f"source {self.source} is not writable by uid {os.getuid()}",
                "headless writes <source>/extract/: mount the checkout writable for this user, "
                "or run the container as the checkout's owner (docker run --user)",
                code="source_not_writable",
            )
        outtree.assert_output_root(self.source / outtree.HEADLESS_DIRNAME)
        self.out: Path | None = None
        self.log = RunLog(self.source)
        self.records: list[StageRecord] = []
        self._number = ""
        self.usage: list[dict] = []
        self.agent_env: dict[str, str] = {}
        self.credentials: list[assets.Credential] = []
        self.credential_at = 0
        self.drop_env: list[str] = []
        self.agent_ready = True
        self.s = self._settings()

    # -- settings ---------------------------------------------------------------

    def _settings(self) -> _Settings:
        args = self.args
        table = agent_table()
        name = getattr(args, "agent", None) or DEFAULT_AGENT
        entry = table.get(name)
        if entry is None:
            raise ExtractkitError(
                f"unknown agent {name!r}",
                f"use one of: {', '.join(sorted(table)) or 'none (the agents: block is empty)'}",
                code="unknown_agent",
            )
        permissions = getattr(args, "agent_permissions", None) or "allowlist"
        override = [t for t in (getattr(args, "allowed_tools", None) or []) if t]
        chosen = {}
        for option in ("model", "effort"):
            value = getattr(args, f"agent_{option}", None) or entry.get(f"default_{option}") or None
            if value and not entry.get(f"{option}_args"):
                raise ExtractkitError(
                    f"agent {name} has no {option} argument in extractkit.yaml",
                    f"unset --agent-{option}, EXTRACTKIT_AGENT_{option.upper()}, agent.{option} and default_{option}, "
                    f"or add {option}_args to its agents: entry",
                    code="agent_option_unsupported",
                )
            chosen[option] = value
        return _Settings(
            agent=name, entry=entry, permissions=permissions, model=chosen["model"], effort=chosen["effort"],
            allowed_tools=override or list(entry.get("allowed_tools") or []),
            preflight_tools=override or list(entry.get("preflight_tools") or []),
            timeout=int(getattr(args, "task_timeout", None) or 1800),
            max_fix=2 if getattr(args, "max_fix_attempts", None) is None else int(args.max_fix_attempts),
            online=bool(getattr(args, "storage_state", None)),
        )

    # -- calling extractkit -----------------------------------------------------

    def _env(self, *, agent: bool = False, restrict: bool = False) -> dict[str, str]:
        """No EXTRACTKIT_* reaches a child: headless passes every setting as a flag.

        Neither does what opens the vault or the archives. Only an `agent` child gets the credential.
        An agent process (`restrict`) gets only what `_agent_sees` allows, so a CI job's other secrets stay out.
        """
        passwords = set(getattr(self.args, "assets_password_env", None) or [])
        env = {
            k: v for k, v in os.environ.items()
            if not k.startswith(("EXTRACTKIT_", VAULT_TOKEN_PREFIX)) and k not in passwords
        }
        if restrict:
            env = {k: v for k, v in env.items() if self._agent_sees(k)}
        if agent:
            for name in self.drop_env:
                env.pop(name, None)
            env.update(self.agent_env)
        launcher = install.launcher_path().parent
        env["PATH"] = f"{launcher}{os.pathsep}{env.get('PATH', '')}"
        return env

    def _agent_sees(self, name: str) -> bool:
        entry = self.s.entry
        prefixes = (*AGENT_ENV_PREFIXES, *(entry.get("env_prefixes") or []))
        extra = set(getattr(self.args, "agent_env", None) or [])
        return name in AGENT_ENV_NAMES or name in extra or name == entry.get("api_key_env") or name.startswith(prefixes)

    def _say(self, text: str, *, indent: int = 0) -> None:
        if not getattr(self.args, "quiet", False):
            live.say(text, indent=indent, force=True)

    def _kit(self, *argv: str, allow_fail: bool = False, agent: bool = False) -> dict:
        progress_flag = ["--progress"] if argv[0] in PROGRESS_COMMANDS else []
        command = [sys.executable, str(REPO_ROOT / "extractkit"), *argv, *progress_flag, "--json"]
        child = subprocess.Popen(
            command, cwd=self.source, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=self._env(agent=agent),
        )
        errors: list[str] = []
        pump = threading.Thread(target=self._forward, args=(child.stderr, errors), daemon=True)
        pump.start()
        stdout = child.stdout.read()
        child.wait()
        pump.join()
        child.stdout.close()
        child.stderr.close()
        try:
            doc = json.loads(stdout)
        except ValueError:
            detail = "\n".join(errors) or stdout
            raise StageFailed(
                "kit_failed",
                f"extractkit {argv[0]} exited {child.returncode} without a JSON result: {detail.strip()[:300]}",
            ) from None
        if child.returncode != 0 and not allow_fail:
            error = doc.get("error") or {}
            raise StageFailed(
                error.get("code") or "kit_failed",
                error.get("message") or f"extractkit {argv[0]} exited {child.returncode}",
                error.get("fix"),
            )
        return doc

    def _forward(self, stream, errors: list[str]) -> None:
        """Show a child's progress lines as they come; keep every line for an error message."""
        for raw in stream:
            line = raw.rstrip()
            errors.append(line)
            if line and not getattr(self.args, "quiet", False):
                print(line, file=sys.stderr, flush=True)

    def _common(self, *, exclude: bool = True) -> list[str]:
        flags = ["--source", str(self.source)]
        if getattr(self.args, "profile", None):
            flags += ["--profile", self.args.profile]
        if exclude:
            for item in getattr(self.args, "exclude", None) or []:
                flags += ["--exclude", item]
        return flags

    def _cms(self) -> list[str]:
        """The CMS flags, only on the online route. Headless never adds `--allow-production`."""
        if not self.s.online:
            return []
        flags: list[str] = []
        for option, dest in CMS_VALUES:
            value = getattr(self.args, dest, None)
            if value:
                flags += [option, str(value)]
        for option, dest in CMS_LISTS:
            for item in getattr(self.args, dest, None) or []:
                flags += [option, str(item)]
        return flags

    def _out_flag(self) -> list[str]:
        return ["--out", str(self.out)]

    def _the_profile(self) -> dict:
        """Composed fresh each time: a context task rewrites `context/profile.yaml`."""
        return context.resolve_profile(
            Namespace(profile=getattr(self.args, "profile", None), exclude=None), self.source, self.out,
        )

    def _phase_done(self, *phase_ids: str) -> bool:
        if self.out is None:
            return False
        profile = self._the_profile()
        optional = progress.optional_slots(profile)
        slots = {s for pid in phase_ids if (p := guide.resolve_phase(profile, pid)) for s in p.slots}
        return all(
            progress.step_complete(self.out, plugin)
            for slot, plugin in runner._bound_pipeline(profile) if slot in slots and slot not in optional
        )

    def _attach(self, sidecar: str | None) -> None:
        if sidecar and self.out is None:
            self.out = Path(sidecar)
            self.log.attach(self.out)

    # -- the agent --------------------------------------------------------------

    def _argv(self, tools: list[str]) -> list[str]:
        entry = self.s.entry
        extra = entry.get("bypass_args" if self.s.permissions == "bypass" else "allowlist_args") or []
        values = {
            "allowed_tools": ",".join(tools), "denied_tools": ",".join(entry.get("denied_tools") or []),
            "source": str(self.source), "model": self.s.model or "", "effort": self.s.effort or "",
        }
        model_part = (entry.get("model_args") or []) if self.s.model else []
        effort_part = (entry.get("effort_args") or []) if self.s.effort else []
        argv = [*(entry.get("argv") or []), *model_part, *effort_part, *extra]
        return [self._fill(token, values) for token in argv]

    @staticmethod
    def _fill(token: str, values: dict[str, str]) -> str:
        for key, value in values.items():
            token = token.replace("{" + key + "}", value)
        return token

    def _agent(self, stage: str, task: str, attempt: int, prompt: str, tools: list[str]) -> Path:
        """Run the agent once. When its credential has run out, go on with the next one on the same task."""
        resumed = False
        while True:
            try:
                return self._agent_once(stage, task, attempt, prompt + (RESUMED_NOTE if resumed else ""), tools)
            except AgentExit:
                if not self._switch_credential(stage, task, attempt):
                    raise
                resumed = True

    def _agent_once(self, stage: str, task: str, attempt: int, prompt: str, tools: list[str]) -> Path:
        log = self.log.agent_log(stage, task, attempt, self.credential_at)
        argv = self._argv(tools)
        start = time.monotonic()
        self._say(f"agent {argv[0]} started on {task} (attempt {attempt}, timeout {live.duration(self.s.timeout)}, model {self.s.model or "default"}, effort {self.s.effort or "default"}), log {self.log.where(log)}", indent=1)
        try:
            with log.open("w", encoding="utf-8") as handle:
                child = subprocess.Popen(
                    argv, stdin=subprocess.PIPE, cwd=self.source, env=self._env(agent=True, restrict=True), text=True,
                    stdout=handle, stderr=subprocess.STDOUT,
                )
                self._wait(child, prompt, log, task, start)
        except subprocess.TimeoutExpired:
            self._line(stage, task, attempt, False, 1, "agent_timeout", f"{argv[0]} ran over {self.s.timeout}s", start, log, agent=True)
            raise StageFailed(
                "agent_timeout", f"{argv[0]} ran over {self.s.timeout}s on {task}",
                "raise --task-timeout, or split the task",
            ) from None
        except OSError as exc:
            self._line(stage, task, attempt, False, 1, "agent_failed", str(exc), start, log, agent=True)
            raise StageFailed("agent_failed", f"could not start {argv[0]}: {exc}", f"install {argv[0]}") from None
        if child.returncode != 0:
            self._line(stage, task, attempt, False, child.returncode, "agent_failed", f"{argv[0]} exited {child.returncode}", start, log, agent=True)
            raise AgentExit(
                "agent_failed", f"{argv[0]} exited {child.returncode} on {task}; see {self.log.where(log)}",
                "check the agent CLI login or API key in this environment",
            )
        usage = agent_usage(log.read_text(encoding="utf-8", errors="replace"), self.s.entry.get("usage"))
        self.usage.append(usage)
        self._say(f"agent finished {task} in {live.duration(time.monotonic() - start)}{_spent(usage)}", indent=1)
        self._line(stage, task, attempt, True, 0, None, "agent finished", start, log, usage, agent=True)
        return log

    # -- credentials ------------------------------------------------------------

    def _use_credential(self, index: int) -> None:
        self.credential_at = index
        self.agent_env = {str(self.s.entry["api_key_env"]): self.credentials[index].token}

    def _probe(self, credential: assets.Credential) -> bool:
        """Ask the agent a one-word question with this credential. Any failure to answer means it is unusable."""
        env = self._env(agent=True, restrict=True)
        env[str(self.s.entry["api_key_env"])] = credential.token
        try:
            done = subprocess.run(
                self._argv(self.s.allowed_tools), input=PROBE_PROMPT, cwd=self.source, env=env, text=True,
                capture_output=True, timeout=PROBE_TIMEOUT, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return done.returncode == 0 and not _reported_error(done.stdout)

    def _pick_credential(self, start: int) -> bool:
        """Use the first credential from `start` on that answers a probe. Several are tried in priority order."""
        for index in range(start, len(self.credentials)):
            credential = self.credentials[index]
            self._say(f"probing credential {index + 1}/{len(self.credentials)} ({credential.source}) ...", indent=1)
            if self._probe(credential):
                self._use_credential(index)
                return True
            self._say(f"credential {index + 1} ({credential.source}) did not answer", indent=1)
        return False

    def _switch_credential(self, stage: str, task: str, attempt: int) -> bool:
        """After an agent exit: when the credential no longer answers, move to the next that does.

        False when there is nothing to switch to, or when the credential still answers (the exit was not about it).
        """
        if len(self.credentials) < 2 or self._probe(self.credentials[self.credential_at]):
            return False
        start = time.monotonic()
        gone = self.credentials[self.credential_at].source
        if not self._pick_credential(self.credential_at + 1):
            self._line(stage, task, attempt, False, 1, "credentials_exhausted", f"credential {gone} and the ones after it did not answer", start)
            raise StageFailed(
                "credentials_exhausted", f"no agent credential answers any more (last in use: {gone})",
                "run headless again later, or with more credentials; the finished tasks are kept and are not run again",
            )
        now = self.credentials[self.credential_at].source
        self._say(f"credential {gone} did not answer; going on with {now} ({task}, attempt {attempt})", indent=1)
        self._line(stage, task, attempt, True, 0, "credential_switched", f"{gone} -> {now}", start)
        return True

    def _wait(self, child: subprocess.Popen, prompt: str, log: Path, task: str, start: float) -> None:
        """Feed the prompt, then wait for the agent, saying every HEARTBEAT seconds that it is alive."""
        pending: str | None = prompt
        while True:
            left = self.s.timeout - (time.monotonic() - start)
            try:
                child.communicate(input=pending, timeout=max(0.1, min(HEARTBEAT, left)))
                return
            except subprocess.TimeoutExpired:
                pending = None
                if time.monotonic() - start >= self.s.timeout:
                    child.kill()
                    child.communicate()
                    raise
                self._say(f"agent still working on {task}: {live.duration(time.monotonic() - start)} elapsed, {_tail(log)}", indent=1)

    def _line(self, stage: str, task: str | None, attempt: int | None, ok: bool, code_exit: int,
              code: str | None, message: str, start: float, log: Path | None = None,
              usage: dict | None = None, agent: bool = False) -> None:
        self.log.add(
            stage=stage, task=task, attempt=attempt, ok=ok, exit=code_exit, code=code,
            message=message, duration_s=round(time.monotonic() - start, 3), log=self.log.rel(log),
            **({"model": self.s.model or "default", "effort": self.s.effort or "default"} if agent else {}),
            **(usage or {}),
        )

    # -- stages -----------------------------------------------------------------

    def run(self) -> int:
        until = getattr(self.args, "until", None)
        stages = {
            "install": self._install, "assets": self._assets, "preflight": self._preflight, "doctor": self._doctor,
            "static": self._static, "cms": self._cms_stage, "synthesis": self._synthesis,
            "agent:context": lambda: self._loop("agent:context", only_context=True),
            "agent:live_config": lambda: self._loop("agent:live_config", only_context=True),
            "agent": self._agent_stage,
            "check": self._check, "promote": self._promote,
        }
        exit_code, failure = 0, None
        planned = STAGES[: STAGES.index(until) + 1] if until else STAGES
        self._say(f"headless: {len(planned)} stage(s) on {self.source} with agent {self.s.agent}")
        try:
            for number, stage in enumerate(planned, 1):
                self._number = f"[{number}/{len(planned)}]"
                self._stage(stage, stages[stage])
        except StageFailed as exc:
            exit_code, failure = exc.exit, exc
        finally:
            self.log.close()
        self._report(exit_code, failure)
        return exit_code

    def _stage(self, stage: str, fn) -> None:
        start = time.monotonic()
        self._say(f"{self._number} {stage} ...")
        try:
            message = fn()
        except StageFailed as exc:
            self._finish(stage, False, "blocked" if exc.exit == 3 else "failed", exc.exit, exc.code, str(exc), start)
            raise
        self._finish(stage, True, "skipped" if message.startswith("skipped") else "ok", 0, None, message, start)

    def _finish(self, stage: str, ok: bool, status: str, code_exit: int, code: str | None, message: str, start: float) -> None:
        duration = round(time.monotonic() - start, 3)
        self.records.append(StageRecord(stage, ok, status, code_exit, code, message, duration))
        self._say(f"{self._number} {stage} {status} in {live.duration(duration)}: {message}")
        self._line(stage, None, None, ok, code_exit, code, message, start)

    def _install(self) -> str:
        self._kit("install")
        return "ok"

    def _assets(self) -> str:
        """Read the attachments. Never fails: what is missing is printed and its stages are skipped."""
        args = self.args
        directory, vault, item = (getattr(args, name, None) for name in ("assets_dir", "op_vault", "op_item"))
        if not (directory or vault or item):
            return "skipped: no attachments source (--assets-dir, or --op-vault and --op-item)"
        xp_host = getattr(args, "xp_host", None)
        try:
            with tempfile.TemporaryDirectory(prefix="extractkit-assets-") as work:
                bundle = assets.collect(
                    directory=directory, op_vault=vault, op_item=item,
                    passwords=assets.password_values(getattr(args, "assets_password_env", None)),
                    workdir=Path(work), environ=os.environ,
                )
                outcome = assets.resolve(
                    bundle, agent=self.s.agent, entry=self.s.entry, xp_host=xp_host,
                    want_state=not self.s.online and bool(xp_host), state_dir=assets.private_dir("extractkit-state-"),
                )
        except Exception as exc:  # noqa: BLE001 - the stage must not stop the run, whatever a file or a tool did
            bundle, outcome = assets.Bundle(), assets.Outcome(problems=[f"attachments could not be processed ({type(exc).__name__})"])
        self.agent_env, self.drop_env = outcome.agent_env, outcome.drop_env
        self.credentials = outcome.credentials
        if len(self.credentials) > 1 and not self._pick_credential(0):
            outcome.problems.append(f"none of the {len(self.credentials)} {assets.TYPE_AGENT} credentials for agent {self.s.agent} answered")
            self.agent_env, self.credentials = {}, []
        elif len(self.credentials) > 1 and self.credential_at:
            outcome.notes.append(f"credential {self.credential_at + 1} of {len(self.credentials)} is in use; the ones before it did not answer")
        if outcome.storage_state:
            args.storage_state = str(outcome.storage_state)
            self.s.online = True
        var = self.s.entry.get("api_key_env")
        if var and var not in self.agent_env and not os.environ.get(var):
            self.agent_ready = False
            outcome.problems.append(
                f"no credential for agent {self.s.agent}: no usable {assets.TYPE_AGENT} and {var} is not set, "
                "so the agent stages are skipped"
            )
        for problem in outcome.problems:
            live.say(f"attachments: {problem}", indent=1, force=True)
        found = f"{len(bundle.resources)} resource(s) in {bundle.files} file(s)"
        used = "; ".join(outcome.notes)
        shown = "; ".join(outcome.problems[:3]) + (f"; and {len(outcome.problems) - 3} more" if len(outcome.problems) > 3 else "")
        return f"ok: {found}" + (f"; {used}" if used else "") + (f"; {len(outcome.problems)} problem(s): {shown}" if outcome.problems else "")

    def _preflight(self) -> str:
        notes: list[str] = []
        if not (self.source / "graft").is_dir() and shutil.which("graft"):
            self._say("building the graft index (optional) ...", indent=1)
            try:
                built = subprocess.run(
                    ["graft", "build"], cwd=self.source, capture_output=True, text=True, check=False,
                    timeout=GRAFT_TIMEOUT, env=self._env(),
                ).returncode == 0
            except subprocess.TimeoutExpired:
                built = False
            notes.append("graft index built" if built else "graft build failed (optional, continuing)")
        missing = [r for r in readiness.check_source(self.source) if r.failed]
        if not missing:
            return "ok (already done)" if not notes else "ok: " + ", ".join(notes)
        if not self.agent_ready:
            return f"{NO_AGENT_CREDENTIAL}; Serena onboarding and the Graphify index stay unprepared"
        prompt = render_prompt(HEADLESS_DIR / "preflight.md", source=str(self.source))
        log = self._agent("preflight", "preflight", 1, prompt, self.s.preflight_tools)
        still = [r for r in readiness.check_source(self.source) if r.failed]
        if still:
            raise StageFailed(
                "readiness_missing", f"{still[0].name}: {still[0].detail}",
                f"{still[0].fix}; the agent's account of the attempt is in {self.log.where(log)}",
            )
        return "ok: " + ", ".join([*notes, "Serena onboarding and Graphify index created by the agent"])

    def _doctor(self) -> str:
        flags = self._common(exclude=False)
        resources = getattr(self.args, "resources", None)
        if resources:
            flags += ["--resources", str(resources)]
        if self.s.online:
            flags += ["--storage-state", str(self.args.storage_state)]
        self._kit("doctor", *flags, agent=True)
        return "ok"

    def _static(self) -> str:
        latest = outtree.latest_run(self.source, outtree.HEADLESS_DIRNAME)
        if latest is not None:
            self.out = latest
            self.log.attach(latest)
            if self._phase_done("static"):
                return "ok (already done)"
        out = self.out or outtree.default_out(self.source, dirname=outtree.HEADLESS_DIRNAME)
        doc = self._kit("run", *self._common(), "--until", "static", "--out", str(out))
        self._attach(doc.get("sidecar"))
        return "ok"

    def _cms_stage(self) -> str:
        if not self.s.online:
            return "skipped: no storage state, offline route"
        if self._phase_done("cms"):
            return "ok (already done)"
        self._kit("resume", *self._common(), *self._out_flag(), "--until", "cms", *self._cms())
        return "ok"

    def _synthesis(self) -> str:
        if self._phase_done("merge", "synthesis"):
            return "ok (already done)"
        self._kit("run", *self._common(), *self._out_flag(), "--from", "merge", "--until", "synthesis", *self._cms())
        return "ok"

    def _check(self) -> str:
        doc = self._kit("check", *self._out_flag(), allow_fail=True)
        if doc.get("exit") != 0:
            problems = doc.get("problems") or []
            raise StageFailed("check_failed", f"{len(problems)} problem(s): " + "; ".join(problems[:3]),
                              "fix the listed problems, then re-run headless")
        return "ok"

    def _promote(self) -> str:
        if not getattr(self.args, "promote", False):
            return "skipped: pass --promote to copy the specs into the checkout"
        self._kit("promote", "--source", str(self.source), *self._out_flag())
        return "ok"

    # -- the agent loop ---------------------------------------------------------

    def _loop(self, stage: str, *, only_context: bool) -> str:
        if not self.agent_ready:
            return NO_AGENT_CREDENTIAL
        ran: list[str] = []
        while True:
            doc = self._kit("agent", "next", *self._out_flag())
            task = doc.get("next")
            if task is None:
                blocked = doc.get("blocked") or []
                if blocked and not only_context:
                    raise StageFailed(
                        "task_inputs_missing",
                        "; ".join(f"{b['id']} waits on {', '.join(b['missing_reads'])}" for b in blocked),
                        "run the pipeline phases that write those files",
                    )
                break
            if only_context and not str(task["id"]).startswith("context."):
                break
            if task["id"] in ran:
                raise StageFailed("agent_failed", f"{task['id']} is still pending after its agent run")
            self._say(f"next agent task: {task['id']}", indent=1)
            self._run_task(stage, task["id"])
            ran.append(task["id"])
        return f"ok: ran {', '.join(ran)}" if ran else "ok (already done)"

    def _agent_stage(self) -> str:
        """The required tasks, then `spec.enrich` unless `--no-enrich`. A failed enrich does not stop the run."""
        if not self.agent_ready:
            return NO_AGENT_CREDENTIAL
        message = self._loop("agent", only_context=False)
        if getattr(self.args, "no_enrich", False):
            return message
        if self._kit("agent", "show", ENRICH, *self._out_flag()).get("state") == "done":
            return message
        self._say(f"optional agent task: {ENRICH}", indent=1)
        try:
            self._run_task("agent", ENRICH)
        except StageFailed as exc:
            self._say(f"{ENRICH} failed, going on to check: {exc}", indent=1)
            return f"{message}; {ENRICH} failed and was skipped: {exc}"
        return f"{message}, {ENRICH}" if message.startswith("ok: ran") else f"ok: ran {ENRICH}"

    def _blocker(self, task_id: str) -> Path:
        return self.out / "reports" / "blockers" / f"{task_id}.md"

    def _run_task(self, stage: str, task_id: str) -> None:
        self._blocker(task_id).unlink(missing_ok=True)
        shown = self._kit("agent", "show", task_id, *self._out_flag())
        preamble = render_prompt(HEADLESS_DIR / "preamble.md", source=str(self.source), sidecar=str(self.out))
        problems: list[str] = []
        attempts = self.s.max_fix + 1
        for attempt in range(1, attempts + 1):
            self._say(f"task {task_id}: attempt {attempt}/{attempts}" + (f", fixing {len(problems)} check problem(s)" if problems else ""), indent=1)
            prompt = f"{preamble}\n\n{shown['prompt']}"
            if problems:
                prompt += (
                    "\n\n## `extractkit check` failed after your last attempt\n\n"
                    + "\n".join(f"- {p}" for p in problems)
                    + "\n\nFix these in the files this task writes, then stop.\n"
                )
            self._agent(stage, task_id, attempt, prompt, self.s.allowed_tools)
            blocker = self._blocker(task_id)
            if blocker.is_file():
                raise Blocked("task_blocked", f"{task_id} wrote a blocker: reports/blockers/{task_id}.md", f"read {blocker}")
            self._say(f"task {task_id}: re-running {' '.join(shown.get('rerun') or []) or 'nothing'}, then check", indent=1)
            self._rerun(shown.get("rerun") or [])
            check = self._kit("check", *self._out_flag(), allow_fail=True)
            problems = list(check.get("problems") or [])
            self._say(f"task {task_id}: check " + ("passed" if check.get("exit") == 0 else f"found {len(problems)} problem(s): {'; '.join(problems[:2])[:200]}"), indent=1)
            if check.get("exit") == 0 and self._kit("agent", "show", task_id, *self._out_flag()).get("state") == "done":
                return
            if check.get("exit") == 0:
                problems = [f"{task_id} is not done: the file it writes is missing or not valid"]
        self._write_blocker(task_id, problems)
        raise Blocked(
            "task_blocked",
            f"{task_id} still fails check after {self.s.max_fix} fix attempt(s); blocker at reports/blockers/{task_id}.md",
            f"read {self._blocker(task_id)}",
        )

    def _write_blocker(self, task_id: str, problems: list[str]) -> None:
        path = self._blocker(task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        evidence = "; ".join(problems) or "no detail"
        path.write_text(
            f"Reason: extractkit check still fails after {self.s.max_fix} fix attempt(s) (written by headless)\n"
            f"Evidence: {evidence}\n", encoding="utf-8",
        )

    def _rerun(self, tokens: list[str]) -> None:
        if not tokens:
            return
        for piece in self._split_rerun(list(tokens)):
            command, rest = piece[0], piece[1:]
            flags = [*self._common(), *self._out_flag(), *self._cms()]
            self._kit(command, *rest, *flags)

    def _split_rerun(self, tokens: list[str]) -> list[list[str]]:
        """On the offline route a `run` range that holds the CMS phase runs as two slices."""
        if tokens[0] != "run" or self.s.online:
            return [tokens]
        profile = self._the_profile()
        order = [p.id for p in guide.phases(profile)]
        cms = guide.phase_of(profile, guide.CMS_SLOT)
        first, last = _flag(tokens, "--from"), _flag(tokens, "--until")
        start = guide.resolve_phase(profile, first) if first else None
        end = guide.resolve_phase(profile, last) if last else None
        if cms is None or start is None or end is None:
            return [tokens]
        lo, hi, mid = order.index(start.id), order.index(end.id), order.index(cms.id)
        if not lo <= mid <= hi:
            return [tokens]
        pieces: list[list[str]] = []
        if lo < mid:
            pieces.append(["run", "--from", start.id, "--until", order[mid - 1]])
        if mid < hi:
            pieces.append(["run", "--from", order[mid + 1], "--until", end.id])
        return pieces

    def _summary(self) -> dict:
        usage: dict = {}
        if any("tokens" in u for u in self.usage):
            usage["tokens"] = sum(u.get("tokens", 0) for u in self.usage)
        if any("cost_usd" in u for u in self.usage):
            usage["cost_usd"] = round(sum(u.get("cost_usd", 0) for u in self.usage), 4)
        return {
            "duration_s": round(sum(r.duration_s for r in self.records), 3),
            "agent_runs": len(self.usage), "usage": usage,
            "agent": {"name": self.s.agent, "model": self.s.model or "default", "effort": self.s.effort or "default"},
        }

    # -- result -----------------------------------------------------------------

    def _report(self, exit_code: int, failure: StageFailed | None) -> None:
        result.note_run(sidecar=self.out, source=self.source)
        result.note_extra(stages=[r.as_dict() for r in self.records])
        summary = self._summary()
        result.note_extra(summary=summary)
        self._say("summary:")
        for record in self.records:
            row = f"{record.status:8s} {record.id:18s} {live.duration(record.duration_s):>7s}  {record.message}"
            print(f"  {row}")
            self._say(row, indent=1)
        agent = summary["agent"]
        total = (f"total {live.duration(summary['duration_s'])}, {summary['agent_runs']} agent run(s) "
                 f"({agent['name']}, model {agent['model']}, effort {agent['effort']})")
        if summary["agent_runs"]:
            total += _spent(summary["usage"]) if summary["usage"] else " (the agent reported no token or cost data)"
        print(f"  {total}")
        self._say(total, indent=1)
        if failure is not None:
            result.note_error(failure.code, str(failure), failure.fix)
            print(f"\nheadless: stopped (exit {exit_code}): {failure}")
            return
        print(f"\nheadless: {len(self.records)} stage(s) passed ({self.out})")
        if self.out is not None and not getattr(self.args, "promote", False):
            prog = getattr(self.args, "prog_display", None) or "extractkit"
            result.note_next(guide.Suggestion(
                "Review the extract, then promote it into the checkout:",
                [prog, "promote", "--source", str(self.source), "--out", str(self.out)],
            ))


def _path(doc: object, dotted: str) -> object:
    for key in dotted.split("."):
        doc = doc.get(key) if isinstance(doc, dict) else None
    return doc


def _reported_error(text: str) -> bool:
    """An agent CLI that prints a JSON result can report a failure (a spent quota) and still exit 0."""
    try:
        doc = json.loads(text)
    except ValueError:
        return False
    return isinstance(doc, dict) and doc.get("is_error") is True


def agent_usage(text: str, spec: dict | None) -> dict:
    """Tokens and cost read from an agent's log with the entry's `usage:` block, or {}.

    `tokens`: JSON paths whose numbers are summed; `cost_usd`: one JSON path; both are read from
    the last JSON line that has any of them. `tokens_regex`: a pattern with one number group,
    for an agent that prints plain text. An agent with no `usage:` block reports nothing.
    """
    spec = spec or {}
    found: dict = {}
    if spec.get("tokens") or spec.get("cost_usd"):
        for line in reversed([l for l in text.splitlines() if l.strip()][-40:]):
            try:
                doc = json.loads(line)
            except ValueError:
                continue
            tokens = [_path(doc, p) for p in spec.get("tokens") or []]
            cost = _path(doc, spec["cost_usd"]) if spec.get("cost_usd") else None
            if all(t is None for t in tokens) and cost is None:
                continue
            if any(t is not None for t in tokens):
                found["tokens"] = sum(int(t or 0) for t in tokens)
            if cost is not None:
                found["cost_usd"] = round(float(cost), 4)
            return found
    if spec.get("tokens_regex"):
        match = re.search(spec["tokens_regex"], text, re.IGNORECASE)
        if match:
            found["tokens"] = int(match.group(1).replace(",", ""))
    return found


def _spent(usage: dict) -> str:
    parts = []
    if usage.get("tokens"):
        parts.append(f"{usage['tokens']:,} tokens")
    if usage.get("cost_usd") is not None:
        parts.append(f"${usage['cost_usd']:.2f}")
    return f" ({', '.join(parts)})" if parts else ""


def _tail(log: Path) -> str:
    """Log size and its last line, for a heartbeat."""
    try:
        size = log.stat().st_size
        with log.open("rb") as handle:
            handle.seek(max(0, size - 4096))
            lines = [l for l in handle.read().decode("utf-8", "replace").splitlines() if l.strip()]
    except OSError:
        return "no log yet"
    last = lines[-1].strip()[:100] if lines else ""
    return f"log {size} B" + (f", last: {last}" if last else ", no output yet")


def _flag(tokens: list[str], name: str) -> str | None:
    for index, token in enumerate(tokens[:-1]):
        if token == name:
            return tokens[index + 1]
    return None


def cmd_headless(args: Namespace) -> int:
    return Headless(args).run()
