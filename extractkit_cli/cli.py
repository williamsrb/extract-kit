"""Argument parsing for `extractkit`, including the help contract.

Bare invocation and `--help` produce identical stdout and exit 0, recursively
for every group. Only a genuine mistake — an unknown subcommand or a bad flag
— writes usage to stderr and exits 2.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from . import check, deps, guide, profiles, progress, promote, runner
from .errors import ExtractkitError

DESCRIPTION = """\
Read a legacy checkout and write a stack-agnostic extract tree.

extractkit is profile-driven: YAML types under profiles/ declare a pipeline
and bind stack adapters. Enonic XP7 is the first adapter. PHP is an empty
placeholder. Every command writes on the first call: run writes a sidecar
under <source>/.extract/<run-id>/ and never mutates the source tree.

The pipeline is grouped into seven phases: 1 preflight, 2 static, 3 cms,
4 merge, 5 synthesis, 6 check, 7 promote. --from, --until and step accept a
phase id or number. Every run ends with the next command to paste.

Runtime CMS (enonic.cms) is local or review XP only. Pass --branch,
--storage-state and a Guillotine URL; production hosts are refused.

Common examples:
  extractkit profile list
  extractkit profile show enonic
  extractkit doctor --profile php
  extractkit deps --profile enonic
  extractkit run --profile enonic --source ./legacy --until static
  extractkit status --source ./legacy
  extractkit resume --profile enonic --source ./legacy \\
      --branch draft --storage-state ~/.agents/.auth/xp7-localhost.json \\
      --guillotine http://localhost:8080/admin/site/preview/en/draft
  extractkit run --profile enonic --source ./legacy \\
      --out ./legacy/.extract/<run-id> --from merge --until synthesis
  extractkit check --out ./legacy/.extract/<run-id>
  extractkit promote --source ./legacy --out ./legacy/.extract/<run-id>

Run 'extractkit GROUP --help' or 'extractkit GROUP COMMAND --help' for details.
"""


def _add_cms_flags(parser: argparse.ArgumentParser) -> None:
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
    parser.add_argument(
        "--allow-production", dest="allow_production", action="store_true",
        help="Override production deny-by-default. Not used in the DoD.",
    )
    parser.add_argument(
        "--tasks", action="store_true",
        help="Write Spec Kit tasks.md (off by default).",
    )


def _add_output_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="List every recorded action with its path.")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Suppress tips.")


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
    p_show.set_defaults(func=profiles.cmd_show)

    doc = flat("doctor", "Validate kit identity and profile YAML (empty PHP is allowed).")
    doc.add_argument("--profile", metavar="NAME", help="Check only this profile.")
    doc.add_argument(
        "--source", metavar="DIR",
        help="Also check dependencies and that the legacy checkout has Serena "
             "onboarding, a Graphify index and a graft index.",
    )
    _add_output_flags(doc)
    doc.set_defaults(func=profiles.cmd_doctor)

    dep = flat("deps", "Check that every binary a profile declares is on PATH.")
    dep.add_argument(
        "--profile", default="core", metavar="TYPE",
        help="Profile type whose deps to check (default: core).",
    )
    _add_output_flags(dep)
    dep.set_defaults(func=deps.cmd_deps)

    run = flat("run", "Execute a profile pipeline and write the sidecar.")
    run.add_argument("--profile", required=True, metavar="NAME")
    run.add_argument("--source", required=True, metavar="DIR",
                     help="Legacy checkout (read-only).")
    run.add_argument("--out", metavar="DIR",
                     help="Extract tree. Default: <source>/.extract/<run-id>/.")
    run.add_argument("--from", dest="from_step", metavar="STEP",
                     help="Start at this phase (id or number), slot, or plugin id.")
    run.add_argument("--until", metavar="STEP",
                     help="Stop after this phase (id or number), slot, or plugin id.")
    _add_cms_flags(run)
    _add_output_flags(run)
    run.set_defaults(func=runner.cmd_run)

    step = flat("step", "Execute one phase or pipeline slot and write its artifacts.")
    step.add_argument("step_id", metavar="STEP",
                      help="Phase id or number (runs its slots), slot, or plugin id.")
    step.add_argument("--profile", required=True, metavar="NAME")
    step.add_argument("--source", required=True, metavar="DIR")
    step.add_argument("--out", metavar="DIR")
    _add_cms_flags(step)
    _add_output_flags(step)
    step.set_defaults(func=runner.cmd_step)

    chk = flat("check", "Fail closed on schema, descriptor coverage, missing x-source, or spec FR cites.")
    chk.add_argument("--out", required=True, metavar="DIR",
                     help="Extract tree to validate.")
    _add_output_flags(chk)
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
    nxt.set_defaults(func=progress.cmd_status)

    res = flat("resume", "Continue a sidecar from the first incomplete pipeline slot.")
    res.add_argument("--profile", required=True, metavar="NAME")
    res.add_argument("--source", required=True, metavar="DIR")
    res.add_argument("--out", metavar="DIR",
                     help="Extract tree. Default: latest <source>/.extract/<run-id>/.")
    res.add_argument("--until", metavar="STEP",
                     help="Stop after this phase (id or number), slot, or plugin id.")
    _add_cms_flags(res)
    _add_output_flags(res)
    res.set_defaults(func=progress.cmd_resume)

    promo = flat("promote", "Copy constitution, PRODUCT/DESIGN, and specs into the source tree. Never edits .gitignore or .git/.")
    promo.add_argument("--source", required=True, metavar="DIR",
                       help="Legacy checkout to copy into.")
    promo.add_argument("--out", metavar="DIR",
                       help="Extract sidecar. Default: latest <source>/.extract/<run-id>/.")
    promo.add_argument("--force", action="store_true",
                       help="Overwrite destinations git cannot restore.")
    _add_output_flags(promo)
    promo.set_defaults(func=promote.cmd_promote)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw = list(argv if argv is not None else sys.argv[1:])
    args, unknown = parser.parse_known_args(raw)

    if unknown:
        parser.error("unrecognized arguments: " + " ".join(unknown))
    if not hasattr(args, "func"):
        parser.print_help()
        return 0

    args.argv = raw
    args.prog_display = guide.prog_display()
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except ExtractkitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if exc.fix_args:
            command = guide.join([args.prog_display, *guide.rewrite(raw, set=exc.fix_args)])
            print(f"fix:   $ {command}", file=sys.stderr)
            if exc.fix:
                print(f"hint:  {exc.fix}", file=sys.stderr)
        elif exc.fix:
            print(f"fix:   {exc.fix}", file=sys.stderr)
        return 1
