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
  inventory/runtime.json          # optional
  inventory/content-volume.json   # optional, with runtime
  inventory/content-volume.md     # optional, with runtime
  baseline/INDEX.md               # optional
  baseline/<slug>/                # desktop.png, mobile.png, page.html, network.json
  reports/xp8-compat.md           # optional; never promoted
  inventory/merge-report.md
  product/PRODUCT.md
  design/DESIGN.md
  design/design.json
  docs/harvest/
  docs/technical/
  docs/guide/
  use-cases/<context>.md
  integrations/openapi.yaml
  integrations/swagger-ui/        # read-only Swagger UI; Try it out disabled
  spec-kit/constitution.md
  spec-kit/constitution/          # optional fragments
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
- `maps`: `code` / `semantic` pointers to reused source indexes, or null
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
| `configKeys`, `listeners` | `site` | Names the app's controllers read or listen for |
| `usage` | page, layout, part | Guillotine count when the probe answered |
<!-- markdownlint-enable MD013 -->

`map/content-model.json` also holds `references`: `{from, field, to[]}`
for each content-selector field.

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

`baseline/`, `reports/` and `inventory/` are never promoted. Only files
present in the sidecar are copied. `promote` refuses when there is nothing
to copy.

## Surface status

Applies to `page`, `layout`, `part`, and `macro` when runtime exists.

| Status | Meaning |
| --- | --- |
| `live` | Seen in a runtime page's `templateOrder`, or the usage probe counted more than 0 (evidence `usage:<app>:<kind>:<name>:<n>`) |
| `dead` | Not seen, and the usage probe counted exactly 0 |
| `unobserved` | Not seen, and no count: the probe was unsupported, or the kind has no indexed field (macro). It is not `dead`; a port should keep it |
| `conditional` | Seen in round 1, absent in round 2 |
| `unverified-live` | No runtime, or any other kind |

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
