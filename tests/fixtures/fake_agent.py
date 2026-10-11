#!/usr/bin/env python3
"""A stand-in agent CLI for the headless tests. It reads the prompt on stdin.

FAKE_AGENT_MODE: `ok` (default) does the work; `block` writes a blocker file;
`noop` exits 0 without writing anything; `sleep` hangs; `crash` exits 2.
FAKE_AGENT_REPORT_ENV: comma-separated variable names; their values go to `fake-env.json`.
FAKE_AGENT_DEAD: comma-separated FAKE_TOKEN values that always exit 1, like a spent quota.
FAKE_AGENT_DIE_ON: `<token>:<task id>`; that token exits 1 on that task and is dead from then on.
FAKE_AGENT_REPORT_MODEL: the model the result JSON reports in `modelUsage`.
Every run appends `<token> <resumed|-> <first prompt line>` to `fake-calls.log`.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import yaml

mode = os.environ.get("FAKE_AGENT_MODE", "ok")
prompt = sys.stdin.read()
cwd = Path.cwd()

if os.environ.get("FAKE_AGENT_REPORT_ENV"):
    names = os.environ["FAKE_AGENT_REPORT_ENV"].split(",")
    (cwd / "fake-env.json").write_text(json.dumps({n: os.environ.get(n) for n in names}), encoding="utf-8")

token = os.environ.get("FAKE_TOKEN", "")
with (cwd / "fake-calls.log").open("a", encoding="utf-8") as calls:
    calls.write(f"{token} {'resumed' if '## Resumed' in prompt else '-'} {prompt.splitlines()[0] if prompt else ''}\n")
spent = cwd / ".fake-dead"
if token and (token in os.environ.get("FAKE_AGENT_DEAD", "").split(",") or (spent.is_file() and token in spent.read_text().split())):
    sys.exit(1)
die_token, _, die_task = os.environ.get("FAKE_AGENT_DIE_ON", "").partition(":")
if die_token and die_token == token and re.search(rf"^# Task {re.escape(die_task)}:", prompt, re.MULTILINE):
    with spent.open("a", encoding="utf-8") as handle:
        handle.write(token + "\n")
    sys.exit(1)

if mode == "sleep":
    time.sleep(60)
if mode == "crash":
    sys.exit(2)
if mode == "noop":
    sys.exit(0)

if os.environ.get("FAKE_AGENT_REPORT_MODEL"):
    print(json.dumps({"usage": {"input_tokens": 1}, "modelUsage": {os.environ["FAKE_AGENT_REPORT_MODEL"]: {}}}))

if "# Headless preflight" in prompt:
    (cwd / ".serena" / "memories").mkdir(parents=True, exist_ok=True)
    (cwd / ".serena" / "project.yml").write_text("project_name: fake\n", encoding="utf-8")
    (cwd / ".serena" / "memories" / "overview.md").write_text("# fake\n", encoding="utf-8")
    (cwd / "graphify-out").mkdir(exist_ok=True)
    (cwd / "graphify-out" / "graph.json").write_text("{}\n", encoding="utf-8")
    sys.exit(0)

task = re.search(r"^# Task (\S+?):", prompt, re.MULTILINE)
sidecar = re.search(r"^Sidecar: `([^`]+)`", prompt, re.MULTILINE)
if not task or not sidecar:
    sys.exit(0)
task_id, out = task.group(1), Path(sidecar.group(1))

if mode == "block":
    blockers = out / "reports" / "blockers"
    blockers.mkdir(parents=True, exist_ok=True)
    (blockers / f"{task_id}.md").write_text(
        "Reason: the fake agent was told to block\nEvidence: FAKE_AGENT_MODE=block\n", encoding="utf-8",
    )
    sys.exit(0)

if task_id == "context.exclude":
    path = out / "context" / "profile.yaml"
    overlay = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    overlay["exclude"] = ["prototype"]
    path.write_text(yaml.safe_dump(overlay), encoding="utf-8")
