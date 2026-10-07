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
| context | (command `context`) | — | `context/profile.yaml` |
| static | `map.code` | `map.code` | always (optional) |
| static | `map.semantic` | `map.semantic` | always (optional) |
| static | `inventory.descriptors` | `enonic.descriptors` | `inventory/static.json` |
| static | `inventory.controllers` | `enonic.controllers` | `inventory/controllers.json` |
| static | `inventory.templates` | `core.templates` | `inventory/templates.json` |
| static | `maps.normalize` | `maps.normalize` | the four `map/*-map.json` / `content-model.json` files |
| static | `inventory.integrations` | `enonic.integrations` | `integrations/openapi.yaml`, `integrations/swagger-ui/` |
| cms | `inventory.runtime` | `enonic.cms` | `inventory/runtime.json` |
| cms | `inventory.baseline` | `enonic.baseline` | `baseline/INDEX.md` (optional slot) |
| merge | `maps.merge` | `maps.merge` | `map/bounded-contexts.json`, `inventory/merge-report.md` |
| merge | `rules.view` | `core.view_rules` | `rules/view-rules.json`, `rules/RULES.md` |
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

## context (command)

**Does.** Phase 2, not a slot: `run` and `resume` call it when the sidecar
has no overlay, and `extractkit context --source DIR` runs it alone. It
detects the stack from the checkout (`--profile` wins), runs the build-scope
analysis without executing any build, and writes the overlay that every
later slot composes on top of the stack profile. It excludes nothing by
itself.

**Needs.** Required: `--source`, and exactly one stack marker unless
`--profile` is given (`src/main/resources/application.xml` or
`site/site.xml` for `enonic`, a root `composer.json` for `php`).
Optional: `--profile`, `--exclude`, `<source>/.extractkit/profile.yaml`.

**Writes.** `context/build-scope.json` (`branch`, `entry_points`,
`in_scope`, `out_of_scope`) and `context/profile.yaml` (`extends: <stack>`,
plus `exclude: []` when the build scope has no entry point or nothing
outside it). A re-run refreshes both and keeps the `exclude` and
`live_config` keys the agent tasks wrote.

**Refuse.** No marker, or markers for both stacks: exit 1 with a `fix:`
that passes `--profile enonic`. `step context` is refused with the
`extractkit context` command.

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
- `methods`: exported
  `get|post|put|delete|patch|head|options|all|connect|trace`, `filter`,
  `run`, `responseProcessor`, `canRender`, `handle*`
- `views`: `resolve('…')`, `new React4xp('…')`, and `render` calls on a
  thymeleaf, mustache, freemarker, handlebars, react4xp or pebble import
- `i18n`: `localize({ key: '…' })` keys
- `configKeys`: `app.config['…']` and `app.config.…`
- `listeners`: `event.listener({ type: '…' })` types

**Writes.** `inventory/controllers.json` (`controllers.schema.json`).
`maps.normalize` attaches the record to the surface of the same folder (or
file) as `behavior`. A string built at run time is not recorded.

## inventory.templates (`core.templates`)

**Does.** Stack-neutral inventory of the view layer. Every profile binds
it, so it runs on enonic, as, php and core checkouts alike. Stdlib only;
the source stays read-only. It reads `inventory/controllers.json` when
present, which is why it sits after `inventory.controllers`.

Engines are detected from file globs, content signals and manifests
(`package.json`, `pom.xml`, `build.gradle`):

<!-- markdownlint-disable MD013 -->
| Engine | Signals |
| --- | --- |
| `freemarker` | `*.ftl`, `*.ftlh`, `<#` / `<@` directives, `freemarker` dependency |
| `thymeleaf` | `xmlns:th` or `th:*` attributes inside a tag, `thymeleaf` / `lib-thymeleaf` dependency |
| Enonic render binding | a file named by a controller `resolve('…')` that imports a render lib gets that lib as engine (`high`) |
| `mustache`, `handlebars` | `*.mustache`; `*.hbs`; `{{#` / `{{>` sections with the dependency; `registerHelper(` scripts |
| `pebble` | `*.peb`, `{% tag %}` with the dependency |
| `react` | `*.jsx` / `*.tsx` with JSX; `framework: react4xp` when a controller names it |
| `nextjs` | `next.config.*`, `next` dependency, files under `pages/` or `app/` (also recorded as `react`) |
| `angular` | `angular.json`, `@Component(`, `*.component.html` |
| `vue` | `*.vue`, `vue` dependency |
| `jquery` | an HTML page with `<script src=…jquery…>`, the `jquery` dependency, then `$(` / `jQuery(` usage in JS |
<!-- markdownlint-enable MD013 -->

