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
| static | `inventory.controllers` | `enonic.controllers` | `inventory/controllers.json` |
| static | `maps.normalize` | `maps.normalize` | the four `map/*-map.json` / `content-model.json` files |
| static | `inventory.integrations` | `enonic.integrations` | `integrations/openapi.yaml`, `integrations/swagger-ui/` |
| cms | `inventory.runtime` | `enonic.cms` | `inventory/runtime.json` |
| cms | `inventory.baseline` | `enonic.baseline` | `baseline/INDEX.md` (optional slot) |
| merge | `maps.merge` | `maps.merge` | `map/bounded-contexts.json`, `inventory/merge-report.md` |
| merge | `inventory.docs` | `enonic.docs` | `docs/harvest/INDEX.md` |
| synthesis | `product.impeccable` | `product.impeccable` | `product/PRODUCT.md`, `design/DESIGN.md` |
| synthesis | `docs.synthesize` | `docs.synthesize` | `docs/technical/overview.md`, `docs/guide/overview.md` |
| synthesis | `use_cases` | `use_cases` | a non-empty `use-cases/` |
| synthesis | `spec.kit` | `spec.kit` | `spec-kit/constitution.md` |
| synthesis | `report.compat` | `enonic.compat` | `reports/xp8-compat.md` (optional slot) |
<!-- markdownlint-enable MD013 -->

**Optional slots** (`inventory.baseline`, `report.compat`; profile key
`optional_slots`) never block `status`, `resume` or the `complete` state.
When their marker is absent, `status` marks the phase row `optional, not
captured` and prints the `step` command that would produce it.

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

- `site/site.xml` (kind `site`), with its `<x-data name allowContentTypes>`
  entries as `xData`
- `site/content-types`, `site/mixins`, `site/x-data`, `site/pages`,
  `site/layouts`, `site/parts`, `site/macros`
- sibling `services/`, `tasks/`, `admin/tools` (`admin-tool`) and
  `admin/widgets` (`admin-widget`), beside `site/`, not under it
- script-only items, from the file itself: `site/filters/*` and
  `<mapping filter>` (`filter`), `site.xml` `<response-processor>`
  (`response-processor`, with `order`), `site/error/error.*` and
  `error/error.*` (`error`), `webapp/webapp.*` (`webapp`),
  `idprovider/idprovider.xml|js` (`id-provider`)
- `i18n/phrases*.properties` and `site/i18n/phrases*.properties`, one
  `i18n-bundle` per locale file with `location`, `locale`, `keyCount` and
  `missingKeys` (keys another locale in the same folder has). Bundles in
  `site/i18n` are named `site.<stem>`
- a service or task folder with a controller and no XML descriptor, as its
  script (`services/<name>/<name>.js`)

A descriptor is `<name>/<name>.xml`, or every `*.xml` in a folder without
one. The display name comes from `<display-name>`, then `<description>`,
then the file stem. The app name comes from the nearest
`gradle.properties` (`appName`, else `group.projectName`), else
`unknown`.

Every XML descriptor of a content type, mixin, x-data, page, layout, part,
macro or task also gets its parsed `<form>` (`form`), and pages and layouts
their `<regions>` (`regions`). A form field records `name`, `type`,
`label`, `occurrences {min, max}` (default 0..1), `config` (for example
`allowContentType`, option values), and for `option-set`, `item-set` and
`field-set` their children (a `field-set` is flattened with a `fieldSet`
label). An `<inline mixin>` stays `{mixin: ref}`. The parser is
`steps/enonic/forms.py`.

**Writes.** `inventory/static.json`. `check` uses it for FR-10 descriptor
coverage.

## inventory.controllers (`enonic.controllers`)

**Does.** Regex scan of controller code. Stdlib only, no graft, no XP.
Scans scripts (`.js`, `.es6`, `.ts`) of components (`site/pages`,
`layouts`, `parts`, `macros`), `services`, `tasks`, `admin/tools` and
`admin/widgets`, `site/filters`, `site/processors`, `site/error`, `error`,
`webapp`, `idprovider`, `main.*`, and the files named by `site.xml`
`<mapping controller>`. `lib/` helpers are not scanned. Comments are blanked
first, so commented-out code reports nothing.

Per file it records, each with its `line`:

- `imports`: `/lib/*` modules and their alias (`require` and `import`,
  including destructured names)
- `calls`: `<alias>.<fn>(` for each import
- `queries`: string-literal `query` and `contentTypes` values
- `methods`: exported `get|post|put|delete|patch|head|options|all`,
  `filter`, `run`, `responseProcessor`, `canRender`, `handle*`
- `views`: `resolve('…')`, `new React4xp('…')`, and `render` calls on a
  thymeleaf, mustache, freemarker, handlebars, react4xp or pebble import
- `i18n`: `localize({ key: '…' })` keys
- `configKeys`: `app.config['…']` and `app.config.…`
- `listeners`: `event.listener({ type: '…' })` types

