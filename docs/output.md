# Output contract

Canonical extract tree (stack-agnostic). Enonic details live only under `stackRef`.

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

`extractkit promote` maps the files below. It refuses, writing nothing, when an
existing destination holds changes git cannot restore (modified, staged,
untracked, ignored, or a source outside git). `--force` overwrites anyway.

- `spec-kit/constitution.md` → `.specify/memory/constitution.md`
- `spec-kit/specs/<ctx>/spec.md` → `specs/<ctx>/spec.md`
- `product/PRODUCT.md` → `PRODUCT.md`
- `design/DESIGN.md` → `DESIGN.md`
- `design/design.json` → `.impeccable/design.json`

Status on surfaces: `live` | `dead` | `conditional` | `unverified-live`.
Runtime beats static. Round 2 beats round 1. Contradictions stay in the merge report.

No `PLAN.md`, `DECISIONS.md`, or `IMPLEMENTATION.md` in this tree. Mode is as-is.

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
