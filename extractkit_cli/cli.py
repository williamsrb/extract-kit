"""Argument parsing for `extractkit`, including the help contract.

Bare invocation and `--help` produce identical stdout and exit 0, recursively
for every group. Only a genuine mistake — an unknown subcommand or a bad flag
— writes usage to stderr and exits 2.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from . import (
    agent_tasks,
    check,
    context,
    deps,
    envflags,
    guide,
    headless,
    install,
    kitguard,
    profiles,
    progress,
    promote,
    resources,
    result,
    runner,
)
from .errors import ExtractkitError

DESCRIPTION = """\
Read a legacy checkout and write a stack-agnostic extract tree.

extractkit is profile-driven: YAML types under profiles/ declare a pipeline
and bind stack adapters. Enonic XP7 is the first adapter. PHP is an empty
placeholder. The stack is detected from the checkout (pass --profile to
override). Every command writes on the first call: run writes a sidecar
under <source>/.extract/<run-id>/ and never mutates the source tree.

The pipeline is grouped into nine phases: 1 preflight, 2 context, 3 static,
4 cms, 5 merge, 6 synthesis, 7 agent, 8 check, 9 promote. --from, --until and
step accept a phase id or number. Every run ends with the next command to paste.

Runtime CMS (enonic.cms) is local or review XP only. Pass --branch,
--storage-state and a Guillotine URL; production hosts are refused.

Install once from the kit repo (preflight repeats it), then run every
command from the legacy checkout, in an agent session opened there:
  ./extractkit install

Common examples:
  extractkit profile list
  extractkit profile show enonic
  extractkit doctor --profile php
  extractkit deps --profile enonic
  extractkit context --source .
  extractkit run --source . --until static
  extractkit status --source .
  extractkit resume --source . \\
      --branch draft --storage-state ~/.agents/.auth/xp7-localhost.json \\
      --guillotine http://localhost:8080/admin/site/preview/en/draft
  extractkit run --source . \\
      --out .extract/<run-id> --from merge --until synthesis
  extractkit check --out .extract/<run-id>
  extractkit promote --source . --out .extract/<run-id>