Each engine row has `confidence` (`high`, `medium`, `low`) and its signals
as `path:line` plus the rule. A file signal is `high`, a dependency only is
`medium`, and jQuery found only through `$(` usage is `low`. The scan skips
`node_modules`, `vendor`, `dist`, `build`, `target`, `.extract`, `.git`,
`graft`, `graphify-out` and `.serena`, `extract` once it holds a headless
run, and files over 1 MB. Skips are
listed under `coverage`.

Per file it records, each with `line`: `inputs` (declared ones typed, the
rest `inferred`), `children`, `slots`, `outputs`, loop and conditional
counts (a conditional is a branch that shows or selects, not a derived
value), `i18n`, `assets`, `dom` (jQuery selectors bound to the markup) and
the `predicates` that `rules.view` reads. An Angular `templateUrl` file is a
companion of its component, not a second file. `controllers[]` holds the
branches of render controllers over `content.data.*` or app and site config.

**Writes.** `inventory/templates.json` (`templates.schema.json`).

## maps.normalize

**Does.** Turns `inventory/static.json` into stack-agnostic surfaces.
Each resource becomes one surface with id `<app>:<kind>:<name>`, status
`unverified-live`, and the Enonic path under `stackRef.enonic`.
`site.xml` `<mapping>` entries (controller or filter) become `mapping`
routes.

Template files become surfaces of kind `component`, or `partial` when only
other templates include them or when they are helper scripts. The id is
`<engine>:<kind>:<path without suffix>`, engine detail is under
`stackRef.template`, and a `template` block carries `inputs`, `children`
(each `resolved` to a surface id or `unresolved`), `slots`, `outputs`,
`logic`, `i18n`, `assets`, `dom` and `dataSource`, every item with
`path:line`. `dataSource` is a surface id, `next:route:<path>` for a
Next.js page, or `none`.

An Enonic descriptor and its view are one surface. The join reads the
controller `views` rows: `resolve` and `React4xp` refs by name, and a
`<lib>.render` call by the view file in the same folder. The surface keeps
its `config` and `regions` and gains `template`. Joining here, not in
`maps.merge`, keeps a `--until static` run spec-ready without CMS access.

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
- `map/component-map.json`: `page`, `layout`, `part`, `macro`, `component`, `partial`
- `map/content-model.json`: `content-type`, `mixin`, `x-data`,
  `i18n-bundle`, and `references`
- `map/route-map.json`: `service`, `task`, `site`, `filter`,
  `response-processor`, `error`, `webapp`, `id-provider`, `admin-tool`,
  `admin-widget`, `mapping`, and `route` (Next.js pages)

`check` fails when a file in `inventory/templates.json` maps to no
surface, or when a surface with a `template` lacks `entry`, `inputs`,
resolved or `unresolved` children, `dataSource` or `status`.

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

HTTP with cookies from the Playwright storage-state file. Only `http` and
`https` URLs are opened. A redirect is followed only on the same host and never
from https to http; any other redirect is refused (`redirect_refused`), because
the cookie and the production check belong to the host you named.

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
   `live_config.configenv_path`, which `enonic` defaults to the seeds
   Config Env tool). With neither, Config Env is skipped with a fix; the
   step does not fail. List every public Site Config and Config Env key whose
   value is a URL or a host map in `inventory/live-config-candidates.json`
   (`origin`, `key`, `kind: url|hostmap`, `covered`). The agent task
   `context.live_config` reads that file.
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
- Config Env 404/405/501: treat as "app not installed", skip, and record
  the skip `enonic.cms.configenv` with a fix that names `--configenv`
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

**Refuse.** It resolves the same CMS settings as `enonic.cms` and refuses
on the same gaps: no `--branch`, no Guillotine URL or project, no content
keys. A production host, for `--xp-host`, `--guillotine`, `--configenv` or
`--site-url`, is refused before any browser starts.

**Skip.** No `runtime.json`, no `playwright-cli` on PATH, or no readable
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
- `live` with evidence `usage:<app>:<kind>:<name>:<n>`: not sampled, but
  the usage probe counted `n` > 0
- `dead`: not sampled and the usage count is exactly 0
- `unobserved`: not sampled and no count (probe unsupported, or a macro)
- `conditional`: seen in round 1, absent in round 2; also listed as a
  contradiction
