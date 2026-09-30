# CLI

Every command does its job on the first call; nothing needs a second run to
write. Refusals name the fix, and flag fixes repeat your own command.

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

## Phases

`profiles/core.yaml` groups the pipeline into seven phases. Every profile
inherits them. `--from`, `--until` and `step` accept a phase id or number as
well as a slot or plugin id.

<!-- markdownlint-disable MD013 -->
| # | Phase | Slots or command |
| --- | --- | --- |
| 1 | `preflight` | `doctor` (command) |
| 2 | `static` | map.code, map.semantic, inventory.descriptors, maps.normalize, inventory.integrations |
| 3 | `cms` | inventory.runtime |
| 4 | `merge` | maps.merge, inventory.docs |
| 5 | `synthesis` | product.impeccable, docs.synthesize, use_cases, spec.kit |
| 6 | `check` | `check` (command) |
| 7 | `promote` | `promote` (command) |
<!-- markdownlint-enable MD013 -->

`--from <phase>` starts at the phase's first slot. `--until <phase>` stops after
its last slot. `step <phase>` runs every slot of that phase. A slot id keeps its
single-slot meaning. Phases 1, 6 and 7 are commands; passing them to
`--from` / `--until` / `step` is refused with the command to run instead.

## Output

`run`, `step` and `resume` print a header (profile, sidecar, new or existing),
one `[N/7] <Phase>` block per phase touched, and a row per slot: `✓` with up to
three artifacts relative to the sidecar (then `+N more`), or `–` with the skip
reason. The body ends with `N files written`.

At most two tips follow, only when something triggers them: a skipped slot's
fix, or a row cut short (`Add -v to list every path.`).

Every successful command ends with a `next` block: the command to run next,
rebuilt from your own flags and pinned to `--out <sidecar>`, plus an `or`
alternative where one exists (continue without CMS, or add CMS after the
offline route). A value the kit cannot know stays as a placeholder such as
`<playwright-state.json>` or `<legacy-checkout>`.

| Flag | Effect |
| --- | --- |
| `-v`, `--verbose` | List every recorded action with its path |
| `-q`, `--quiet` | Suppress tips |

Colour appears only on a TTY and when `NO_COLOR` is unset. Glyphs fall back to
`ok` / `skip` / `>` / `.` when stdout is not UTF-8.

Errors go to stderr as `error:` then `fix:   $ <your command with the fix>`
when a flag fixes it (with the prose as `hint:`), or a prose `fix:` otherwise.

## CMS flags (run / step / resume)

`--branch draft|master` is required when `inventory.runtime` is in the slice.
`--storage-state` is required whenever `enonic.cms` runs.
`--xp-host`, `--guillotine`, `--project`, `--cms-key`,
`--round2`, `--configenv`, `--allow-production` (unused in the DoD).

`--cms-key` pins Site Config harvest. Enonic also samples
`cms.sample_per_type` (default 3) contents per type without walking the
tree.

`--tasks` writes Spec Kit `tasks.md` (off by default).

## Static vs full

A full `run` without `--until` includes CMS and needs `--branch` and
`--storage-state`.

```bash
./extractkit run --profile enonic --source ./legacy --until static
./extractkit run --profile enonic --source ./legacy --out <sidecar> \
  --from merge --until synthesis
```

## Promote guard

`promote` writes into the legacy checkout on the first call, so it refuses the
whole promote, writing nothing, when an existing destination is modified,
staged, untracked or ignored, or when the source is not a git work tree.
Tracked, clean destinations are overwritten (git can restore them).
Destinations that do not exist are always written. `--force` skips the check.

## Sidecar

Default `--out` is `<source>/.extract/<run-id>/`. `.extract/.gitignore` is `*`.
The kit never edits the source `.gitignore` or `.git/`.
