# CLI

Every command writes on the first call. Nothing needs a second run to
write.

Refusals print `error:` and a `fix:`. When the fix is a flag, the line is
your own command with that flag added.

## Commands

| Command | Role |
| --- | --- |
| `profile list` / `show NAME` | Inspect YAML types |
| `doctor [--profile NAME]` | Validate kit, composed profiles, and phases |
| `deps [--profile NAME]` | Binaries on PATH (`provides`) |
| `run --profile NAME --source DIR` | Pipeline; `--from` / `--until` |
| `step STEP --profile NAME --source DIR` | One phase or one slot |
| `check --out DIR` | Schema, coverage, `x-source`, spec FR |
| `status [--source DIR] [--out DIR]` | Phase checklist (alias `next`) |
| `resume --profile NAME --source DIR` | Continue from first incomplete slot |
| `promote --source DIR [--out DIR] [--force]` | Copy Spec Kit + PRODUCT |

## Defaults

<!-- markdownlint-disable MD013 -->
| Command | Default |
| --- | --- |
| `deps` | `core` unless `--profile`. Optional deps print `skipped` and never fail |
| `run`, `step` | New sidecar unless `--out` names one. With `--out`, files are added or overwritten |
| `status`, `resume`, `promote` | Latest sidecar under `<source>/.extract/` (by run id) unless `--out` |
| `status` profile | `MANIFEST.yaml` `source.profile` when `--profile` is omitted |
| `resume` | First slot that is not done, through the end or `--until` |
| `check` | Reads the sidecar only |
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

`profiles/core.yaml` groups the pipeline into seven phases. Every profile
inherits them. `--from`, `--until` and `step` accept a phase id or number
as well as a slot or plugin id.

<!-- markdownlint-disable MD013 -->
| # | Phase | Slots or command |
| --- | --- | --- |
| 1 | `preflight` | `doctor` (command) |
| 2 | `static` | map.code, map.semantic, inventory.descriptors, inventory.controllers, maps.normalize, inventory.integrations |
| 3 | `cms` | inventory.runtime, inventory.baseline (optional) |
| 4 | `merge` | maps.merge, inventory.docs |
| 5 | `synthesis` | product.impeccable, docs.synthesize, use_cases, spec.kit, report.compat (optional) |
| 6 | `check` | `check` (command) |
| 7 | `promote` | `promote` (command) |
<!-- markdownlint-enable MD013 -->

<!-- markdownlint-disable MD013 -->
| Token | Effect |
| --- | --- |
| `--from <phase>` | Start at the phase's first slot |
| `--until <phase>` | Stop after the phase's last slot |
| `step <phase>` | Run every slot of that phase |
| slot or plugin id | Single-slot meaning, as before |
<!-- markdownlint-enable MD013 -->

Phases 1, 6 and 7 are commands. Passing them to `--from` / `--until` /
`step` is refused, with the command to run instead.

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

One `[N/7] <Phase>` block per phase touched. Each slot is a row: `✓` with
up to three artifacts relative to the sidecar (then `+N more`), or `–`
with the skip reason. The body ends with `N files written`.

### Tips

At most two, and only when something triggers them: a skipped slot's fix,
or a row cut short (`Add -v to list every path.`).

### Next

Every successful command ends with a `next` block: the command to run
next, rebuilt from your flags and pinned to `--out <sidecar>`, plus an
`or` alternative where one exists (continue without CMS, or add CMS after
the offline route).

A value the kit cannot know stays as a placeholder such as
`<playwright-state.json>` or `<legacy-checkout>`.

Colour appears only on a TTY and when `NO_COLOR` is unset. Glyphs fall
back to `ok` / `skip` / `>` / `.` when stdout is not UTF-8.

Errors go to stderr as `error:` then
`fix:   $ <your command with the fix>` when a flag fixes it (with the
prose as `hint:`), or a prose `fix:` otherwise.

## CMS flags

`--branch draft|master` is required when `inventory.runtime` is in the
slice. `--storage-state` is required whenever `enonic.cms` runs.

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
  `inventory/content-volume.json`, the Enonic extras, or
  `map/bounded-contexts.json` exist and break their schema
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