- `unverified-live`: no runtime, or any other kind

Seen surfaces get an evidence ref `runtime:<app>:<name>:r<round>`. A `dead`
status needs a count; sampling alone never produces it.

Bounded contexts, each emitted only when non-empty:

- `presentation`: page, layout, part, macro, component, partial
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

## rules.view (`core.view_rules`)

**Does.** Surfaces business rules written in the view layer, with
evidence. It reads `inventory/templates.json`, the merged maps and, when
present, the CMS survey. It extracts, scores and groups. It never names a
rule and never evaluates an expression.

Every predicate the scanners recorded becomes a rule:

- `id`: `VR-` plus a hash of file, line and shape. Stable across runs
- `kind`: `visibility`, `eligibility`, `calculation`, `validation`,
  `formatting`, `selection`, `routing` or `market`
- `expression`, `shape` (operators unified, operands reduced to their leaf
  name, literals normalized), `literals`, `effect`, `component`, `source`
  (`path:line`)
- `operands`: each resolved to a component input, a content-model field or
  a config key, else `unresolved`

Harvested per engine: Thymeleaf `th:if`, `th:unless`, `th:switch`,
ternaries, `#numbers` / `#dates` / `#strings`, `th:with`; FreeMarker `<#if>`,
`<#assign>` arithmetic, `?then`, `?string`, macro defaults; Mustache
sections and Handlebars `if` blocks and helper bodies; Pebble `if`, `set`;
JSX `&&`, ternaries, early `return null`, `className`, derived constants,
`getServerSideProps` branches; Vue `v-if`, `v-show`, `computed`; Angular
`*ngIf`, `@if`, pipes, `Validators.*`, `canActivate`; jQuery handler
branches, `.toggle`, `.validate({rules})`, `$.ajax` data; and Enonic
controller branches over content data or config before `render`.

**Score.** A domain-term operand (price, amount, date, role, market,
country, status, type, age, qty, discount, limit and a few more) adds 2, a
non-trivial literal 2, a comparison with it 1, arithmetic 1. Length checks,
null and empty guards, index checks, format calls and pure CSS toggles lower
it. Two or more is `business`, otherwise `presentational`. The signals stay
on the rule. Nothing is dropped.

**Groups.** The same shape in several files is `repeated`. The same
operands with a different literal or operator across files are
`divergent`.

**Runtime.** When `inventory/content-survey.json` or `inventory/runtime.json`
holds sampled values, each rule records up to 10 distinct values per operand.
A business rule whose sampled operands are always empty is `possiblyDead`.

**Review.** `rules/review.md` has one checkbox per business rule with
`name:`, `intent:` and `out-of-scope:` lines. The agent fills the first two
and marks them `_(inferred)_`; an analyst ticks the box. A re-run carries
all of it over by id, from the same sidecar or the newest sibling under
`<source>/.extract/` or `<source>/extract/`, and lists ids that vanished
under `Removed`.

**Writes.** `rules/view-rules.json` (`view-rules.schema.json`),
`rules/RULES.md` (coverage line first, divergent groups next, then context,
component and kind), `rules/literals.md`, `rules/review.md`.

## inventory.docs (`enonic.docs`)

**Does.** Copies existing source docs as-is into
`docs/harvest/<same path>` and lists them in `docs/harvest/INDEX.md`.

Harvested: any `README.md`, `README`, `PRODUCT.md` or `DESIGN.md`, plus
`.md` / `.txt` / `.adoc` under a top-level `docs/` or `documentation/`.

Skipped folders: `.git`, `.extract`, `node_modules`, `graft`,
`graphify-out`, `__pycache__`, `.gradle`, `build`, and `extract` once it
holds a headless run.

**Skip.** With nothing to harvest it still writes the index and records a
skip.

## product.impeccable

**Does.** Deterministic as-is PRODUCT and DESIGN from the maps. It does
not run the Impeccable skill. `status` names `impeccable` for an operator
who wants a richer rewrite, which may replace these files.

**Writes.**

- `product/PRODUCT.md`: profile, source, capabilities with their status,
  link to harvested docs
- `design/DESIGN.md`: one section per page, layout, part, macro, component
  and partial, with its composition and, for a template, its file, inputs
  and children
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
- Each business view rule gets its own journey: **Given** the rule applies
  to the component, **When** its expression is evaluated, **Then** the
  effect applies, cited by `path:line` and rule id.
