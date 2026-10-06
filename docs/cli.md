# CLI

Every command writes on the first call. Nothing needs a second run to
write.

Refusals print `error:` and a `fix:`. When the fix is a flag, the line is
your own command with that flag added.

## Commands

<!-- markdownlint-disable MD013 -->
| Command | Role |
| --- | --- |
| `profile list` / `show NAME [--out DIR]` | Inspect YAML types; with `--out`, the profile as that sidecar's run sees it, overlays included |
| `doctor [--profile NAME] [--source DIR]` | Validate kit, composed profiles, and phases; with `--source`, also the deps, the target's agent tooling and the stack it would detect |
| `deps [--profile NAME]` | Every dep run, not just found: binaries, Python version and modules |
| `context --source DIR [--out DIR]` | Detect the stack and record the build scope (phase 2); `run` and `resume` call it when the sidecar has none |
| `run --source DIR [--profile NAME]` | Pipeline; `--from` / `--until` |
| `step STEP --source DIR [--profile NAME]` | One phase or one slot |
| `agent list\|show ID\|next [--out DIR] [--json]` | List, render and pick agent tasks. The kit never calls a model |
| `check --out DIR` | Schema, coverage, `x-source`, spec FR, `BUSINESS.md` when present |
| `status [--source DIR] [--out DIR]` | Phase checklist (alias `next`) |
| `resume --source DIR [--profile NAME]` | Continue from first incomplete slot |
| `promote --source DIR [--out DIR] [--force]` | Copy Spec Kit + PRODUCT |
| `headless --source DIR [--agent NAME] [--resources FILE] [--until STAGE] [--promote] [--no-enrich]` | Run the whole extract with no human, calling an agent CLI for the preflight and each agent task. The one command that starts an agent CLI; see [Headless](headless.md) |
<!-- markdownlint-enable MD013 -->

## Defaults

