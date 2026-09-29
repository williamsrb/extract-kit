# Profiles

Extractor types are YAML files under `profiles/`. `core` declares the pipeline
and leaves stack adapters unbound. `enonic` and `php` extend core.

## Composition

Same algorithm as 99x-dev-kit `manifest.py`, ported for YAML:

- `extends` with loop detection
- parent-first list merge (`pipeline`, `deps`)
- child **replaces** `todo` and `adapters`

Unknown adapter ids fail `extractkit doctor` / `profile show`.

## Pipeline (core)

1. `map.code` — reuse source `graft/` or skip
2. `map.semantic` — reuse source `graphify-out/` or skip
3. `inventory.descriptors` — stack adapter (Enonic: FR-10 folders)
4. `maps.normalize` — static `map/*.json`
5. `inventory.integrations` — OpenAPI harvest
6. `inventory.runtime` — live CMS (Enonic: Guillotine + Site Config + Config Env)
7. `maps.merge` — runtime vs static, `bounded-contexts.json`, merge-report
8. `inventory.docs` — harvest source README/`docs/`
9. `product.impeccable` — as-is PRODUCT.md + DESIGN.md from maps
10. `docs.synthesize` — `docs/technical/` vs `docs/guide/`
11. `use_cases` — one markdown file per bounded context
12. `spec.kit` — as-is constitution + per-context `spec.md`

## Enonic

Binds `enonic.descriptors`, `enonic.integrations`, `enonic.cms`, `enonic.docs`.
Default CMS host is `http://localhost:8080`. Production hosts are refused.

## PHP

Empty placeholder. `todo` lists unfinished work. Adapters for descriptors,
integrations, runtime, and docs stay `null`. `run --profile php` refuses.
`doctor --profile php` is green.
