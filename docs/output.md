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
  integrations/swagger-ui/
  spec-kit/constitution.md
  spec-kit/constitution/          # optional fragments
  spec-kit/specs/<context>/spec.md
  spec-kit/specs/<context>/tasks.md   # only with --tasks
  hygiene/dead-code.md
```

`extractkit promote --apply` maps:

- `spec-kit/constitution.md` → `.specify/memory/constitution.md`
- `spec-kit/specs/<ctx>/spec.md` → `specs/<ctx>/spec.md`
- `product/PRODUCT.md` → `PRODUCT.md`
- `design/DESIGN.md` → `DESIGN.md`
- `design/design.json` → `.impeccable/design.json`

Status on surfaces: `live` | `dead` | `conditional` | `unverified-live`.
Runtime beats static. Round 2 beats round 1. Contradictions stay in the merge report.

No `PLAN.md`, `DECISIONS.md`, or `IMPLEMENTATION.md` in this tree. Mode is as-is.
