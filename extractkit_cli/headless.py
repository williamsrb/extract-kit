"""`extractkit headless` — run the whole extract with no human, for a pipeline.

This is the only module that starts an agent CLI process. Every other command
never calls a model. Headless runs the documented procedure (`docs/llm.md`) as
eleven stages, each one a call to `extractkit` as a subprocess with `--json`, so
it uses the same contract an external agent uses and does not depend on PATH:

    install > preflight > doctor > static > agent:context > cms >
    agent:live_config > synthesis > agent > check > promote (only --promote)

Preflight builds the graft index directly and asks the agent CLI for Serena
onboarding and the Graphify index. An agent task runs in a fresh agent process
in the source folder, with the rendered prompt behind `headless/preamble.md`;
then its `rerun`, then `check`. A `check` failure feeds the problems back to a
new process, up to `--max-fix-attempts` times. Where a prompt says "ask the
operator", the agent writes `<sidecar>/reports/blockers/<task id>.md` instead,
and headless stops with exit 3.

Exit codes: 0 every stage passed, 1 a stage failed, 3 a blocker file exists
(a human is needed). Headless never passes `--allow-production` and never runs
`promote --force`. The analyst gates do not change: no agent ticks a review box.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path

from . import (
    agent_tasks,
    context,
    guide,
    install,
    outtree,
    progress,
    readiness,
    result,
    runner,
)
from .common import REPO_ROOT, load_kit_identity
from .errors import ExtractkitError

STAGES = (
    "install", "preflight", "doctor", "static", "agent:context", "cms",
    "agent:live_config", "synthesis", "agent", "check", "promote",
)
HEADLESS_DIR = REPO_ROOT / "headless"
DEFAULT_AGENT = "claude"
GRAFT_TIMEOUT = 600
CMS_VALUES = (
    ("--branch", "branch"), ("--xp-host", "xp_host"), ("--guillotine", "guillotine"),
    ("--project", "project"), ("--storage-state", "storage_state"),
    ("--configenv", "configenv"), ("--site-url", "site_url"),
)
CMS_LISTS = (("--cms-key", "cms_keys"), ("--round2", "round2"))


class StageFailed(Exception):
    """A stage stopped the run. `exit` is 1, or 3 when a human is needed."""

    exit = 1

    def __init__(self, code: str, message: str, fix: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.fix = fix


class Blocked(StageFailed):
    exit = 3


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
    move into `reports/` when `attach` is called.
    """

    def __init__(self) -> None:
        self.out: Path | None = None
        self.lines: list[dict] = []
        self.pending: Path | None = None

    def agent_log(self, stage: str, task: str, attempt: int) -> Path:
        name = f"{stage.replace(':', '-')}-{task}-{attempt}.log"
        if self.out is None and self.pending is None:
            self.pending = Path(tempfile.mkdtemp(prefix="extractkit-headless-"))
        base = (self.out / "reports" / "headless") if self.out else self.pending
        base.mkdir(parents=True, exist_ok=True)
        return base / name

    def rel(self, path: Path | None) -> str | None:
        return f"reports/headless/{path.name}" if path else None

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
        if self.pending is not None:
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
    allowed_tools: list[str]
    preflight_tools: list[str]
    timeout: int
    max_fix: int
    online: bool


