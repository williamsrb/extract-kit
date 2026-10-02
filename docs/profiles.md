# Profiles

Extractor types are YAML files under `profiles/`.
`extractkit profile show NAME` prints the composed result.

<!-- markdownlint-disable MD013 -->
| Profile | Role |
| --- | --- |
| `core` | Pipeline and phases. Stack adapters stay unbound |
| `enonic` | Extends `core`. Binds XP7 descriptors, integrations, CMS, docs |
| `as` | Extends `enonic`. Adds the Authentic Scandinavia `live_config` rules |
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
| `deps` | Entries with `provides` (binaries on PATH), `optional: true`, install hints `apt` / `dnf` / `pacman`, `probe` (argv list; exit 0 within 5 s is ok), `python_modules` (importable names) and `python` (a version bound such as `">=3.12"`). `core` declares `python3`, `git`, `graft`, `serena` and `graphify`; every profile inherits them. |
| `todo` | Unfinished work, printed when `run` refuses. |
| `optional_slots` | Slots that may stay unbound or empty without blocking `run`, `status` or `resume` (`inventory.baseline`, `report.compat`). |
| `cms` | Enonic CMS defaults (below). |
| `live_config` | Client rules for Site Config and Config Env endpoints (below). `{}` in `enonic`. |
| `round2` | Bounded contexts to survey a second time. |
| `exclude` | Source-relative folders or files every scan leaves out (lists extend the parent's). `--exclude` adds to it; see [CLI](cli.md#other-flags). `as` excludes `prototype` and `prototype-old`, which no default-branch build ships. |
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
3. `inventory.descriptors` — stack adapter (Enonic: descriptors, forms, regions)
4. `inventory.controllers` — controller facts with `file:line`
5. `maps.normalize` — static `map/*.json`
6. `inventory.integrations` — OpenAPI harvest + read-only Swagger UI
7. `inventory.runtime` — live CMS (Enonic: Guillotine + Site Config + Config Env)
8. `inventory.baseline` — optional screenshots, HTML, network list
9. `maps.merge` — runtime vs static, `bounded-contexts.json`, merge-report
10. `inventory.docs` — harvest source README/`docs/`
11. `product.impeccable` — as-is PRODUCT.md + DESIGN.md from maps
12. `docs.synthesize` — `docs/technical/` vs `docs/guide/`
13. `use_cases` — Given/When/Then journeys from extracted facts
14. `spec.kit` — as-is constitution + per-context `spec.md`
15. `report.compat` — optional XP8 compatibility facts

An unbound slot is dropped when the plugin of the same id is optional
(`map.code`, `map.semantic`) or the slot is in `optional_slots`
(`inventory.baseline`, `report.compat`). Any other unbound slot makes `run`
refuse with the `todo` list.

## Enonic

Binds `enonic.descriptors`, `enonic.controllers`, `enonic.integrations`,
`enonic.cms`, `enonic.baseline`, `enonic.docs`, `enonic.compat`.
Production hosts are refused.

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
| `configenv` | `--configenv` | `{host}` + `live_config.configenv_path`; none in `enonic`, so Config Env is skipped |
| `site_url` | `--site-url` | `{host}/admin/site/preview/{project}/{branch}` (baseline only) |
| `storage_state` | `--storage-state` | none; required |
| `sample_per_type` | — | `3` |
| `context_by_key` | — | map of content key → bounded context, used by `round2` |
<!-- markdownlint-enable MD013 -->

`--round2` values are added to the profile's `round2` list.

`enonic.cms` is where XP7 detection rules live (not core, not PHP):
`sample_per_type: 3`, `/_templates` folder order, and customized >
explicit `page.template` > implicit `data.supports`. See
[output](output.md#enonic-extras-not-a-phpcore-contract).

## live_config

Client rules for what Site Config and Config Env imply. The generic
adapter names no client; `profiles/as.yaml` holds today's values, and a
run under `--profile as` produces the same `runtime.json` endpoints as
before the split. A malformed table is refused with a fix.

<!-- markdownlint-disable MD013 -->
| Key | Meaning |
| --- | --- |
| `configenv_path` | Config Env tool path, appended to `{host}` when `--configenv` is absent |
| `site_url_keys` | Site Config leaf keys (case-insensitive) whose `http(s)` value is an endpoint |
| `hostmap_keys` | Config Env keys whose value is `/<path>=<host>,…`; also matched as a suffix |
| `providers` | Leaf substring (case-insensitive) → provider name, in order; no match uses the leaf |
| `env_endpoints` | List of rules: `provider`, `key` (leaf), optional `path` (substring of the full key), `origins` (value → origin), `default` origin, `urls` (suffixes appended to the origin; default one empty suffix) |
<!-- markdownlint-enable MD013 -->

A rule's `source` names the full key path when `path` is set, else the
`key` as written. Keys ending in `endpoint` are always kept as a generic
rule. Secrets are redacted before any rule runs.

## PHP

Empty placeholder. `todo` lists unfinished work. Adapters for
descriptors, controllers, integrations, runtime, and docs stay `null`.

- `run --profile php` refuses
- `doctor --profile php` is green
- `php` and `composer` are optional deps
- the core deps and the view-layer slots (`inventory.templates`,
  `rules.view`) are inherited

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