<!-- markdownlint-disable MD013 -->
| Command | Default |
| --- | --- |
| `deps` | `core` unless `--profile`. An optional tool that is absent prints `skipped`; one that is broken prints `BROKEN` but does not fail the exit code |
| `doctor` | All profiles unless `--profile`. `--source` adds the deps of `--profile` (default `core`) and the readiness rows |
| `run`, `step` | New sidecar unless `--out` names one. With `--out`, files are added or overwritten |
| `status`, `resume`, `promote` | Latest sidecar under `<source>/.extract/` or `<source>/extract/` (by run id) unless `--out` |
| `run`, `step`, `resume`, `status` profile | `--profile`, else `MANIFEST.yaml` `source.profile`, else the stack detected from the checkout (see [Context](#context)). No marker, or markers for both stacks, is refused with a `fix:` that passes `--profile` |
| `resume` | First slot that is not done, through the end or `--until` |
| `check` | Reads the sidecar only |
| `agent` | Latest sidecar under `<source>/.extract/` or `<source>/extract/` when `--source` is given; otherwise `--out` is required. `next` lists required tasks only; `show spec.enrich` or `show spec.review` runs an optional one |
<!-- markdownlint-enable MD013 -->

`resume` never starts at an optional slot (`inventory.baseline`,
`report.compat`), but runs one that falls inside its range. To add one
later, use `step`; `status` prints the command.

If `resume` lands on CMS, pass the CMS flags. To skip CMS, use
`run --from merge` instead. Done-markers are in [steps](steps.md).

## Exit codes

<!-- markdownlint-disable MD013 -->
| Code | Meaning |
| --- | --- |
| 0 | Done, or `check` / `doctor` / `deps` clean |
| 1 | Refused (`error:` + `fix:`), `check` or `doctor` problems, required dep missing, or a `headless` stage failed |
| 2 | Usage error: unknown command or flag |
| 3 | `headless` only: a task is blocked and a person must look |
| 130 | Interrupted |
<!-- markdownlint-enable MD013 -->

Bare `extractkit` and any `--help` print help and exit 0.

## JSON output and environment variables

`--json` is accepted by `install`, `deps`, `doctor`, `context`, `run`, `step`,
`resume`, `status`, `check`, `promote`, `headless` and `agent list|show|next`.
It prints one JSON document on stdout and nothing else, errors included
(`ok: false`, `error.code`, `error.message`, `error.fix`, `error.fix_command`);
exit codes do not change. The envelope is `schemas/result.schema.json`:
`schema`, `ok`, `command`, `exit`, `phase`, `sidecar`, `source`, `rows`,
`wrote`, `skips`, `problems`, `error`, `next_command` and `config`. The `agent`
payloads keep their own keys (`next` stays a task id in `list` and a task row
in `next`); the suggested command is `next_command`, with `argv` ready to
exec. `config` gives each option's origin (`cli`, `env`, `file`, `default`)
with secrets redacted. Argparse usage errors stay on stderr with exit 2.

Every long option `--foo-bar` has an env form `EXTRACTKIT_FOO_BAR`, and
`--resources FILE` (`EXTRACTKIT_RESOURCES`) fills what no flag or variable set.
`--allow-production` and `--force` have no env form. See
[Headless](headless.md) for the precedence, the table of variables and the
resources file.

## Kit workspace guard

Every command except `install`, `deps`, `profile list|show`, bare invocation,
`--help` and `doctor` without `--source` refuses to run when the working
folder, `--source` or `--out` is inside the kit repo or the installed kit
(`error.code: "kit_workspace"`, exit 1). Run from the legacy checkout.

## Phases

The operator path and sidecar lineage are in [flow](flow.md).

`profiles/core.yaml` groups the pipeline into nine phases. Every profile
inherits them. `--from`, `--until` and `step` accept a phase id or number
as well as a slot or plugin id.

<!-- markdownlint-disable MD013 -->
| # | Phase | Slots or command |
| --- | --- | --- |
| 1 | `preflight` | `doctor` (command) |
| 2 | `context` | `context` (command) |
| 3 | `static` | map.code, map.semantic, inventory.descriptors, inventory.controllers, inventory.templates, maps.normalize, inventory.integrations |
| 4 | `cms` | inventory.runtime, inventory.baseline (optional) |
| 5 | `merge` | maps.merge, rules.view, inventory.docs |
| 6 | `synthesis` | product.impeccable, docs.synthesize, use_cases, spec.kit, report.compat (optional) |
| 7 | `agent` | `agent` (command) |
| 8 | `check` | `check` (command) |
| 9 | `promote` | `promote` (command) |
<!-- markdownlint-enable MD013 -->

<!-- markdownlint-disable MD013 -->
| Token | Effect |
| --- | --- |
| `--from <phase>` | Start at the phase's first slot |
| `--until <phase>` | Stop after the phase's last slot |
| `step <phase>` | Run every slot of that phase |
| slot or plugin id | Single-slot meaning, as before |
<!-- markdownlint-enable MD013 -->

Phases 1, 2, 7, 8 and 9 are commands. Passing them to `--from` / `--until` /
`step` is refused, with the command to run instead (`run --from agent` names
`extractkit agent next --out <sidecar>`, and `step context` names
`extractkit context --source <legacy-checkout>`).

## Context

The `context` phase works out the project, so no client profile ships in
the kit. `extractkit context --source DIR` (called by `run` and `resume` when
the sidecar has no overlay) writes two files under the sidecar:

- `context/build-scope.json`: `branch`, `entry_points`, `in_scope` and
  `out_of_scope` from the build scope (the folders no default-branch build
  names). It never excludes any of them.
- `context/profile.yaml`: the overlay, with `extends: <stack>` and, when the
  build scope has nothing to decide, `exclude: []`. The agent tasks
  `context.exclude` and `context.live_config` write its `exclude` and
  `live_config` keys. A re-run refreshes `extends` and the build scope and
  keeps those two keys.

The stack is `enonic` when `src/main/resources/application.xml` or
`src/main/resources/site/site.xml` exists under a folder no exclude covers,
and `php` when `composer.json` is at the root. `--profile` always wins.

A run composes the profile in layers, each with the same merge rules as
`extends`: the stack chain (`core`, then `enonic`), then
`<sidecar>/context/profile.yaml`, then the operator's override
`<source>/.extractkit/profile.yaml`. The kit reads the override and never
writes it. A layer after the stack may set only `exclude` and `live_config`;
any other key is refused, naming the file and the key. `exclude` lists merge
as a union, so a later layer cannot drop an entry, and a resumed run keeps
what `MANIFEST.yaml` already excluded: correcting an exclusion means a new
sidecar. `live_config` merges one level deep, so an override replaces a whole
sub-key such as `env_endpoints`. `MANIFEST.yaml` `context.layers` lists the
files that took part, and `profile show NAME --out DIR` prints the result.

`check` runs `context_grounded` on `context/profile.yaml` only (the override
is exempt). An `exclude` entry must be in `build-scope.json` `out_of_scope`. A
`live_config` key, `env_endpoints` path or URL path must occur in the source
(any file outside the built-in skip folders, whatever `exclude` says) or among
the harvested config keys and values, case-insensitively. An origin host must
occur literally there, or every dot-separated label of it must appear on one
source line (a template literal builds `test.` and `epayment.nets.eu` apart).

## Agent

`extractkit agent` reads the task registry in `agent-tasks/<id>/` (a
`task.yaml` and a `prompt.md`; schema in `schemas/agent-task.schema.json`).

<!-- markdownlint-disable MD013 -->
| Command | Output |
| --- | --- |
| `agent list` | Every task as done, pending (`next` marks the first), or optional; `--json` adds `reads`, `missing_reads`, `writes`, `rerun`, `promote`, `checks` |
| `agent show ID` | The prompt with `{sidecar}`, `{source}`, `{profile}` and `{run_id}` filled in, then the input and output files; `--json` adds `prompt` and `inputs` |
| `agent next` | The first pending required task whose inputs exist, then a pasteable `agent show`. With none pending it points at `check`; with only blocked tasks it names the missing inputs and points at `status` |
<!-- markdownlint-enable MD013 -->

A task is done when its `done` markers exist, or when its `done_check` holds:
for `rules.name`, no business rule in `rules/view-rules.json` is still
`extracted`; for `context.exclude`, the overlay has an `exclude` key; for
`context.live_config`, the overlay has a `live_config` key or no
`inventory/live-config-candidates.json` exists (nothing was harvested).
`context.exclude` is ready after the static phase and `context.live_config`
after the CMS slot, so `next` offers `agent show context.exclude` while the
pipeline is still before the CMS and merge phases. The agent
phase is done when every required task is done. `spec.enrich` and
`spec.review` are optional and never block it.

While a required task is pending, `status`, `run`, `step` and `resume` end
with `Agent is next` and `agent next`, plus `or skip to check`. `check`
validates `business/BUSINESS.md` only when it exists; a deterministic-only
run still passes.

## Other flags

`--tasks` writes Spec Kit `tasks.md` (off by default). Accepted by `run`,
`step` and `resume`. It only affects `spec.kit`.

<!-- markdownlint-disable MD013 -->
| Flag | Effect |
| --- | --- |
| `--exclude PATH` | Leave a source-relative folder or file out of every scan. Repeatable; `run`, `step` and `resume` |
| `-v`, `--verbose` | List every recorded action with its path |
| `-q`, `--quiet` | Suppress tips |
<!-- markdownlint-enable MD013 -->

`--exclude` adds to the profile's `exclude:` list. The union is written to
`MANIFEST.yaml` `exclude`, and a later `run`, `step` or `resume` on the same
sidecar keeps it, so every slot reads the same tree. A path that is absolute
or leaves the source exits 1. The built-in skip folders (`node_modules`,
`vendor`, `dist`, `build`, `target`, `.git`, `.extract`, `graft`,
`graphify-out`, `.serena`, `__pycache__`, `.gradle`) are always pruned.
`map.code` and `map.semantic` reuse the source's own graft and Graphify
indexes, which the kit does not rebuild, so an exclude does not reach them.

## Output

### Header

`run`, `step` and `resume` print the profile, the sidecar, and whether it
is new or existing.

### Slot rows

One `[N/9] <Phase>` block per phase touched. Each slot is a row: `✓` with
up to three artifacts relative to the sidecar (then `+N more`), or `–`
with the skip reason. The body ends with `N files written`.

### Tips

At most two, and only when something triggers them: a skipped slot's fix,
or a row cut short (`Add -v to list every path.`).

### Next

Every successful command ends with a `next` block: the command to run
next, rebuilt from your flags and pinned to `--out <sidecar>`, plus an
`or` alternative where one exists (continue without CMS, skip the agent
phase to `check`, or add CMS after the offline route).

A value the kit cannot know stays as a placeholder such as
`<playwright-state.json>` or `<legacy-checkout>`.

Colour appears only on a TTY and when `NO_COLOR` is unset. Glyphs fall
back to `ok` / `skip` / `>` / `.` when stdout is not UTF-8.

Errors go to stderr as `error:` then
`fix:   $ <your command with the fix>` when a flag fixes it (with the
prose as `hint:`), or a prose `fix:` otherwise.

## Deps

`deps` runs each declared `probe` (an argv list, exit 0 within 5 s means
ok) and reports four states:

<!-- markdownlint-disable MD013 -->
| State | Meaning |
| --- | --- |
| `ok` | On PATH and the probe passed |
| `MISSING` | Not on PATH |
| `BROKEN` | On PATH but the probe failed. Prints the first stderr line (the last line of a Python traceback) and a `fix:` |
| `skipped` | Optional and absent |
<!-- markdownlint-enable MD013 -->

Python rows (`python`, `python:<module>`) check the interpreter version
against `python: ">=3.12"` and each `python_modules` entry with
`importlib.util.find_spec`. A required row that is `MISSING` or `BROKEN`
exits 1. A `BROKEN` optional tool, such as a `graphify` shim whose package
is gone, prints a `note:` and does not change the exit code.

## Install

`extractkit install` copies the kit into the user's home. Nothing it writes
points back into the kit repo, so the checkout can be deleted afterwards. To
update, run it again from a fresh checkout.

<!-- markdownlint-disable MD013 -->
| Row | Path | Content |
| --- | --- | --- |
| `install` | `~/.local/share/extractkit/` | Kit runtime, `docs/*.md`, skills, and the `.extractkit-install.json` marker (commit, time, files). The row shows the installed commit and time |
| `launcher extractkit` | `~/.local/bin/extractkit` | A regular file that runs the installed copy |
| `skill <name>` | `~/.agents/skills/<name>` | A copy of `<kit>/skills/<name>` with the marker |
| `claude <name>` | `~/.claude/skills/<name>` | A link to `~/.agents/skills/<name>` |
| `extractkit on PATH` | (check only) | `~/.local/bin` is a PATH entry |
<!-- markdownlint-enable MD013 -->

The marker, not the name, proves the install created a folder. A folder or
file without it is `BROKEN` and is never touched. A symlink that resolves into
a kit checkout (the old symlink install) is replaced. Any other symlink is
`BROKEN` until `--force` replaces it. A failing row exits 1. A new install is
written beside the old one and swapped in by rename, so a failed copy leaves
the previous install in place.

Run from the installed copy, `install` copies nothing. It checks that the
launcher, the skills and their markers match the installed commit, and a
mismatch is `BROKEN` with the fix `run ./extractkit install from a kit
checkout`. `deps` and `doctor --source` run the same install first: a full
install from a checkout, a check from the installed copy.

Once the link is on PATH, `next` blocks and `fix:` lines print `extractkit`.
Run from inside the kit repo without the link, they print `./extractkit`;
from anywhere else, the absolute path.

## Preflight

`doctor --source DIR` adds the target checkout to the profile check:

<!-- markdownlint-disable MD013 -->
| Row | Ready when | Missing |
| --- | --- | --- |
| `serena onboarding` | `.serena/project.yml` exists and `.serena/memories/` holds a `*.md` | exit 1; fix: open an agent session in the source and run Serena onboarding |
| `graphify index` | `graphify-out/graph.json` exists | exit 1; fix: run `/graphify .` from a session opened in the source |
| `graft index` | `graft/` exists | warning only; fix: run `graft build` in the source |
| `build scope` | every top-level folder is named by a default-branch build | warning only; lists the folders and the `--exclude` flags |
<!-- markdownlint-enable MD013 -->

`build scope` reads the build entry points without running them:
`.gitlab-ci.yml` jobs whose `only`, `except` or `rules` let them run on the
default branch (`origin/HEAD`, else a local `main` or `master`, else the
checked-out branch), with local `extends` templates resolved; the Makefile
targets the default goal reaches, plus the variables their recipes use; root
`package.json` scripts; and root Gradle or Maven files, which also keep
`src`. Hidden folders, the skip folders and the profile's `exclude:` are
left out. A folder outside the build is not always dead (a cron script that
calls the site, for example), so the row only reports. The operator decides
with `--exclude` or the profile. With no entry point the row is `skipped`.

The kit never runs Serena, graphify or graft; it detects them and prints the
fix. The check is presence only, not freshness. `run` is not gated by it:
`map.code` and `map.semantic` still skip with the same fix, and
`MANIFEST.yaml` `maps.serena` records the `.serena/` path or null. The
`next` block after a failing `doctor --source` is the first fix, then the
command to re-run. A clean `doctor --source` suggests `run --until static`
on that source.

## CMS flags

`--branch draft|master` is required when `inventory.runtime` is in the
slice. `--storage-state` is required whenever `enonic.cms` runs.

<!-- markdownlint-disable MD013 -->
| Flag | Effect |
| --- | --- |
| `--xp-host URL` | XP origin |
| `--project NAME` | Content Studio project; builds the preview URL |
| `--guillotine URL` | GraphQL POST URL |
| `--cms-key KEY` | Content key to survey (repeatable) |
| `--round2 CONTEXT` | Survey that context's keys a second time (repeatable) |
| `--configenv URL` | Config Env HTML page. Default: `{host}` plus the profile's `live_config.configenv_path`; with neither, Config Env is skipped |
| `--site-url URL` | Base URL for `inventory.baseline` page captures. Default: `{host}/admin/site/preview/{project}/{branch}` |
| `--allow-production` | Lift the production refusal (unused in the DoD) |
<!-- markdownlint-enable MD013 -->

Each flag falls back to the profile's `cms` key, then a built-in default.
The table is in [profiles](profiles.md#enonic). A key given with
`--cms-key` replaces the profile's `cms.keys`.

`--xp-host`, `--guillotine`, `--configenv` and `--site-url` must be local
(`localhost`, `127.0.0.1`, `::1`, `0.0.0.0`, `*.localhost`) or review
(`*.k8s.seeds.no`). Anything else is production and refused.

`--cms-key` pins Site Config harvest. Enonic also samples
`cms.sample_per_type` (default 3) contents per type without walking the
tree.

## Check

`check --out DIR` fails closed, listing every problem, when:

- `MANIFEST.yaml` or one of the four map files is missing or breaks its
  schema
- `inventory/static.json` is missing, or a resource in it is in neither
  the maps (`entry` or `stackRef.enonic.descriptor`) nor
  `hygiene/dead-code.md` (FR-10 coverage)
- `integrations/openapi.yaml` is missing, is not YAML, or has an
  operation without `x-source`
- `inventory/runtime.json`, `inventory/controllers.json`,
  `inventory/templates.json`, `rules/view-rules.json`,
  `inventory/content-volume.json`, the Enonic extras, or
  `map/bounded-contexts.json` exist and break their schema
- a file in `inventory/templates.json` maps to no component surface, or a
  surface with a `template` is not spec-ready (`entry`, `inputs`,
  `children`, `dataSource`, `status`)
- a `business` rule in `rules/view-rules.json` is cited by no spec while a
  spec exists, and `rules/review.md` does not mark it `out-of-scope: yes`
- a `spec-kit/specs/**/spec.md` has no `FR-N` heading, an FR section has
  no `Evidence:` line, or a paragraph marked `_(inferred)_` has no
  `Evidence:` line in it or right after it
- `context/profile.yaml` names an `exclude` entry outside
  `context/build-scope.json` `out_of_scope`, or a `live_config` fact the
  source and the harvested config do not support (see [Context](#context))

Optional files that are absent are not problems.

## Static vs full

A full `run` without `--until` includes CMS and needs `--branch` and
`--storage-state`.

```bash
extractkit run --source . --until static
extractkit run --source . --out <sidecar> \
  --from merge --until synthesis
```

## Promote guard

`promote` writes into the legacy checkout on the first call. It refuses
the whole promote, writing nothing, when:

- an existing destination is modified, staged, untracked, or ignored
- the source is not a git work tree

Tracked, clean destinations are overwritten (git can restore them).
Destinations that do not exist are always written. `--force` skips the
check.

## Sidecar

Default `--out` is `<source>/.extract/<run-id>/`. `.extract/.gitignore`
is `*`, written only when the sidecar sits under `<source>/.extract/`. With
an `--out` elsewhere the run writes nothing into the source. The kit never
edits the source `.gitignore` or `.git/`.

`headless` writes `<source>/extract/<run-id>/` instead: a visible folder with
no `.gitignore`, for a pipeline artifact. `status`, `resume`, `promote` and
`agent` with `--source` take the newest run under either folder, and scans
skip `<source>/extract/` once it holds a run (a folder with `MANIFEST.yaml`).
