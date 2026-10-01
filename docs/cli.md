# CLI

Every command writes on the first call. Nothing needs a second run to
write.

Refusals print `error:` and a `fix:`. When the fix is a flag, the line is
your own command with that flag added.

## Commands

<!-- markdownlint-disable MD013 -->
| Command | Role |
| --- | --- |
| `profile list` / `show NAME` | Inspect YAML types |
| `doctor [--profile NAME] [--source DIR]` | Validate kit, composed profiles, and phases; with `--source`, also the deps and the target's agent tooling |
| `deps [--profile NAME]` | Every dep run, not just found: binaries, Python version and modules |
| `run --profile NAME --source DIR` | Pipeline; `--from` / `--until` |
| `step STEP --profile NAME --source DIR` | One phase or one slot |
| `agent list\|show ID\|next [--out DIR] [--json]` | List, render and pick agent tasks. The kit never calls a model |
| `check --out DIR` | Schema, coverage, `x-source`, spec FR, `BUSINESS.md` when present |
| `status [--source DIR] [--out DIR]` | Phase checklist (alias `next`) |
| `resume --profile NAME --source DIR` | Continue from first incomplete slot |
| `promote --source DIR [--out DIR] [--force]` | Copy Spec Kit + PRODUCT |
<!-- markdownlint-enable MD013 -->

## Defaults

<!-- markdownlint-disable MD013 -->
| Command | Default |
| --- | --- |
| `deps` | `core` unless `--profile`. An optional tool that is absent prints `skipped`; one that is broken prints `BROKEN` but does not fail the exit code |
| `doctor` | All profiles unless `--profile`. `--source` adds the deps of `--profile` (default `core`) and the readiness rows |
| `run`, `step` | New sidecar unless `--out` names one. With `--out`, files are added or overwritten |
| `status`, `resume`, `promote` | Latest sidecar under `<source>/.extract/` (by run id) unless `--out` |
| `status` profile | `MANIFEST.yaml` `source.profile` when `--profile` is omitted |
| `resume` | First slot that is not done, through the end or `--until` |
| `check` | Reads the sidecar only |
| `agent` | Latest sidecar under `<source>/.extract/` when `--source` is given; otherwise `--out` is required. `next` lists required tasks only; `show spec.enrich` runs the optional one |
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
| 1 | Refused (`error:` + `fix:`), `check` or `doctor` problems, required dep missing |
| 2 | Usage error: unknown command or flag |
| 130 | Interrupted |
<!-- markdownlint-enable MD013 -->

Bare `extractkit` and any `--help` print help and exit 0.

## Phases

The operator path and sidecar lineage are in [flow](flow.md).

`profiles/core.yaml` groups the pipeline into eight phases. Every profile
inherits them. `--from`, `--until` and `step` accept a phase id or number
as well as a slot or plugin id.

<!-- markdownlint-disable MD013 -->
| # | Phase | Slots or command |
| --- | --- | --- |
| 1 | `preflight` | `doctor` (command) |
| 2 | `static` | map.code, map.semantic, inventory.descriptors, inventory.controllers, inventory.templates, maps.normalize, inventory.integrations |
| 3 | `cms` | inventory.runtime, inventory.baseline (optional) |
| 4 | `merge` | maps.merge, rules.view, inventory.docs |
| 5 | `synthesis` | product.impeccable, docs.synthesize, use_cases, spec.kit, report.compat (optional) |
| 6 | `agent` | `agent` (command) |
| 7 | `check` | `check` (command) |
| 8 | `promote` | `promote` (command) |
<!-- markdownlint-enable MD013 -->

<!-- markdownlint-disable MD013 -->
| Token | Effect |
| --- | --- |
| `--from <phase>` | Start at the phase's first slot |
| `--until <phase>` | Stop after the phase's last slot |
| `step <phase>` | Run every slot of that phase |
| slot or plugin id | Single-slot meaning, as before |
<!-- markdownlint-enable MD013 -->

Phases 1, 6, 7 and 8 are commands. Passing them to `--from` / `--until` /
`step` is refused, with the command to run instead (`run --from agent` names
`extractkit agent next --out <sidecar>`).

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

A task is done when its `done` markers exist, or, for `rules.name`, when no
business rule in `rules/view-rules.json` is still `extracted`. The agent
phase is done when every required task is done. `spec.enrich` is optional
and never blocks it.

While a required task is pending, `status`, `run`, `step` and `resume` end
with `Agent is next` and `agent next`, plus `or skip to check`. `check`
validates `business/BUSINESS.md` only when it exists; a deterministic-only
run still passes.

## Other flags

`--tasks` writes Spec Kit `tasks.md` (off by default). Accepted by `run`,
`step` and `resume`. It only affects `spec.kit`.

| Flag | Effect |
| --- | --- |
| `-v`, `--verbose` | List every recorded action with its path |
| `-q`, `--quiet` | Suppress tips |

## Output

### Header

`run`, `step` and `resume` print the profile, the sidecar, and whether it
is new or existing.

### Slot rows

One `[N/8] <Phase>` block per phase touched. Each slot is a row: `✓` with
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

## Preflight

`doctor --source DIR` adds the target checkout to the profile check:

<!-- markdownlint-disable MD013 -->
| Row | Ready when | Missing |
| --- | --- | --- |
| `serena onboarding` | `.serena/project.yml` exists and `.serena/memories/` holds a `*.md` | exit 1; fix: open the source in an agent with Serena and run onboarding |
| `graphify index` | `graphify-out/graph.json` exists | exit 1; fix: run `/graphify .` in the source |
| `graft index` | `graft/` exists | warning only; fix: run `graft build` in the source |
<!-- markdownlint-enable MD013 -->

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

Optional files that are absent are not problems.

## Static vs full

A full `run` without `--until` includes CMS and needs `--branch` and
`--storage-state`.

```bash
./extractkit run --profile enonic --source ./legacy --until static
./extractkit run --profile enonic --source ./legacy --out <sidecar> \
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