class Headless:
    def __init__(self, args: Namespace) -> None:
        self.args = args
        self.source = outtree.resolve_source(args.source)
        self.out: Path | None = None
        self.log = RunLog()
        self.records: list[StageRecord] = []
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
        return _Settings(
            agent=name, entry=entry, permissions=permissions,
            allowed_tools=override or list(entry.get("allowed_tools") or []),
            preflight_tools=override or list(entry.get("preflight_tools") or []),
            timeout=int(getattr(args, "task_timeout", None) or 1800),
            max_fix=2 if getattr(args, "max_fix_attempts", None) is None else int(args.max_fix_attempts),
            online=bool(getattr(args, "storage_state", None)),
        )

    # -- calling extractkit -----------------------------------------------------

    def _env(self) -> dict[str, str]:
        """No EXTRACTKIT_* reaches a child: headless passes every setting as a flag."""
        env = {k: v for k, v in os.environ.items() if not k.startswith("EXTRACTKIT_")}
        launcher = install.launcher_path().parent
        env["PATH"] = f"{launcher}{os.pathsep}{env.get('PATH', '')}"
        return env

    def _kit(self, *argv: str, allow_fail: bool = False) -> dict:
        command = [sys.executable, str(REPO_ROOT / "extractkit"), *argv, "--json"]
        done = subprocess.run(
            command, cwd=self.source, capture_output=True, text=True, check=False, env=self._env(),
        )
        try:
            doc = json.loads(done.stdout)
        except ValueError:
            raise StageFailed(
                "kit_failed",
                f"extractkit {argv[0]} exited {done.returncode} without a JSON result: "
                f"{(done.stderr or done.stdout).strip()[:300]}",
            ) from None
        if done.returncode != 0 and not allow_fail:
            error = doc.get("error") or {}
            raise StageFailed(
                error.get("code") or "kit_failed",
                error.get("message") or f"extractkit {argv[0]} exited {done.returncode}",
                error.get("fix"),
            )
        return doc

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
        values = {"allowed_tools": ",".join(tools), "source": str(self.source)}
        argv = [*(entry.get("argv") or []), *extra]
        return [self._fill(token, values) for token in argv]

    @staticmethod
    def _fill(token: str, values: dict[str, str]) -> str:
        for key, value in values.items():
            token = token.replace("{" + key + "}", value)
        return token

    def _agent(self, stage: str, task: str, attempt: int, prompt: str, tools: list[str]) -> Path:
        log = self.log.agent_log(stage, task, attempt)
        argv = self._argv(tools)
        start = time.monotonic()
        try:
            with log.open("w", encoding="utf-8") as handle:
                done = subprocess.run(
                    argv, input=prompt, cwd=self.source, env=self._env(), text=True,
                    stdout=handle, stderr=subprocess.STDOUT, timeout=self.s.timeout, check=False,
                )
        except subprocess.TimeoutExpired:
            self._line(stage, task, attempt, False, 1, "agent_timeout", f"{argv[0]} ran over {self.s.timeout}s", start, log)
            raise StageFailed(
                "agent_timeout", f"{argv[0]} ran over {self.s.timeout}s on {task}",
                "raise --task-timeout, or split the task",
            ) from None
        except OSError as exc:
            self._line(stage, task, attempt, False, 1, "agent_failed", str(exc), start, log)
            raise StageFailed("agent_failed", f"could not start {argv[0]}: {exc}", f"install {argv[0]}") from None
        if done.returncode != 0:
            self._line(stage, task, attempt, False, done.returncode, "agent_failed", f"{argv[0]} exited {done.returncode}", start, log)
            raise StageFailed(
                "agent_failed", f"{argv[0]} exited {done.returncode} on {task}; see {self.log.rel(log)}",
                "check the agent CLI login or API key in this environment",
            )
        self._line(stage, task, attempt, True, 0, None, "agent finished", start, log)
        return log

    def _line(self, stage: str, task: str | None, attempt: int | None, ok: bool, code_exit: int,
              code: str | None, message: str, start: float, log: Path | None = None) -> None:
        self.log.add(
            stage=stage, task=task, attempt=attempt, ok=ok, exit=code_exit, code=code,
            message=message, duration_s=round(time.monotonic() - start, 3), log=self.log.rel(log),
        )

    # -- stages -----------------------------------------------------------------

    def run(self) -> int:
        until = getattr(self.args, "until", None)
        stages = {
            "install": self._install, "preflight": self._preflight, "doctor": self._doctor,
            "static": self._static, "cms": self._cms_stage, "synthesis": self._synthesis,
            "agent:context": lambda: self._loop("agent:context", only_context=True),
            "agent:live_config": lambda: self._loop("agent:live_config", only_context=True),
            "agent": lambda: self._loop("agent", only_context=False),
            "check": self._check, "promote": self._promote,
        }
        exit_code, failure = 0, None
        try:
            for stage in STAGES:
                self._stage(stage, stages[stage])
                if until == stage:
                    break
        except StageFailed as exc:
            exit_code, failure = exc.exit, exc
        finally:
            self.log.close()
        self._report(exit_code, failure)
        return exit_code

    def _stage(self, stage: str, fn) -> None:
        start = time.monotonic()
        try:
            message = fn()
        except StageFailed as exc:
            self._finish(stage, False, "blocked" if exc.exit == 3 else "failed", exc.exit, exc.code, str(exc), start)
            raise
        self._finish(stage, True, "skipped" if message.startswith("skipped") else "ok", 0, None, message, start)

    def _finish(self, stage: str, ok: bool, status: str, code_exit: int, code: str | None, message: str, start: float) -> None:
        duration = round(time.monotonic() - start, 3)
        self.records.append(StageRecord(stage, ok, status, code_exit, code, message, duration))
        self._line(stage, None, None, ok, code_exit, code, message, start)

    def _install(self) -> str:
        self._kit("install")
        return "ok"

    def _preflight(self) -> str:
        notes: list[str] = []
        if not (self.source / "graft").is_dir() and shutil.which("graft"):
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
        prompt = render_prompt(HEADLESS_DIR / "preflight.md", source=str(self.source))
        self._agent("preflight", "preflight", 1, prompt, self.s.preflight_tools)
        still = [r for r in readiness.check_source(self.source) if r.failed]
        if still:
            raise StageFailed("readiness_missing", f"{still[0].name}: {still[0].detail}", still[0].fix)
        return "ok: " + ", ".join([*notes, "Serena onboarding and Graphify index created by the agent"])

    def _doctor(self) -> str:
        flags = self._common(exclude=False)
        resources = getattr(self.args, "resources", None)
        if resources:
            flags += ["--resources", str(resources)]
        if self.s.online:
            flags += ["--storage-state", str(self.args.storage_state)]
        self._kit("doctor", *flags)
        return "ok"

    def _static(self) -> str:
        latest = outtree.latest_run(self.source)
        if latest is not None:
            self.out = latest
            self.log.attach(latest)
            if self._phase_done("static"):
                return "ok (already done)"
        extra = self._out_flag() if self.out else []
        doc = self._kit("run", *self._common(), "--until", "static", *extra)
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
            self._run_task(stage, task["id"])
            ran.append(task["id"])
        return f"ok: ran {', '.join(ran)}" if ran else "ok (already done)"

    def _blocker(self, task_id: str) -> Path:
        return self.out / "reports" / "blockers" / f"{task_id}.md"

    def _run_task(self, stage: str, task_id: str) -> None:
        self._blocker(task_id).unlink(missing_ok=True)
        shown = self._kit("agent", "show", task_id, *self._out_flag())
        preamble = render_prompt(HEADLESS_DIR / "preamble.md", source=str(self.source), sidecar=str(self.out))
        problems: list[str] = []
        for attempt in range(1, self.s.max_fix + 2):
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
            self._rerun(shown.get("rerun") or [])
            check = self._kit("check", *self._out_flag(), allow_fail=True)
            problems = list(check.get("problems") or [])
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

    # -- result -----------------------------------------------------------------

    def _report(self, exit_code: int, failure: StageFailed | None) -> None:
        result.note_run(sidecar=self.out, source=self.source)
        result.note_extra(stages=[r.as_dict() for r in self.records])
        for record in self.records:
            print(f"  {record.status:8s} {record.id:18s} {record.message}")
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


def _flag(tokens: list[str], name: str) -> str | None:
    for index, token in enumerate(tokens[:-1]):
        if token == name:
            return tokens[index + 1]
    return None


def cmd_headless(args: Namespace) -> int:
    return Headless(args).run()
