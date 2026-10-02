#!/usr/bin/env python3
"""A stand-in agent CLI for the headless tests. It reads the prompt on stdin.

FAKE_AGENT_MODE: `ok` (default) does the work; `block` writes a blocker file;
`noop` exits 0 without writing anything; `sleep` hangs; `crash` exits 2.
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

import yaml

mode = os.environ.get("FAKE_AGENT_MODE", "ok")
prompt = sys.stdin.read()
cwd = Path.cwd()

if mode == "sleep":
    time.sleep(60)
if mode == "crash":
    sys.exit(2)
if mode == "noop":
    sys.exit(0)

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
