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
  inventory/runtime.json          # optional
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
| `inventory/runtime.json` | `runtime-inventory.schema.json` |
| `inventory/content-survey.json`, `content-survey-resolved.json`, `page-templates.json` | same-named `*.schema.json` |
| composed profiles | `profile.schema.json` |
<!-- markdownlint-enable MD013 -->

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

Only files present in the sidecar are copied. `promote` refuses when
there is nothing to copy.

## Surface status

Applies to `page`, `layout`, `part`, and `macro` when runtime exists.

| Status | Meaning |
| --- | --- |
| `live` | Seen in a runtime page's `templateOrder` |
| `dead` | Runtime exists and never saw it |
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
profiles do not produce them. `maps.merge` still only reads
`runtime.json` `pages[].templateOrder`.

```text
  inventory/content-survey.json
  inventory/content-survey.md
  inventory/content-survey-resolved.json
  inventory/content-survey-resolved.md
  inventory/page-templates.json
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
