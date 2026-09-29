# CLI

Dry-run is the default. `--apply` writes. Refusals name the fix.

## Commands

| Command | Role |
| --- | --- |
| `profile list` / `show NAME` | Inspect YAML types |
| `doctor [--profile NAME]` | Validate kit + composed profiles |
| `deps [--profile NAME]` | Binaries on PATH (`provides`) |
| `run --profile NAME --source DIR` | Pipeline; `--from` / `--until` |
| `step ID --profile NAME --source DIR` | One slot |
| `check --out DIR` | Schema, coverage, `x-source`, spec FR |
| `next [--source DIR] [--out DIR]` | Next step + skill + artifacts |
| `resume --profile NAME --source DIR` | Continue from that step |
| `promote --source DIR [--out DIR]` | Copy constitution / PRODUCT / specs |

## CMS flags (run / step / resume)

`--branch draft|master` is required when `inventory.runtime` is in the slice.
`--xp-host`, `--guillotine`, `--project`, `--storage-state`, `--cms-key`,
`--round2`, `--configenv`, `--allow-production` (unused in the DoD).

`--tasks` writes Spec Kit `tasks.md` (off by default).

## Static vs full

A full `run --apply` without `--until` includes CMS and needs `--branch`.

```bash
./extractkit run --profile enonic --source ./legacy --apply --until inventory.integrations
./extractkit run --profile enonic --source ./legacy --out <sidecar> --apply \
  --from maps.merge --until spec.kit
```

## Sidecar

Default `--out` is `<source>/.extract/<run-id>/`. `.extract/.gitignore` is `*`.
The kit never edits the source `.gitignore` or `.git/`.