**Writes.** `inventory/controllers.json` (`controllers.schema.json`).
`maps.normalize` attaches the record to the surface of the same folder (or
file) as `behavior`. A string built at run time is not recorded.

## maps.normalize

**Does.** Turns `inventory/static.json` into stack-agnostic surfaces.
Each resource becomes one surface with id `<app>:<kind>:<name>`, status
`unverified-live`, and the Enonic path under `stackRef.enonic`.
`site.xml` `<mapping>` entries (controller or filter) become `mapping`
routes.

Facts carried onto the surface:

- content types, mixins and x-data: `fields`. A `{mixin: ref}` is expanded
  from the same inventory and each expanded field is tagged `fromMixin`;
  an unknown mixin stays `{mixin: ref}`. The mixin also stays its own
  surface.
- pages, layouts, parts, macros, tasks: `config` (the form), and
  `regions` for pages and layouts
- any surface with a controller: `behavior` (from
  `inventory/controllers.json`)
- the `site` surface: `configKeys` and `listeners` of its app

`map/content-model.json` also gets `references`: one row per
`ContentSelector`, `ImageSelector` or `MediaSelector` field, with the
content types its `allowContentType` lists.

**Writes.**

- `map/project-map.json`: every surface
- `map/component-map.json`: `page`, `layout`, `part`, `macro`
- `map/content-model.json`: `content-type`, `mixin`, `x-data`,
  `i18n-bundle`, and `references`
- `map/route-map.json`: `service`, `task`, `site`, `filter`,
  `response-processor`, `error`, `webapp`, `id-provider`, `admin-tool`,
  `admin-widget`, `mapping`

**Skip.** Without `inventory/static.json` (for example `step
maps.normalize` on an empty sidecar) it re-scans the source.

## inventory.integrations (`enonic.integrations`)

**Does.** Static harvest into a field-minimal OpenAPI 3.1 document. Three
directions, each operation carrying `x-source` (`file:line`) and
`x-direction`:

- `inbound`: every XP service, as `<METHOD> /_/service/<app>/<name>` for
  each HTTP method its controller exports (`inventory/controllers.json`),
  or `POST` when that file is absent or exports none. `all` is written as
  the first of `POST`, `GET`, `PUT`, … the controller does not export
  itself, with `x-exported-method: all`
- `outbound`: every `.js` / `.es6` / `.ts` file that imports
  `/lib/http-client`, one operation per `request({ … })` call, as
  `<method> /outbound/<file-stem>` (`POST` without a literal `method`). A
  string-literal `url` is `x-url`; any other expression is `x-url-expr`
- `browser-embed`: every `<script src="http(s)://…">` in HTML under a
  `site` folder (commented lines skipped), as
  `GET /browser-embed/<slug>` with `x-embed-url`

`inventory.baseline` later appends the third-party hosts it saw as
`x-observed-hosts` (metadata only).

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
   the Config Env table (`--configenv`, or the profile's
   `live_config.configenv_path`). With neither, Config Env is skipped with a
   fix; the step does not fail.
6. Count usage: for each page, layout and part descriptor, one Guillotine
   `queryConnection(query: "components.<kind>.descriptor = '<app>:<name>'",
   first: 0) { totalCount }`. A GraphQL error records every count as
   `null` and `usageProbe: "unsupported"` once. It never refuses the step.
   Macros have no indexed field and are not counted.
7. Count content for sizing a content migration (below).

