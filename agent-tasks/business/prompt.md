# Task business: write BUSINESS.md, the general business flow

Sidecar: `{sidecar}`
Source (read-only): `{source}`
Profile: `{profile}`
Run: `{run_id}`

## Invariants

- Run from the legacy checkout, in an agent session opened there, with
  `extractkit` on PATH (`./extractkit install` in a kit checkout puts it
  there as a detached copy; preflight only checks it). The CLI refuses to
  run when the working folder, `--source` or `--out` is inside the kit:
  Serena, Graphify and graft act on the session's folder, so a session in
  the kit would onboard and index the kit. If it refuses, stop and ask the
  operator to open the legacy checkout.
- The source checkout is read-only. Every run writes only
  `<source>/.extract/<run-id>/`, or `<source>/extract/<run-id>/` under
  `extractkit headless`. Only `promote` writes into the checkout, and only
  when the operator asked for it.
- There is no dry run. Every command writes on its first call.
- The profile is not yours to write. The only profile file an agent task
  edits is `<sidecar>/context/profile.yaml`, and only the key the task names.
  `<source>/.extractkit/profile.yaml` is the operator's override: read it,
  never create or edit it.
- Core commands never run Serena, graphify or graft. They detect them and
  print the fix. Do not run them inside the source yourself; tell the
  operator and wait. The one exception is `extractkit headless`: its
  preflight builds the graft index and has the agent CLI run Serena
  onboarding and the Graphify index.
- Production CMS hosts are refused. Use a local or review XP only.
- Credentials are the operator's. Never read, print or log the files that hold
  them (the agent token, the XP login, the job environment); `extractkit assets`
  lists their types and file names only.
- The kit extracts and scores. It never infers. Anything you add beyond an
  extracted fact is marked `_(inferred)_` and keeps an `Evidence:` line.
- Migration means a mapped, spec-ready component structure. It does not
  mean converting code to another stack.
- Never pass `--allow-production`, and use `--force` on `promote` only when
  the operator says so.

Write `{sidecar}/business/BUSINESS.md` and `{sidecar}/business/capabilities.json`:
what the extracted project does for its users and operators, in business terms,
and the list of capabilities it names. Build it from what the kit already
extracted. The kit does not know the business; you infer it from evidence, and
an analyst confirms it.

## Inputs

Read these, in this order. Paths are under `{sidecar}`.

- `map/bounded-contexts.json`: the contexts and the surfaces in each. They set
  the Capabilities.
- `use-cases/`: one journey file per context. They set the Business flow.
- `rules/RULES.md` and `rules/view-rules.json`: the named business rules and
  their ids (`VR-` plus ten hex digits). They set the Business rules.
- `map/content-model.json`: the content types, which set the Glossary.
- `map/route-map.json`: sites, services, tasks and admin tools, which set the
  Actors and Integrations.
- `product/PRODUCT.md`: the surface counts per kind. After you finish,
  `product.impeccable` re-runs and fills its users, jobs and capabilities from
  your file.
- `docs/harvest/`: Enonic product docs, when the folder exists.
- `domain/packet/INDEX.json`, when it exists (Enonic profile): the source
  modules (`lib.modules.<name>`, `services`, `tasks`, `cron`, `main`) and, in
  each packet, the jobs, listeners and external callers that start them. Use
  it to find the capabilities the view layer does not show: booking
  lifecycle, payments, pricing, emails, scheduled jobs.

Read the source under `{source}` only to confirm a claim at a `path:line`.

## Output

Write exactly these H2 sections, in this order, and no other H2:

- `## Purpose and audience`: what the project is for and who it serves.
- `## Actors`: who uses or operates it (visitors, editors, administrators,
  scheduled jobs, external systems).
- `## Capabilities`: one `###` entry per capability, grouped by bounded
  context. Each entry cites at least one rule id or surface id. Include the
  domain capabilities the server code carries (booking, payment, pricing,
  email, jobs), not only what the pages show. Include one `### Platform and
  operations` entry for the cross-cutting facts: URL and locale scheme,
  market map, i18n, roles, CSP, caching, scheduled jobs.