- A context with none gets one journey saying nothing was extracted.

Without `map/bounded-contexts.json` it writes only `use-cases/README.md`.

## spec.kit

**Writes.**

- as-is `spec-kit/constitution.md`: a title, the project part from
  `spec-kit/constitution/project.md` (the `constitution` agent task) or a
  note that it has not run, then a Governance section
- `spec-kit/specs/<context>/spec.md` with one `FR-N` per surface

Each FR has a heading, one sentence, `Acceptance:` bullets when any
were extracted, and an `Evidence:` line. The bullets come from the
surface only:

- content model: a field per input (type, occurrences, `allowContentType`,
  option values, `fromMixin`)
- components: config inputs and `Exposes region`
- controllers: exported methods, `/lib/*` calls, queries, views, i18n keys,
  config keys, listeners, each with `file:line`
- runtime: the composition

- business view rules: one `Rule VR-…` bullet each, with kind, expression
  and `path:line`

`Evidence:` lists the map id, the descriptor path, `runtime:` / `usage:`
refs and the controller file. The kit writes no `_(inferred)_` text; a
rule name from `rules/review.md` is carried with its own marker.

Each context also gets a `## Components` section before the requirements:
the component tree, and per component a table of inputs and its slots and
outputs, every row with an `x-source` cite. Divergent rule groups end the
spec as `## Open questions`. `check` fails a `business` rule that no spec
cites unless `rules/review.md` marks it `out-of-scope: yes`.

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

**Skip.** No `inventory/static.json` records a skip that points at
`run --until static`.

## Agent tasks

Not pipeline slots. The agent phase (phase 7) lists the tasks in
`agent-tasks/<id>/`; `extractkit agent list|show|next` renders them and the
[extract-agentic skill](../skills/extract-agentic/SKILL.md) runs them. The
kit never calls a model. `status` counts the phase done when every required
task is done. Output rules are the same as for the kit: every claim beyond
an extracted fact ends with `_(inferred)_` and sits under an `Evidence:`
line.

### context.exclude

**Does.** Required while the build scope leaves folders undecided. After
`inventory.integrations` (the end of the static phase), before CMS and
merge, so the later scans skip what it excludes. Reads
`context/build-scope.json` and the checkout, and picks the folders of
`out_of_scope` that are not part of the product (old prototypes, for
example), keeping the ones the product runs (a payment cron script that no
build names, for example). Each pick cites its evidence as a YAML comment.

**Writes.** The `exclude` key of `context/profile.yaml`, and nothing else
in it. `[]` is a valid decision, and a folder it cannot judge stays in:
an exclusion cannot be undone in the same sidecar. Then it re-runs
`run --from static --until synthesis` with the CMS flags of the earlier
run, or stops at `--until inventory.integrations` when there were none.

**Done when.** The overlay has an `exclude` key. The `context` phase
already writes `exclude: []` when the build scope has nothing to decide.

**Check.** `context_grounded` fails an entry that is not in
`context/build-scope.json` `out_of_scope`.

### context.live_config

