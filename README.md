# 99x Extract Kit

Extractkit reads a legacy checkout and writes a sidecar any later tool can
consume.

<!-- markdownlint-disable MD013 -->
| Profile | What it does |
| --- | --- |
| `enonic` | XP7 inventory, OpenAPI harvest, optional live CMS |
| `as` | `enonic` plus the Authentic Scandinavia `live_config` rules |
| `php` | Placeholder. `doctor` is green; `run` refuses with the todo list |
| `core` | Pipeline and phases only. No stack adapters |
<!-- markdownlint-enable MD013 -->

The sidecar stays under `<source>/.extract/<run-id>/`. `promote` copies as-is
Spec Kit files into the checkout. That is not an XP8 or React4XP port.

Every command writes on the first call. There is no dry run.

Docs: [flow](docs/flow.md), [CLI](docs/cli.md), [steps](docs/steps.md),
[profiles](docs/profiles.md), [output](docs/output.md).

## Install

Python 3.12+ with PyYAML and jsonschema (already on the reference box).

```bash
chmod +x ./extractkit
./extractkit --help
```

No bootstrap, no desktop forks, no writes into `~/.agents-profiles`.

## Commands

```bash
./extractkit profile list
./extractkit profile show enonic
./extractkit profile show php
./extractkit doctor --profile php          # empty PHP is allowed
./extractkit deps --profile enonic
./extractkit run --profile enonic --source /path/to/legacy --until static
./extractkit status --source /path/to/legacy
./extractkit resume --profile enonic --source /path/to/legacy
./extractkit check --out /path/to/legacy/.extract/<run-id>
./extractkit promote --source /path/to/legacy
```

## Sidecar

`run` writes `<source>/.extract/<run-id>/`.

## Next

Each run prints the phases it touched and ends with a `next` block: the
command to paste next. `status` (alias `next`) shows every phase as done,
current, or pending.

The path is in [flow](docs/flow.md). Flags, `-v` / `-q`, and the promote
guard are in [CLI](docs/cli.md).

![Operator path](docs/diagrams/operator-path.png)

## Source safety

The kit never edits the source `.gitignore` or `.git/`. A sidecar under
`<source>/.extract/` is self-ignored: `.extract/.gitignore` contains `*`. With
an `--out` outside the checkout a run writes nothing into the source.

## PHP

`./extractkit run --profile php --source …` exits non-zero with the
unfinished work list. It does not parse PHP.

## Static extract

Descriptors, maps, and OpenAPI only. A full Enonic run also surveys live
CMS and needs `--branch` and `--storage-state`.

```bash
./extractkit run --profile enonic --source /path/to/legacy --until static
```

Then merge, docs, and Spec Kit without CMS:

```bash
./extractkit run --profile enonic --source /path/to/legacy \
  --out /path/to/legacy/.extract/<run-id> \
  --from merge --until synthesis
```

`extractkit check` validates the sidecar. What it fails on is in
[CLI](docs/cli.md#check).

## Runtime CMS

`enonic.cms` surveys a local or review XP only. Production hosts are
refused.

Required: `--branch draft|master`, `--storage-state`, and a Guillotine URL
(`--guillotine`). Pin keys with `--cms-key`. Do not walk the tree.

```bash
./extractkit step enonic.cms --profile enonic --source /path/to/legacy \
  --out /path/to/legacy/.extract/<run-id> \
  --branch draft \
  --storage-state ~/.agents/.auth/xp7-localhost.json \
  --guillotine http://localhost:8080/admin/site/preview/en/draft \
  --cms-key /en
```

Survey rules and redaction are in
[steps](docs/steps.md#inventoryruntime-enoniccms). After CMS, `maps.merge`
updates page, layout, part, and macro status. The four values are in
[output](docs/output.md#surface-status).

## Baseline and XP8 report

Two optional slots add what a port needs beyond the descriptors. Neither
fails a run. A skip prints the command to run.

```bash
# desktop 1440 and mobile 390 screenshots, rendered HTML, network list
./extractkit step inventory.baseline --profile enonic --source /path/to/legacy \
  --out /path/to/legacy/.extract/<run-id> --branch draft \
  --storage-state ~/.agents/.auth/xp7-localhost.json

# factual XP7 to XP8 list, outside spec-kit/
./extractkit step report.compat --profile enonic --source /path/to/legacy \
  --out /path/to/legacy/.extract/<run-id>
```

`inventory.baseline` needs `playwright-cli` and the runtime pages. It
refuses production hosts. `--site-url` replaces the preview base URL.
`reports/xp8-compat.md` is never promoted.

## What the spec holds

`spec.md` states behavior from extracted facts only: fields, config
inputs, regions, controller calls with `file:line`, and the composition
runtime saw. Each FR has `Acceptance:` bullets and an `Evidence:` line.
`check` fails an FR without that line. A model may enrich the prose under
the contract in [the skill](skills/extract-legacy/SKILL.md).

## Promote

Explicit. Copies as-is Spec Kit constitution, PRODUCT, DESIGN, and
per-context `spec.md` into the checkout. It does not copy the sidecar into
git.

It refuses, writing nothing, when git cannot restore an existing
destination. `--force` overwrites. Paths and the guard are in
[output](docs/output.md#promote) and [CLI](docs/cli.md#promote-guard).

## Tests

```bash
python3 -m unittest discover -s tests
```

Fixtures: `tests/fixtures/enonic-mini/`. No GitLab CI in this kit.
