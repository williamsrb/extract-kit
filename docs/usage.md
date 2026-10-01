# Usage

How to run extractkit. For what the kit is and what it produces, start with
the [README](../README.md).

The output folder is called the **sidecar**: a run writes it to
`<source>/.extract/<run-id>/`, next to the legacy project (the **checkout**,
a local clone of its repository). `promote` copies as-is Spec Kit files into
the checkout. That is not an XP8 or React4XP port.

<!-- markdownlint-disable MD013 -->
| Profile | What it does |
| --- | --- |
| `enonic` | XP7 inventory, OpenAPI harvest, optional live CMS |
| `as` | `enonic` plus the Authentic Scandinavia `live_config` rules |
| `php` | Placeholder. `doctor` is green; `run` refuses with the todo list |
| `core` | Pipeline and phases only. No stack adapters |
<!-- markdownlint-enable MD013 -->

Every command writes on the first call. There is no dry run.

Agents: read [llm.md](llm.md) first. It is the instruction set for driving
the kit and for the rule-naming step.

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
./extractkit doctor --profile enonic --source /path/to/legacy  # + readiness
./extractkit deps --profile enonic         # runs each probe
./extractkit run --profile enonic --source /path/to/legacy --until static
./extractkit status --source /path/to/legacy
./extractkit resume --profile enonic --source /path/to/legacy
./extractkit agent next --out /path/to/legacy/.extract/<run-id>
./extractkit check --out /path/to/legacy/.extract/<run-id>
./extractkit promote --source /path/to/legacy
```

## Next

Each run prints the phases it touched and ends with a `next` block: the
command to paste next. `status` (alias `next`) shows every phase as done,
current, or pending.

After synthesis, `next` points at `extractkit agent next` while a required
agent task is pending. Agent tasks are prompts stored in `agent-tasks/`:
they name the view-layer rules and write `BUSINESS.md`. The kit never calls
a model; the `extract-agentic` skill runs them.

The path is in [flow](flow.md). Flags, `-v` / `-q`, and the promote
guard are in [CLI](cli.md).

![Operator path](diagrams/operator-path.png)

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
[CLI](cli.md#check).

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
[steps](steps.md#inventoryruntime-enoniccms). After CMS, `maps.merge`
updates page, layout, part, and macro status. The four values are in
[output](output.md#surface-status).

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

## View layer

Every profile also inventories the view layer. `inventory.templates` detects
FreeMarker, Thymeleaf, Mustache, Handlebars, Pebble, React, Next.js,
Angular, Vue and jQuery, and `maps.normalize` maps each template file into a
spec-ready `component` or `partial` surface (inputs, children, slots,
outputs, data source) without converting any code. `rules.view` then
harvests the business rules hidden in templates and view scripts, scores
them, flags rules that are repeated or that diverge between files, and
writes `rules/`. The kit extracts; the agent names the rules; an analyst
confirms them. Details: [steps](steps.md#inventorytemplates-coretemplates),
[rule naming](llm.md#6-agent).

## What the spec holds

`spec.md` states behavior from extracted facts only: fields, config
inputs, regions, controller calls with `file:line`, and the composition
runtime saw. Each FR has `Acceptance:` bullets and an `Evidence:` line.
`check` fails an FR without that line. A model may enrich the prose under
the contract in `extractkit agent show spec.enrich` (run by the
[extract-agentic skill](../skills/extract-agentic/SKILL.md)).

## Promote

Explicit. Copies as-is Spec Kit constitution, PRODUCT, DESIGN, `BUSINESS.md`
when present, and per-context `spec.md` into the checkout. It does not copy
the sidecar into git.

It refuses, writing nothing, when git cannot restore an existing
destination. `--force` overwrites. Paths and the guard are in
[output](output.md#promote) and [CLI](cli.md#promote-guard).

## Tests

```bash
python3 -m unittest discover -s tests
```

Fixtures: `tests/fixtures/enonic-mini/` and `tests/fixtures/templates-mini/`.
No GitLab CI in this kit.
