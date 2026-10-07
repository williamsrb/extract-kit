# Task constitution: write the project constitution

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

Write `{sidecar}/spec-kit/constitution/project.md`: the ground rules of the
extracted project as it is today. `promote` copies the composed
`spec-kit/constitution.md` to `.specify/memory/constitution.md`, where Spec Kit
reads it before every new spec, plan or task list. Whoever writes the next
spec for this project must learn from it what the project is built on, how it
is laid out, which conventions its code follows, and which business rules a
change must not break.

## Inputs

Read these first. Paths are under `{sidecar}`.

- `business/BUSINESS.md`: purpose, actors, capabilities and business rules.
  It sets Product and Invariants.
- `map/bounded-contexts.json` and `map/route-map.json`: the contexts, sites,
  services, tasks and admin tools. They set Architecture.
- `map/content-model.json`: the content types and how they reference each
  other.
- `context/build-scope.json`: the build entry points and the folders in and
  out of the build. It sets Delivery.
- `rules/view-rules.json`: the business rule ids.
- `integrations/openapi.yaml` and `docs/technical/overview.md`, when present.

Then read the source under `{source}` for what the maps do not hold: build
files (`build.gradle`, `gradle.properties`, `package.json`, `composer.json`,
webpack or gulp files), the application descriptor, CI files, deploy values,
a sample of controllers, services, templates and i18n bundles. Cite each fact
at the `path:line` where you read it.

## Output

No H1: `spec.kit` adds the title. Write exactly these H2 sections, in this
order, and no other H2:

- `## Product`: what the project is and who it serves, in two to four
  sentences, from `BUSINESS.md`.
- `## Stack`: runtime and platform with versions, languages, frameworks,
  view engines, frontend libraries and build tools. One bullet each, with
  the version when the source pins one.
- `## Architecture`: how the code is organized: modules, bounded contexts,
  where controllers, services, scheduled tasks, templates, assets and
  content types live, and how a request reaches a response.
- `## Conventions`: the patterns the code follows today: naming, file
  layout per component, configuration (app config, site config, env
  values), i18n and locales, error handling, logging, shared libraries.
  Name a convention only when at least two places follow it.
- `## Integrations`: external systems, how the project reaches each one
  (HTTP client, library, cron, webhook) and where it is configured.
- `## Delivery`: build steps, CI jobs, environments and deploy targets.
- `## Invariants`: the business rules and technical constraints a change
  must preserve, each as a bullet that cites a rule id (`VR-` plus ten hex
  digits), a capability's surface id or a source `path:line`.
- `## Open questions`: what the evidence does not settle, and every pair of
  places that contradict each other.

## Evidence contract

- State extracted facts plainly. End every claim beyond an extracted fact with
  `_(inferred)_`.
- Every paragraph or bullet list that holds an inferred claim contains, or is
  directly followed by, an `Evidence:` line.
- Every section except `Open questions` has at least one `Evidence:` line.
- Write `Evidence:` refs in backticks, separated by commas. A ref is one of:
  a source `path:line` that exists under `{source}`; a surface, component,
  type or route id from the maps; a context id from
  `map/bounded-contexts.json`; or a rule id from `rules/view-rules.json`. A
  ref that does not resolve fails `check`.

## Do not

- Do not write principles for a future stack, port plans, XP8 or React4XP
  advice, estimates, or `DECISIONS.md` / `IMPLEMENTATION.md` content. This
  is as-is: say what the project does and follows, not what it should do.
- Do not copy `BUSINESS.md` or the specs. Cite them, and keep to what a
  spec writer needs before writing a requirement.
- Do not edit any file outside `{sidecar}/spec-kit/constitution/`. Do not
  write `spec-kit/constitution.md` yourself: `spec.kit` composes it.
- Do not run graft, graphify, Serena onboarding or `git` writes in the source.
- Do not report done until `extractkit check --out {sidecar}` is clean.

Then run:

```bash
extractkit step spec.kit --profile {profile} --source {source} --out {sidecar}
extractkit check --out {sidecar}
```
