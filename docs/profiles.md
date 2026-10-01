# Profiles

Extractor types are YAML files under `profiles/`.
`extractkit profile show NAME` prints the composed result.

<!-- markdownlint-disable MD013 -->
| Profile | Role |
| --- | --- |
| `core` | Pipeline and phases. Stack adapters stay unbound |
| `enonic` | Extends `core`. Binds XP7 descriptors, integrations, CMS, docs |
| `php` | Extends `core`. Placeholder. `run` refuses; `doctor` is green |
<!-- markdownlint-enable MD013 -->

## Keys

<!-- markdownlint-disable MD013 -->
| Key | Meaning |
| --- | --- |
| `name` | Required. Keep it equal to the file stem; commands look profiles up by file name. |
| `extends` | Parent profile name, or `null`. |
| `pipeline` | Ordered slot ids. |
| `phases` | `id`, `title`, and either `slots` (list) or `command` (`doctor`, `check`, `promote`). |
| `adapters` | Slot → plugin id, or `null` for unbound. |
| `deps` | Entries with `provides` (binaries on PATH), optional `optional: true`, and install hints `apt` / `dnf` / `pacman`. |
| `todo` | Unfinished work, printed when `run` refuses. |
| `cms` | Enonic CMS defaults (below). |
| `round2` | Bounded contexts to survey a second time. |
| `_comment` | Free text; ignored. |
<!-- markdownlint-enable MD013 -->

`schemas/profile.schema.json` validates the composed profile. Unknown keys
are allowed.

## Composition

Same algorithm as 99x-dev-kit `manifest.py`, ported for YAML:

- `extends` with loop detection
- lists (`pipeline`, `phases`, `deps`, `round2`) merge parent-first; a
  child item already in the parent is not repeated
- maps (`cms`) merge shallowly; the child's keys win
- child **replaces** `todo` and `adapters`
- `lineage` is added: the chain from root to the profile

Unknown adapter ids fail `extractkit doctor` / `profile show`. `doctor`
also checks the phases: every pipeline slot sits in exactly one phase, no
phase names an unknown slot, and no phase id repeats.

## Pipeline (core)

Each slot is described in [steps](steps.md). Phase grouping is in
[CLI](cli.md#phases). The operator path is in [flow](flow.md).

1. `map.code` — reuse source `graft/` or skip
2. `map.semantic` — reuse source `graphify-out/` or skip
3. `inventory.descriptors` — stack adapter (Enonic: FR-10 folders)
4. `maps.normalize` — static `map/*.json`
5. `inventory.integrations` — OpenAPI harvest + read-only Swagger UI
6. `inventory.runtime` — live CMS (Enonic: Guillotine + Site Config + Config Env)
7. `maps.merge` — runtime vs static, `bounded-contexts.json`, merge-report
8. `inventory.docs` — harvest source README/`docs/`
9. `product.impeccable` — as-is PRODUCT.md + DESIGN.md from maps
10. `docs.synthesize` — `docs/technical/` vs `docs/guide/`
11. `use_cases` — one markdown file per bounded context
12. `spec.kit` — as-is constitution + per-context `spec.md`

An unbound slot is dropped when the plugin of the same id is optional
(`map.code`, `map.semantic`). Any other unbound slot makes `run` refuse
with the `todo` list.

## Enonic

Binds `enonic.descriptors`, `enonic.integrations`, `enonic.cms`,
`enonic.docs`. Production hosts are refused.

`cms` keys. A CLI flag beats the profile key; the profile key beats the
built-in default.

<!-- markdownlint-disable MD013 -->
| Key | Flag | Default |
| --- | --- | --- |
| `host` | `--xp-host` | `http://localhost:8080` |
| `project` | `--project` | `en` in `enonic.yaml` |
| `branch` | `--branch` | none; required |
| `guillotine` | `--guillotine` | `{host}/admin/site/preview/{project}/{branch}` |
| `keys` | `--cms-key` | `[/en]` in `enonic.yaml` |
| `site_key` | — | used when `keys` is empty |
| `configenv` | `--configenv` | `{host}/admin/tool/no.seeds.configenv/module-config` |
| `storage_state` | `--storage-state` | none; required |
| `sample_per_type` | — | `3` |
| `context_by_key` | — | map of content key → bounded context, used by `round2` |
<!-- markdownlint-enable MD013 -->

`--round2` values are added to the profile's `round2` list.

`enonic.cms` is where XP7 detection rules live (not core, not PHP):
`sample_per_type: 3`, `/_templates` folder order, and customized >
explicit `page.template` > implicit `data.supports`. See
[output](output.md#enonic-extras-not-a-phpcore-contract).

## PHP

Empty placeholder. `todo` lists unfinished work. Adapters for
descriptors, integrations, runtime, and docs stay `null`.

- `run --profile php` refuses
- `doctor --profile php` is green
- `php` and `composer` are optional deps

## Adding a profile or adapter

Step 1: Add `profiles/<name>.yaml` with `extends: core` and its
`adapters`.

Step 2: A new plugin is a class with `id`, `requires`, `produces`,
`required`, and `plan(ctx)`, `run(ctx)`, `check(ctx)` (see
`extractkit_cli/registry.py` `Step`). Register it in `registry._load()`.

Step 3: Write through `ctx.write_text` / `write_json` / `write_yaml` so
the run output lists the file. Call
`ctx.record_skip(step, reason, fix)` instead of failing when an optional
input is missing.

Step 4: `status` and `resume` treat the plugin as done when every path in
`produces` exists, unless `extractkit_cli/progress.py` `DISTINCTIVE`
lists narrower markers.
