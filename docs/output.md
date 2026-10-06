# Output contract

Canonical extract tree. Enonic details live only under `stackRef`.

```text
<out>/
  MANIFEST.yaml
  map/project-map.json
  map/component-map.json
  map/content-model.json
  map/route-map.json
  map/bounded-contexts.json
  inventory/static.json
  inventory/controllers.json
  inventory/templates.json
  context/build-scope.json
  context/profile.yaml            # overlay: exclude and live_config
  inventory/runtime.json          # optional
  inventory/live-config-candidates.json  # optional, with runtime
  inventory/content-volume.json   # optional, with runtime
  inventory/content-volume.md     # optional, with runtime
  baseline/INDEX.md               # optional
  baseline/<slug>/                # desktop.png, mobile.png, page.html, network.json
  reports/xp8-compat.md           # optional; never promoted
  reports/spec-review.md          # optional; never promoted
  inventory/merge-report.md
  rules/view-rules.json
  rules/RULES.md
  rules/literals.md
  rules/review.md
  product/PRODUCT.md
  design/DESIGN.md
  design/design.json
  docs/harvest/
  docs/technical/
  docs/guide/
  use-cases/<context>.md
  business/BUSINESS.md            # agent task `business`
  integrations/openapi.yaml
  integrations/swagger-ui/        # read-only Swagger UI; Try it out disabled
  spec-kit/constitution.md        # composed by spec.kit
  spec-kit/constitution/project.md   # agent task `constitution`
  spec-kit/specs/<context>/spec.md
  spec-kit/specs/<context>/tasks.md   # only with --tasks
  hygiene/dead-code.md
```

Which step writes each file is in [steps](steps.md). How those files move
from checkout to sidecar to promote is in [flow](flow.md).

## MANIFEST.yaml

Rewritten at the end of every `run`, `step` and `resume`:

- `schema`: `99x.extract.manifest/v1`
- `run_id`: sidecar directory name (UTC timestamp)
- `source`: `path`, git `sha` and `dirty` (null / false outside git),
  `profile`, `lineage`, and `tools` (extractkit and Python versions)
- `maps`: `code` / `semantic` / `serena` pointers to reused source indexes, or null
- `exclude`: source-relative paths every scan left out (profile `exclude:`
  plus `--exclude`); kept by later runs on the same sidecar
- `context`: `layers`, the overlay files composed on top of the stack
  profile (`context/profile.yaml`, and the operator's
  `<source>/.extractkit/profile.yaml` when it exists)
- `skips`: `step`, `reason`, `fix` for each slot skipped in that run

## Schemas

`schemas/` holds JSON Schema 2020-12 files. Every map surface uses
`surface.schema.json`.

<!-- markdownlint-disable MD013 -->
| File | Schema |
| --- | --- |
| `MANIFEST.yaml` | `manifest.schema.json` |
| `map/project-map.json`, `component-map.json`, `content-model.json`, `route-map.json` | same-named `*.schema.json` |
| `map/bounded-contexts.json` | `bounded-contexts.schema.json` |
| `inventory/static.json` | `inventory.schema.json` |
| `inventory/controllers.json` | `controllers.schema.json` |
| `inventory/templates.json` | `templates.schema.json` |
| `rules/view-rules.json` | `view-rules.schema.json` |
| `inventory/runtime.json` | `runtime-inventory.schema.json` |
| `inventory/content-volume.json` | `content-volume.schema.json` |
| `inventory/content-survey.json`, `content-survey-resolved.json`, `page-templates.json` | same-named `*.schema.json` |
| composed profiles | `profile.schema.json` |
<!-- markdownlint-enable MD013 -->

## Surface fields

Optional properties of a surface, all additive inside `/v1`. Each field
object is defined once per schema file as `$defs.field`; a test keeps the
copies identical.

<!-- markdownlint-disable MD013 -->
| Property | On | Content |
| --- | --- | --- |
| `fields` | content-type, mixin, x-data | Inputs: `name`, `type`, `label`, `occurrences {min,max}`, `config`, `fromMixin`, `fieldSet`, `items`, `options`, `selection`; an unresolved mixin is `{mixin}` |
| `config` | page, layout, part, macro, task | Same field objects, for the component form |
| `regions` | page, layout | Region names |
| `behavior` | any surface with a controller | `file`, `imports`, `calls`, `queries`, `methods`, `views`, `i18n`, `configKeys`, `listeners`, each item with `line` |
| `template` | page, layout, part, macro, component, partial | `engine`, `framework`, `file`, `inputs`, `children` (`surface` id or null, `status`), `slots`, `outputs`, `logic`, `i18n`, `assets`, `dom`, `dataSource`; each item with `line` |
| `configKeys`, `listeners` | `site` | Names the app's controllers read or listen for |
| `usage` | page, layout, part | Guillotine count when the probe answered |
<!-- markdownlint-enable MD013 -->

`map/content-model.json` also holds `references`: `{from, field, to[]}`
for each content-selector field.

## View-layer files

