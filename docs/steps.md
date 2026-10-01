# Steps

One section per pipeline slot, in pipeline order. Each names the plugin
the Enonic profile binds, what it reads, what it writes, and when
`status` / `resume` count it as done.

Paths are relative to the sidecar unless they say `<source>`. The command
path and file lineage are in [flow](flow.md).

A slot counts as **done** when its marker artifacts exist in the sidecar.
`status` and `resume` use only these markers, so deleting a file re-opens
its slot.

<!-- markdownlint-disable MD013 -->
| Phase | Slot | Enonic plugin | Done when present |
| --- | --- | --- | --- |
| static | `map.code` | `map.code` | always (optional) |
| static | `map.semantic` | `map.semantic` | always (optional) |
| static | `inventory.descriptors` | `enonic.descriptors` | `inventory/static.json` |
| static | `maps.normalize` | `maps.normalize` | the four `map/*-map.json` / `content-model.json` files |
| static | `inventory.integrations` | `enonic.integrations` | `integrations/openapi.yaml`, `integrations/swagger-ui/` |
| cms | `inventory.runtime` | `enonic.cms` | `inventory/runtime.json` |
| merge | `maps.merge` | `maps.merge` | `map/bounded-contexts.json`, `inventory/merge-report.md` |
| merge | `inventory.docs` | `enonic.docs` | `docs/harvest/INDEX.md` |
| synthesis | `product.impeccable` | `product.impeccable` | `product/PRODUCT.md`, `design/DESIGN.md` |
| synthesis | `docs.synthesize` | `docs.synthesize` | `docs/technical/overview.md`, `docs/guide/overview.md` |
| synthesis | `use_cases` | `use_cases` | a non-empty `use-cases/` |
| synthesis | `spec.kit` | `spec.kit` | `spec-kit/constitution.md` |
<!-- markdownlint-enable MD013 -->

Every run, whatever its slice, also rewrites `MANIFEST.yaml` and
`hygiene/dead-code.md` (see [output](output.md)).

## map.code

**Does.** Reuses an existing `<source>/graft/` index. Records its path
under `MANIFEST.yaml` `maps.code`. It never runs graft.

**Skip.** Without the folder, the slot is skipped with the tip
`run graft build in <source> yourself`. Optional: a skip does not fail
the run.

## map.semantic

**Does.** Same contract for `<source>/graphify-out/` (`maps.semantic`).
It never runs graphify.

**Skip.** Optional, same as `map.code`.

## inventory.descriptors (`enonic.descriptors`)

**Does.** Static XP7 inventory from disk. No XP runtime. Scans every
`src/main/resources` directory under the source and records:

- `site/site.xml` (kind `site`)
- `site/content-types`, `site/mixins`, `site/x-data`, `site/pages`,
  `site/layouts`, `site/parts`, `site/macros`
- sibling `services/` and `tasks/` (beside `site/`, not under it)

A descriptor is `<name>/<name>.xml`, or every `*.xml` in a folder without
one. The display name comes from `<display-name>`, then `<description>`,
then the file stem. The app name comes from the nearest
`gradle.properties` (`appName`, else `group.projectName`), else
`unknown`.

Out of scope in v1: `admin/`, `site/filters/`, `site/processors/`,
`site/error/`.

**Writes.** `inventory/static.json`. `check` uses it for FR-10 descriptor
coverage.

## maps.normalize

**Does.** Turns `inventory/static.json` into stack-agnostic surfaces.
Each resource becomes one surface with id `<app>:<kind>:<name>`, status
`unverified-live`, and the Enonic path under `stackRef.enonic`.
`site.xml` `<mapping>` entries become `mapping` routes.

**Writes.**

- `map/project-map.json`: every surface
- `map/component-map.json`: `page`, `layout`, `part`, `macro`
- `map/content-model.json`: `content-type`, `mixin`, `x-data`
- `map/route-map.json`: `service`, `task`, `site`, `mapping`

**Skip.** Without `inventory/static.json` (for example `step
maps.normalize` on an empty sidecar) it re-scans the source.

## inventory.integrations (`enonic.integrations`)

**Does.** Static harvest into a field-minimal OpenAPI 3.1 document. Three
directions, each operation carrying `x-source` (`file:line`) and
`x-direction`:

- `inbound`: every XP service, as `POST /_/service/<app>/<name>`
- `outbound`: every `.js` / `.es6` / `.ts` file that imports
  `/lib/http-client`, as `POST /outbound/<file-stem>`
- `browser-embed`: every `<script src="http(s)://…">` in HTML under a
  `site` folder (commented lines skipped), as
  `GET /browser-embed/<slug>` with `x-embed-url`

**Writes.** `integrations/openapi.yaml` and a read-only Swagger UI in
`integrations/swagger-ui/` (`swagger-ui-dist` 5.30.2, copied from
`templates/swagger-ui/`).

Try it out is disabled. The spec is inlined in `spec.js` so `index.html`
opens from `file://`.