**Does.** Required after a live harvest. After `inventory.runtime`. Reads
`inventory/runtime.json`, `inventory/live-config-candidates.json`,
`integrations/openapi.yaml` and `site/site.xml` in the checkout, and writes
the rules that turn the project's Site Config and Config Env values into
provider endpoints: `site_url_keys`, `hostmap_keys`, `providers` and
`env_endpoints` (see [profiles](profiles.md#live_config)).

**Writes.** The `live_config` key of `context/profile.yaml`, and nothing
else in it. Then it re-runs `step inventory.runtime` with the CMS flags of
the earlier run, so `runtime.json` and `openapi.yaml` carry the endpoints.

**Done when.** The overlay has a `live_config` key (an empty mapping
counts), or `inventory/live-config-candidates.json` does not exist: an
offline run, or a stack with no CMS step, has nothing to ground.

**Check.** `context_grounded` fails a key, path, URL path or origin host
that is in neither the checkout nor the harvested config (see
[CLI](cli.md#context)).

### rules.name

**Does.** Required. After `rules.view`. Reads `rules/RULES.md`,
`rules/review.md` and `rules/view-rules.json`, and the source at each cited
`path:line`. The agent writes a `name:` and a one-sentence `intent:` for
each business rule, names every copy of a divergent group without picking
one, and never ticks `[x]` or sets `out-of-scope: yes`.

**Writes.** `rules/review.md`. Then it re-runs
`run --from merge --until synthesis` so the names reach
`rules/view-rules.json`, `rules/RULES.md` and the specs.

**Done when.** `rules/view-rules.json` exists and no `business` rule is
still `status: extracted`. A marker file cannot prove this, because
`rules/review.md` exists from `rules.view` onwards.

**Skip.** None. With no business rules the task is already done.

### business

**Does.** Required. After `spec.kit`. Reads `map/bounded-contexts.json`,
`use-cases/`, `rules/RULES.md`, `rules/view-rules.json`,
`map/content-model.json`, `map/route-map.json`, `product/PRODUCT.md` and
`docs/harvest/` when it exists. Writes the general business flow of the
extracted project. It lists divergent rule groups and `unobserved` surfaces
under Open questions and adds no port advice.

**Writes.** `business/BUSINESS.md` with the sections Purpose and audience,
Actors, Capabilities, Business flow, Business rules by capability,
Glossary, Integrations and Open questions. `promote` copies it to
`BUSINESS.md`. `check` validates it when present (see
[output](output.md#businessmd)). Then it re-runs `step product.impeccable`,
which fills PRODUCT.md's users, jobs and capabilities from it.

**Skip.** `agent next` does not return the task while a required input is
missing; it names the input and points at `status`.

### constitution

**Does.** Required. After `spec.kit`. Reads `business/BUSINESS.md`,
`map/bounded-contexts.json`, `map/route-map.json`,
`map/content-model.json`, `context/build-scope.json` and
`rules/view-rules.json`, then the build files, descriptors, CI files and a
sample of the code in the source. Writes the ground rules of the project as
it is: stack with versions, architecture, conventions, integrations,
delivery, and the invariants a change must preserve. It adds no principle
for a future stack.

**Writes.** `spec-kit/constitution/project.md` with the sections Product,
Stack, Architecture, Conventions, Integrations, Delivery, Invariants and
Open questions. Then it re-runs `step spec.kit`, which composes
`spec-kit/constitution.md` from it. `check` validates it when present (see
[output](output.md#constitution)).

**Skip.** Like `business`, while a required input is missing.

### spec.enrich

**Does.** Optional. After `spec.kit`. Rewrites the prose of a `spec.md` FR
or a `use-cases/*.md` journey so it reads better: first the FRs with no
extracted behavior, then those that are only a field list. Every FR keeps
its `Acceptance:` bullets and `Evidence:` line, and every added sentence
ends with `_(inferred)_`.

**Writes.** `spec-kit/specs/` and `use-cases/`, prose only, and
`reports/spec-enrich.md`, which it extends after each file it rewrites.
`check` then fails an FR without an `Evidence:` line.

**Done when.** `reports/spec-enrich.md` has the line `Status: complete` and is
newer than every `spec.md`, so a later `spec.kit` run makes it pending again.
Without that line the report is the progress ledger of a run that stopped
midway: the next run skips the files it lists.

**Skip.** Never returned by `agent next`. Run it with
`extractkit agent show spec.enrich --out <sidecar>`; `headless` runs it after
the required tasks unless `--no-enrich`. Re-running `spec.kit` rewrites the
specs, so enrich after the last run of that slot.

### spec.review

**Does.** Optional. After `spec.kit`. Reads `spec-kit/specs/`,
`business/BUSINESS.md` (skipped when absent), `rules/view-rules.json` and
`map/bounded-contexts.json`. Reviews the generated specs for meaning: an FR
that misreads its cited line, a context split in the wrong place, duplicate
or conflicting FRs, a contradiction with `BUSINESS.md`, behavior no spec
covers, and a spec too vague for `/speckit.plan`. It edits no spec.

**Writes.** `reports/spec-review.md` only: an H1 `# Spec review`, then one
`### SR-<n>: <title>` per finding with `Spec:`, `Severity:`, `Fix in:` and
`Evidence:` lines, or `No findings.`. `check` validates the format (see
[output](output.md#spec-review)), never the findings. `promote` never
copies the report.

**Skip.** Never returned by `agent next`, and it never makes the agent
phase pending. Run it with `extractkit agent show spec.review --out <sidecar>`.

## PHP

The PHP profile leaves `inventory.descriptors`, `inventory.controllers`,
`inventory.integrations`, `inventory.runtime` and `inventory.docs` unbound,
so `run` refuses before any step with the profile's `todo` list.
`php.placeholder` is registered only so the package imports; running it
raises the same list.