- `inventory/templates.json`: `engines[]` (confidence, `path:line` signals),
  `files[]` (one per template or view script, with its full `scan`),
  `controllers[]` (render-controller predicates) and `coverage` (files
  scanned, skipped with reason, excluded folders: the skip folders plus the
  run's `exclude`)
- `rules/view-rules.json`: `rules[]` (`id`, `kind`, `bucket`, `score` and
  `signals`, `expression`, `shape`, `operands`, `literals`, `component`,
  `source`, `repeated`, `divergent`, `status`), `groups[]` and `removed[]`.
  Rule `status` is `extracted` (kit), `named` (agent wrote `name` and
  `intent`) or `confirmed` (analyst ticked it)
- `rules/RULES.md`, `rules/literals.md`: the readable views
- `rules/review.md`: the only file in `rules/` a person or agent edits

## BUSINESS.md

`business/BUSINESS.md` is written by the `business` agent task. It has the
H2 sections Purpose and audience, Actors, Capabilities, Business flow,
Business rules by capability, Glossary, Integrations and Open questions.
`check` validates it only when it exists: every section is present, every
`Evidence:` ref resolves (a source `path:line`, a map id, a context id or a
rule id), every capability cites a rule id or a surface id, and every
`_(inferred)_` paragraph has an `Evidence:` line.

## Constitution

`spec-kit/constitution/project.md` is written by the `constitution` agent
task. It has the H2 sections Product, Stack, Architecture, Conventions,
Integrations, Delivery, Invariants and Open questions, under the same
evidence contract as `BUSINESS.md`; every section but Open questions has an
`Evidence:` line. `spec.kit` composes `spec-kit/constitution.md` from it: a
title, the project sections (or a note that the task has not run), then a
Governance section that marks the extract as as-is. A re-run of `spec.kit`
keeps the project part.

## PRODUCT.md

`product/PRODUCT.md` is written by `product.impeccable`. Once
`business/BUSINESS.md` exists it takes Users and jobs (Purpose and audience,
Actors) and the capability outline from it; the `business` task re-runs the
step. The surfaces from the maps are a count per kind and status.

## Spec review

`reports/spec-review.md` is written by the optional `spec.review` agent
task. It never edits the specs and `promote` never copies it. `check`
validates it only when it exists: the H1 `# Spec review`, then either
`No findings.` or findings whose `### SR-<n>` block has `Spec:` (a
`spec-kit/specs/<slug>/spec.md` in the sidecar), `Severity:` (`high`,
`medium` or `low`), `Fix in:` (`extractor`, `rules/review.md`,
`spec.enrich` or `source`) and `Evidence:` (every ref resolves like in
`BUSINESS.md`). The FR id after a `Spec:` path is not validated, and the
findings never fail `check`.

## Hygiene

`hygiene/dead-code.md` is report-only. The kit never deletes source.
`check` accepts a descriptor named there as covered.

## Promote

`extractkit promote` maps the files below. It refuses, writing nothing,
when an existing destination holds changes git cannot restore (modified,
staged, untracked, ignored, or a source outside git). `--force`
overwrites anyway.

- `spec-kit/constitution.md` → `.specify/memory/constitution.md`
- `spec-kit/specs/<ctx>/spec.md` → `specs/<ctx>/spec.md`
- `product/PRODUCT.md` → `PRODUCT.md`
- `design/DESIGN.md` → `DESIGN.md`
- `design/design.json` → `.impeccable/design.json`
- `business/BUSINESS.md` → `BUSINESS.md` (a promote row declared by the
  `business` agent task in `agent-tasks/business/task.yaml`; every task's
  `promote` rows are added to this list)

`baseline/`, `reports/` and `inventory/` are never promoted. Only files
present in the sidecar are copied. `promote` refuses when there is nothing
to copy.

## Surface status

Applies to `page`, `layout`, `part`, and `macro` when runtime exists.

<!-- markdownlint-disable MD013 -->
| Status | Meaning |
| --- | --- |
| `live` | Seen in a runtime page's `templateOrder`, or the usage probe counted more than 0 (evidence `usage:<app>:<kind>:<name>:<n>`) |
| `dead` | Not seen, and the usage probe counted exactly 0 |
| `unobserved` | Not seen, and no count: the probe was unsupported, or the kind has no indexed field (macro). It is not `dead`; a port should keep it |
| `conditional` | Seen in round 1, absent in round 2 |
| `unverified-live` | No runtime, or any other kind |
<!-- markdownlint-enable MD013 -->

<!-- markdownlint-disable MD013 -->
| Rule | Winner |
| --- | --- |
| Runtime vs static | Runtime |
| Round 2 vs round 1 | Round 2 |
<!-- markdownlint-enable MD013 -->

Contradictions stay in the merge report. The rules are in
[steps](steps.md#mapsmerge).

## As-is

No `PLAN.md`, `DECISIONS.md`, or `IMPLEMENTATION.md` in this tree. Mode
is as-is, not an XP8 port.

## Enonic extras (not a PHP/core contract)

`enonic.cms` also writes XP7-only files next to `runtime.json`. Other
profiles do not produce them. `maps.merge` reads
`runtime.json` `pages[].templateOrder`, `usage` and `usageProbe`.

```text
  inventory/content-survey.json
  inventory/content-survey.md
  inventory/content-survey-resolved.json
  inventory/content-survey-resolved.md
  inventory/page-templates.json
  inventory/content-volume.json
  inventory/content-volume.md
```

Detection rules live in `steps/enonic/page_templates.py`:

- Sample **3** contents per type (`cms.sample_per_type`, Guillotine
  `queryConnection` `first=N`). That is not a tree walk (FR-14).
- Site Config REST stays on `--cms-key` pins.
- Page resolve order: customized `pageAsJson` (descriptor/regions, no
  `page.template`) > explicit `pageAsJson.template` > implicit first
  `/_templates` child whose `data.supports` lists the content type
  (folder order). A catch-all last in the folder loses to an earlier
  match.
- Guillotine `pageTemplate` is already resolved; the kit does not treat
  it as the editor field.