## inventory.runtime (`enonic.cms`)

**Does.** Live survey of a local or review XP7. Flags and defaults are in
[CLI](cli.md#cms-flags).

**Refuse.** A missing branch, content key or Guillotine URL, or a
production host, is refused before any slot of the run writes. A missing
or cookie-less storage-state is refused when this step starts.

### Transport

HTTP with cookies from the Playwright storage-state file.

### Survey

1. Load the `/_templates` folder under the first content key.
2. Sample `cms.sample_per_type` (default 3) contents per static content
   type with Guillotine `queryConnection` (`first=N`). No tree walk.
3. Fetch every `--cms-key` page (round 1). Keys whose context is listed
   in `--round2` / `round2` are fetched again as round 2. The context of
   a key comes from `cms.context_by_key`.
4. Resolve each page's template: customized > explicit `page.template` >
   implicit `data.supports` in `/_templates` folder order.
5. Read Site Config (Content Studio REST) for the pinned keys only, and
   the Config Env table (`--configenv`).

### Redaction

A field is dropped when its last segment contains `password`, `token`,
`secret` or `apikey`, or ends in `key`, `token`, `password` or `user`.
Site Config lists them under `redacted`. Config Env keeps the key with
`redacted: true` and no value.

### HTTP outcomes

- 401/403: refuse, with a fix to mint a fresh storage-state
- Site Config 404: skip that key
- Config Env 404/405/501: treat as "app not installed" and skip
- any other non-200: refuse

**Writes.** `inventory/runtime.json` and the Enonic extras listed in
[output](output.md#enonic-extras-not-a-phpcore-contract). Live provider
URLs go to `runtime.json` `endpoints` and are merged into
`integrations/openapi.yaml` `x-production-endpoints` (and `spec.js`).
Those URLs are never fetched.

## maps.merge

**Does.** Runtime beats static. Reads `map/project-map.json` (running
`maps.normalize` first if it is missing) and the optional
`inventory/runtime.json`.

Surface status, for `page`, `layout`, `part` and `macro` only:

- `live`: seen in a runtime page's `templateOrder`; `composition` is
  taken from the highest-round page that lists it
- `dead`: runtime exists and never saw it
- `conditional`: seen in round 1, absent in round 2; also listed as a
  contradiction
- `unverified-live`: no runtime, or any other kind

Seen surfaces get an evidence ref `runtime:<app>:<name>:r<round>`.

Bounded contexts, each emitted only when non-empty:

- `presentation`: page, layout, part, macro
- `content`: content-type, mixin, x-data
- `routing`: service, task, site, mapping

With runtime, one `runtime-<context>` context per page context, with one
journey.

**Writes.** Rewrites the four map files with the new statuses, plus
`map/bounded-contexts.json` and `inventory/merge-report.md` (status
counts, surface table, contradictions).

## inventory.docs (`enonic.docs`)

**Does.** Copies existing source docs as-is into
`docs/harvest/<same path>` and lists them in `docs/harvest/INDEX.md`.

Harvested: any `README.md`, `README`, `PRODUCT.md` or `DESIGN.md`, plus
`.md` / `.txt` / `.adoc` under a top-level `docs/` or `documentation/`.

Skipped folders: `.git`, `.extract`, `node_modules`, `graft`,
`graphify-out`, `__pycache__`, `.gradle`, `build`.

**Skip.** With nothing to harvest it still writes the index and records a
skip.

## product.impeccable

**Does.** Deterministic as-is PRODUCT and DESIGN from the maps. It does
not run the Impeccable skill. `status` names `impeccable` for an operator
who wants a richer rewrite, which may replace these files.

**Writes.**

- `product/PRODUCT.md`: profile, source, capabilities with their status,
  link to harvested docs
- `design/DESIGN.md`: one section per page/layout/part/macro with its
  composition
- `design/design.json`

## docs.synthesize

**Does.** Writes a technical overview of every surface and a short guide
to reading the extract.

**Writes.**

- `docs/technical/overview.md`: every surface with kind, status and
  entry, then the bounded contexts
- `docs/guide/overview.md`: how to read the extract

## use_cases

**Writes.** `use-cases/<context>.md`: one Given/When/Then block per
journey, with the surface's status and `evidence[]`.

A context without journeys gets one default journey. Without
`map/bounded-contexts.json` it writes only `use-cases/README.md`.

## spec.kit

**Writes.**

- as-is `spec-kit/constitution.md`
- fragment `spec-kit/constitution/as-is.md`
- `spec-kit/specs/<context>/spec.md` with one `FR-N` per surface citing
  its map id

Without contexts it writes `spec-kit/specs/default/spec.md`. `--tasks`
adds a stub `tasks.md` per context.

## PHP

The PHP profile leaves `inventory.descriptors`, `inventory.integrations`,
`inventory.runtime` and `inventory.docs` unbound, so `run` refuses before
any step with the profile's `todo` list. `php.placeholder` is registered
only so the package imports; running it raises the same list.