Run 'extractkit GROUP --help' or 'extractkit GROUP COMMAND --help' for details.
"""


def _add_cms_flags(parser: argparse.ArgumentParser, *, headless: bool = False) -> None:
    parser.add_argument(
        "--branch", choices=("draft", "master"),
        help="XP branch. Required when inventory.runtime / enonic.cms runs.",
    )
    parser.add_argument(
        "--xp-host", dest="xp_host", metavar="URL",
        help="Local (default) or review XP origin. Production is refused.",
    )
    parser.add_argument(
        "--guillotine", metavar="URL",
        help="GraphQL POST URL (run parameter). Default: "
             "{host}/admin/site/preview/{project}/{branch}.",
    )
    parser.add_argument(
        "--project", metavar="NAME",
        help="Content Studio project (e.g. en). Used to build the preview URL.",
    )
    parser.add_argument(
        "--storage-state", dest="storage_state", metavar="FILE",
        help="Playwright storage-state JSON. Required when enonic.cms runs.",
    )
    parser.add_argument(
        "--cms-key", dest="cms_keys", action="append", metavar="KEY",
        help="Content key for Site Config harvest (repeatable). Pins keys; "
             "does not walk. Enonic still samples N contents per type via "
             "queryConnection.",
    )
    parser.add_argument(
        "--round2", dest="round2", action="append", metavar="CONTEXT",
        help="Bounded context to survey a second time (repeatable).",
    )
    parser.add_argument(
        "--configenv", metavar="URL",
        help="Config Env admin-tool HTML. Default: {host}{live_config.configenv_path} "
             "from the profile; with neither, Config Env is skipped.",
    )
    parser.add_argument(
        "--site-url", dest="site_url", metavar="URL",
        help="Base URL for baseline page captures. Default: "
             "{host}/admin/site/preview/{project}/{branch}. Local or review hosts only.",
    )
    if headless:
        return  # headless never passes --allow-production, and writes no tasks.md
    parser.add_argument(
        "--allow-production", dest="allow_production", action="store_true",
        help="Override production deny-by-default. Not used in the DoD.",
    )
    parser.add_argument(
        "--tasks", action="store_true",
        help="Write Spec Kit tasks.md (off by default).",
    )


def _add_profile_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile", metavar="NAME",
        help="Stack profile (enonic, php). Default: MANIFEST.yaml source.profile, "
             "else detected from the checkout.",
    )


def _add_exclude_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--exclude", action="append", metavar="PATH",
        help="Source-relative folder or file to leave out of every scan (repeatable). "
             "Adds to the profile's exclude list; recorded in MANIFEST.yaml and kept on resume.",
    )


def _add_output_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="List every recorded action with its path.")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Suppress tips.")


def _add_resources_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--resources", metavar="FILE",
        help="Resources YAML (xp, auth, agent): fills options not set by a flag or EXTRACTKIT_* "
             "variable. See docs/headless.md.",
    )


def _add_progress_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--progress", action="store_true",
                        help="Print one line per step on stderr as it starts and finishes.")


def _add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true",
                        help="Print one JSON result document instead of text.")


def _help_action(parser: argparse.ArgumentParser) -> Callable[[argparse.Namespace], int]:
    def run(_args: argparse.Namespace) -> int:
        parser.print_help()
        return 0
    return run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="extractkit",
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    top = parser.add_subparsers(
        dest="group", required=False, title="command groups", metavar="GROUP"
    )

    def group(name: str, summary: str) -> argparse._SubParsersAction:
        group_parser = top.add_parser(
            name, help=summary, description=summary,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        group_parser.set_defaults(func=_help_action(group_parser))
        return group_parser.add_subparsers(
            dest="action", required=False, title="commands", metavar="COMMAND"
        )

    def flat(name: str, summary: str) -> argparse.ArgumentParser:
        sub = top.add_parser(
            name, help=summary, description=summary,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        return sub

    profile = group("profile", "List and inspect YAML profile types.")
    p_list = profile.add_parser("list", help="Show profile types in profiles/.")
    p_list.set_defaults(func=profiles.cmd_list)
    p_show = profile.add_parser("show", help="Show one profile's composed YAML.")
    p_show.add_argument("name")
    p_show.add_argument("--out", metavar="DIR",
                        help="Extract sidecar. Also composes its context overlay and the "
                             "source's .extractkit/profile.yaml, as a run sees them.")
    p_show.set_defaults(func=profiles.cmd_show)

    agent = group("agent", "List, show and pick the next agent task. The kit never calls a model.")

    def agent_flags(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--out", metavar="DIR",
                         help="Extract sidecar. Default: latest <source>/.extract/<run-id>/.")
        sub.add_argument("--source", metavar="DIR",
                         help="Legacy checkout. Used to find the latest sidecar.")
        sub.add_argument("--json", action="store_true", help="Machine-readable output.")
        _add_output_flags(sub)

    a_list = agent.add_parser("list", help="Every agent task with done or pending state.")
    agent_flags(a_list)
    a_list.set_defaults(func=agent_tasks.cmd_list)
    a_show = agent.add_parser("show", help="Print one task's rendered prompt and input files.")
    a_show.add_argument("task_id", metavar="ID")
    agent_flags(a_show)
    a_show.set_defaults(func=agent_tasks.cmd_show)
    a_next = agent.add_parser("next", help="Print the first pending required task whose inputs exist.")
    agent_flags(a_next)
    a_next.set_defaults(func=agent_tasks.cmd_next)

    ins = flat("install", "Copy the kit into ~/.local/share/extractkit, add the launcher to ~/.local/bin and the skills to ~/.agents/skills and ~/.claude/skills.")
    ins.add_argument("--force", action="store_true",
                     help="Replace a symlink that points somewhere else. Never touches a real file or folder.")
    _add_json_flag(ins)
    ins.set_defaults(func=install.cmd_install)

    doc = flat("doctor", "Validate kit identity and profile YAML (empty PHP is allowed).")
    doc.add_argument("--profile", metavar="NAME", help="Check only this profile.")
    doc.add_argument(
        "--source", metavar="DIR",
        help="Also check dependencies and that the legacy checkout has Serena "
             "onboarding, a Graphify index and a graft index.",
    )
    _add_output_flags(doc)
    _add_resources_flag(doc)
    doc.add_argument("--storage-state", dest="storage_state", metavar="FILE",
                     help="Playwright storage-state JSON the resource probes use. Overrides auth.storage_state.")
    _add_json_flag(doc)
    doc.set_defaults(func=profiles.cmd_doctor)

    dep = flat("deps", "Check that every binary a profile declares is on PATH.")
    dep.add_argument(
        "--profile", default="core", metavar="TYPE",
        help="Profile type whose deps to check (default: core).",
    )
    _add_output_flags(dep)
    _add_json_flag(dep)
    dep.set_defaults(func=deps.cmd_deps)

    ctx = flat("context", "Detect the stack and record the build scope (phase 2, writes context/).")
    ctx.add_argument("--source", required=True, metavar="DIR", help="Legacy checkout (read-only).")
    ctx.add_argument("--out", metavar="DIR",
                     help="Extract tree. Default: <source>/.extract/<run-id>/.")
    _add_profile_flag(ctx)
    _add_exclude_flag(ctx)
    _add_output_flags(ctx)
    _add_json_flag(ctx)
    ctx.set_defaults(func=context.cmd_context)

    run = flat("run", "Execute a profile pipeline and write the sidecar.")
    _add_profile_flag(run)
    run.add_argument("--source", required=True, metavar="DIR",
                     help="Legacy checkout (read-only).")
    run.add_argument("--out", metavar="DIR",
                     help="Extract tree. Default: <source>/.extract/<run-id>/.")
    run.add_argument("--from", dest="from_step", metavar="STEP",
                     help="Start at this phase (id or number), slot, or plugin id.")
    run.add_argument("--until", metavar="STEP",
                     help="Stop after this phase (id or number), slot, or plugin id.")
    _add_cms_flags(run)
    _add_exclude_flag(run)
    _add_output_flags(run)
    _add_resources_flag(run)
    _add_progress_flag(run)
    _add_json_flag(run)
    run.set_defaults(func=runner.cmd_run)

    step = flat("step", "Execute one phase or pipeline slot and write its artifacts.")
    step.add_argument("step_id", metavar="STEP",
                      help="Phase id or number (runs its slots), slot, or plugin id.")
    _add_profile_flag(step)
    step.add_argument("--source", required=True, metavar="DIR")
    step.add_argument("--out", metavar="DIR")
    _add_cms_flags(step)
    _add_exclude_flag(step)
    _add_output_flags(step)
    _add_resources_flag(step)
    _add_progress_flag(step)
    _add_json_flag(step)
    step.set_defaults(func=runner.cmd_step)

    chk = flat("check", "Fail closed on schema, descriptor coverage, missing x-source, or spec FR cites.")
    chk.add_argument("--out", required=True, metavar="DIR",
                     help="Extract tree to validate.")
    _add_output_flags(chk)
    _add_json_flag(chk)
    chk.set_defaults(func=check.cmd_check)

    nxt = top.add_parser(
        "status", aliases=["next"],
        help="Show every phase as done, current, or pending, then the next command.",
        description="Show every phase as done, current, or pending, then the next command.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    nxt.add_argument("--profile", metavar="NAME",
                     help="Profile type. Default: MANIFEST.yaml source.profile.")
    nxt.add_argument("--source", metavar="DIR",
                     help="Legacy checkout. Used to find the latest sidecar.")
    nxt.add_argument("--out", metavar="DIR",
                     help="Extract tree. Default: latest <source>/.extract/<run-id>/.")
    _add_output_flags(nxt)
    _add_json_flag(nxt)
    nxt.set_defaults(func=progress.cmd_status)

    res = flat("resume", "Continue a sidecar from the first incomplete pipeline slot.")
    _add_profile_flag(res)
    res.add_argument("--source", required=True, metavar="DIR")
    res.add_argument("--out", metavar="DIR",
                     help="Extract tree. Default: latest <source>/.extract/<run-id>/.")
    res.add_argument("--until", metavar="STEP",
                     help="Stop after this phase (id or number), slot, or plugin id.")
    _add_cms_flags(res)
    _add_exclude_flag(res)
    _add_output_flags(res)
    _add_resources_flag(res)
    _add_progress_flag(res)
    _add_json_flag(res)
    res.set_defaults(func=progress.cmd_resume)

    promo = flat("promote", "Copy constitution, PRODUCT/DESIGN, and specs into the source tree. Never edits .gitignore or .git/.")
    promo.add_argument("--source", required=True, metavar="DIR",
                       help="Legacy checkout to copy into.")
    promo.add_argument("--out", metavar="DIR",
                       help="Extract sidecar. Default: latest <source>/.extract/<run-id>/.")
    promo.add_argument("--force", action="store_true",
                       help="Overwrite destinations git cannot restore.")
    _add_output_flags(promo)
    _add_json_flag(promo)
    promo.set_defaults(func=promote.cmd_promote)

    hl = flat(
        "headless",
        "Run the whole extract with no human: calls an agent CLI for the preflight and each agent task.",
    )
    hl.add_argument("--source", required=True, metavar="DIR", help="Legacy checkout (read-only).")
    _add_profile_flag(hl)
    hl.add_argument("--agent", metavar="NAME",
                    help="Agent CLI from the agents: block of extractkit.yaml (default: claude).")
    hl.add_argument("--agent-permissions", dest="agent_permissions", choices=("allowlist", "bypass"),
                    metavar="MODE", help="allowlist (default) or bypass. Bypass is the operator's call.")
    hl.add_argument("--allowed-tools", dest="allowed_tools", action="append", metavar="TOOL",
                    help="Tool allowlist for the agent (repeatable). Replaces the agents: default.")
    _add_resources_flag(hl)
    _add_cms_flags(hl, headless=True)
    _add_exclude_flag(hl)
    hl.add_argument("--until", type=headless.stage_id, metavar="STAGE",
                    help="Stop after this stage: " + ", ".join(headless.STAGES) + ".")
    hl.add_argument("--promote", action="store_true",
                    help="Also run promote at the end (never --force).")
    hl.add_argument("--max-fix-attempts", dest="max_fix_attempts", type=int, default=2, metavar="N",
                    help="Fix attempts per agent task after a failed check (default 2).")
    hl.add_argument("--task-timeout", dest="task_timeout", type=int, default=1800, metavar="SECONDS",
                    help="Kill an agent process after this long (default 1800).")
    hl.add_argument("-q", "--quiet", action="store_true", help="No progress lines on stderr.")
    _add_json_flag(hl)
    hl.set_defaults(func=headless.cmd_headless)

    return parser


def _fail(exc: ExtractkitError, args: argparse.Namespace | None, raw: list[str], as_json: bool) -> int:
    if as_json:
        return result.fail(exc, args, raw)
    print(f"error: {exc}", file=sys.stderr)
    prog = getattr(args, "prog_display", None) or guide.prog_display()
    if exc.fix_args:
        command = guide.join([prog, *guide.rewrite(raw, set=exc.fix_args)])
        print(f"fix:   $ {command}", file=sys.stderr)
        if exc.fix:
            print(f"hint:  {exc.fix}", file=sys.stderr)
    elif exc.fix:
        print(f"fix:   {exc.fix}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw = list(argv if argv is not None else sys.argv[1:])
    result.reset()
    try:
        envflags.apply_defaults(parser)
    except ExtractkitError as exc:
        return _fail(exc, None, raw, result.json_requested(raw))
    args, unknown = parser.parse_known_args(raw)

    if unknown:
        parser.error("unrecognized arguments: " + " ".join(unknown))
    if not hasattr(args, "func"):
        parser.print_help()
        return 0

    args.argv = raw
    args.prog_display = guide.prog_display()
    as_json = bool(getattr(args, "json", False))
    try:
        envflags.finish(args, raw)
        resources.apply(args, raw)
        kitguard.refuse_kit(args)
        if not as_json:
            return int(args.func(args))
        with result.capture(args, raw) as collector:
            code = int(args.func(args))
        return result.finish(collector, code, args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except ExtractkitError as exc:
        return _fail(exc, args, raw, as_json)