Provider endpoints inferred from Site Config and Config Env come from the
profile's `live_config` table, not from this adapter. See
[profiles](profiles.md#live_config).

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

### Content volume

`inventory/content-volume.json` and `.md`: a total per content type
(`type = '<app>:<type>'`, `first: 0`), per-language counts (a `language`
terms aggregation), media totals by `media:*` type, and the Content Studio
project list from `GET /admin/rest-v2/cs/project/list` (name and `parent`
layer). A query the server rejects is `null` / `unknown`, never `0`. A
non-200 project list writes `projects: null` and `projectsReason`
(`HTTP <status>`).

**Writes.** `inventory/runtime.json` (with `usage` and `usageProbe`) and
the Enonic extras listed in
[output](output.md#enonic-extras-not-a-phpcore-contract). Live provider
URLs go to `runtime.json` `endpoints` and are merged into
`integrations/openapi.yaml` `x-production-endpoints` (and `spec.js`).
Those URLs are never fetched.

## inventory.baseline (`enonic.baseline`)

**Does.** Optional. For each page in `inventory/runtime.json` (pinned keys
and samples; errored pages skipped) it drives `playwright-cli` with the
given `--storage-state`: desktop 1440 and mobile 390 screenshots, the
rendered HTML (`eval document.documentElement.outerHTML`), and the network
list (`requests --static`). Page URL:
`<host>/admin/site/preview/<project>/<branch><content-path>`, or
`<--site-url><content-path>`.

**Refuse.** A production host, for `--xp-host`, `--guillotine` or
`--site-url`, is refused before any browser starts.

**Skip.** No `playwright-cli` on PATH, no `runtime.json`, or no readable
storage-state records a skip with a fix. A command that fails still keeps
what was captured; the missing file is a skip and a `missing` cell in the
index.

**Writes.**

- `baseline/INDEX.md`: one row per page
- `baseline/<slug>/desktop.png`, `mobile.png`, `page.html`, `network.json`
  (query strings dropped). `page.html` has `[redacted]` in place of the
  values of `meta` / `input` tags and inline-script keys whose name looks
  secret (same rule as site config, plus `csrf`)
- `integrations/openapi.yaml` and `spec.js`: `x-observed-hosts`, the hosts
  other than the site's own

The HTML is a raw capture of the rendered page; treat it like the site.

## maps.merge

**Does.** Runtime beats static. Reads `map/project-map.json` (running
`maps.normalize` first if it is missing) and the optional
`inventory/runtime.json`.

Surface status, for `page`, `layout`, `part` and `macro` only:

- `live`: seen in a runtime page's `templateOrder`; `composition` is
  taken from the highest-round page that lists it
- `live` with evidence `usage:<app>:<name>:<n>`: not sampled, but the usage
  probe counted `n` > 0
- `dead`: not sampled and the usage count is exactly 0
- `unobserved`: not sampled and no count (probe unsupported, or a macro)
- `conditional`: seen in round 1, absent in round 2; also listed as a
  contradiction
- `unverified-live`: no runtime, or any other kind

Seen surfaces get an evidence ref `runtime:<app>:<name>:r<round>`. A `dead`
status needs a count; sampling alone never produces it.

Bounded contexts, each emitted only when non-empty:

- `presentation`: page, layout, part, macro
- `content`: content-type, mixin, x-data, i18n-bundle
- `routing`: service, task, site, mapping, filter, response-processor,
  error, webapp, id-provider
- `admin`: admin-tool, admin-widget

With runtime, one `runtime-<context>` context per page context, with one
journey.

**Writes.** Rewrites the four map files with the new statuses, plus
`map/bounded-contexts.json` and `inventory/merge-report.md` (status
counts including `unobserved`, a surface table with a `usage` column,
contradictions). `references` in `content-model.json` is kept.

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

**Writes.** `use-cases/<context>.md`, from extracted facts only.

- A runtime context (`runtime-<context>`) gets one journey per runtime page:
  **Given** content of type T at path P, **When** a visitor opens it,
  **Then** it renders the composition C. The `Evidence:` line carries
  `runtime:<key>:r<round>` and, when `baseline/` has the page,
  `baseline:<slug>/desktop.png`, `mobile.png` and `page.html`.
- A static context gets one journey per surface that has fields, config,
  regions, controller behavior or a composition. The **Then** lists the
  same bullets as the spec.
- A context with none gets one journey saying nothing was extracted.

Without `map/bounded-contexts.json` it writes only `use-cases/README.md`.

## spec.kit

**Writes.**

- as-is `spec-kit/constitution.md`
- fragment `spec-kit/constitution/as-is.md`
- `spec-kit/specs/<context>/spec.md` with one `FR-N` per surface

Each FR has a heading, one sentence, `Acceptance:` bullets and an
`Evidence:` line. The bullets come from the surface only:

- content model: a field per input (type, occurrences, `allowContentType`,
  option values, `fromMixin`)
- components: config inputs and `Exposes region`
- controllers: exported methods, `/lib/*` calls, queries, views, i18n keys,
  config keys, listeners, each with `file:line`
- runtime: the composition

`Evidence:` lists the map id, the descriptor path, `runtime:` / `usage:`
refs and the controller file. The kit writes no `_(inferred)_` text.

Without contexts it writes `spec-kit/specs/default/spec.md`. `--tasks`
adds a stub `tasks.md` per context.

## report.compat (`enonic.compat`)

**Does.** Optional. A factual XP7 to XP8 list from `inventory/static.json`
and `inventory/controllers.json`. Not a plan and not part of `spec-kit/`.

**Writes.** `reports/xp8-compat.md`:

- XML descriptor count by kind (each needs a YAML counterpart), plus
  services and tasks that have no XML descriptor
- script-only items (errors, webapp, i18n bundles)
- `/lib/xp/*` modules in use, with the controllers and calls using them
- calls the XP8 upgrade page names (for example `setPermissions`), with
  the page's own sentence
- lowercase HTTP exports and `resolve` calls, with `file:line`
- site mappings, filters and processors

Every row cites the XP8 offline doc page it was checked against. No row
says an API is removed unless that page does. `promote` does not copy
`reports/`.

## PHP

The PHP profile leaves `inventory.descriptors`, `inventory.controllers`,
`inventory.integrations`, `inventory.runtime` and `inventory.docs` unbound,
so `run` refuses before any step with the profile's `todo` list.
`php.placeholder` is registered only so the package imports; running it
raises the same list.