- `## Business flow`: the general flow across contexts, step by step, from
  first contact to outcome. Name the context that owns each step.
- `## Business rules by capability`: the named business rules under the
  capability they serve, cited by rule id. Group the rules by capability.
- `## Glossary`: the domain terms, taken from content type names and field
  labels.
- `## Integrations`: external systems and how the project reaches them.
- `## Open questions`: what the evidence does not settle (see below).

## Capability list

Also write `{sidecar}/business/capabilities.json`, one row per `###` capability
of `## Capabilities`, with the same title:

The file is one JSON object: `schema` is `99x.extract.capabilities/v1`, and
`capabilities` is a list of objects with `id`, `title` and, optionally,
`modules`. For example one row has `id` `booking-lifecycle`, `title`
`Booking lifecycle` and `modules` listing `lib.modules.bookings`; another has
`id` `platform-and-operations` and `title` `Platform and operations`.

`id` is lowercase words joined by hyphens and is never `packet`. `modules` is
optional: the `domain/packet/` module ids the capability rests on. The
`domain.behavior` and `spec.capabilities` tasks read this file, one output per
row, so keep it in step with the headings. `check` fails when a row has no
heading, or a heading has no row, or `platform-and-operations` is missing.

## Business flow honesty

- Build the Business flow from entry points that are wired: a page, a service
  a page or a job calls, a `cron` job with a schedule, an `external-caller`
  with a crontab line, an `init` listener. Do not describe a flow from a
  function nothing calls. A rule marked `dead: true` in
  `rules/view-rules.json`, or a surface `unobserved` with no content, is not
  live behavior: list it under Open questions instead.
- Say what a job, service or callback does from its code, never from its
  name. A job called sync, import, cleanup or refresh can read, push, update,
  skip, release or delete: open the function and write the verb the code
  performs, with the direction of data (who sends to whom) and what happens
  to a record that already exists. When you did not open the code, take the
  statement from `domain/<capability>.md` or list it under Open questions.
- A runtime value (a count, a URL, a configured endpoint) names the
  environment it came from (`env` in `inventory/runtime.json`, `x-observed-endpoints`
  in `integrations/openapi.yaml`). Write `review` or `local` as that; never
  write it as production. Production values are not in the extract.

## Evidence contract

- State extracted facts plainly. End every claim beyond an extracted fact with
  `_(inferred)_`.
- Every paragraph that holds an inferred claim contains, or is directly
  followed by, an `Evidence:` line.
- Write `Evidence:` refs in backticks, separated by commas. A ref is one of:
  a source `path:line` that exists under `{source}`; a surface, component,
  type or route id from the maps (for example
  `com.example.app:part:header`); a context id from
  `map/bounded-contexts.json`; or a rule id `VR-` plus ten hex digits from
  `rules/view-rules.json`. A ref that does not resolve fails `check`.
- Every `###` capability cites at least one rule id or surface id.

## Open questions

List here, as separate items:

- Every divergent rule group in `rules/RULES.md`. Name the copies; do not say
  which one is right.
- Every surface whose status is `unobserved`.
- Every claim you could not tie to evidence.

## Do not

- Do not add port plans, XP8 or React4XP advice, stack choices, estimates or
  `DECISIONS.md` / `IMPLEMENTATION.md` content. This is as-is.
- Do not define business outcomes, intent or metrics. Say what the system
  does, not what it should achieve.
- Do not tick `[x]` in `rules/review.md` or set `out-of-scope: yes`.
- Do not edit any file outside `{sidecar}/business/`. Do not edit maps,
  inventories, rules or specs.
- Do not run graft, graphify, Serena onboarding or `git` writes in the source.
- Do not report done until `extractkit check --out {sidecar}` is clean.

Then run:

```bash
extractkit step product.impeccable --profile {profile} --source {source} --out {sidecar}
extractkit check --out {sidecar}
```
