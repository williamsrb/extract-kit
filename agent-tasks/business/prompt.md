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
  `<source>/.extract/<run-id>/`. Only `promote` writes into the checkout, and
  only when the operator asked for it.
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
- The kit extracts and scores. It never infers. Anything you add beyond an
  extracted fact is marked `_(inferred)_` and keeps an `Evidence:` line.
- Migration means a mapped, spec-ready component structure. It does not
  mean converting code to another stack.
- Never pass `--allow-production`, and use `--force` on `promote` only when
  the operator says so.

Write `{sidecar}/business/BUSINESS.md`: what the extracted project does for
its users and operators, in business terms. Build it from what the kit already
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
- `product/PRODUCT.md`: the as-is capability list.
- `docs/harvest/`: Enonic product docs, when the folder exists.

Read the source under `{source}` only to confirm a claim at a `path:line`.

## Output

Write exactly these H2 sections, in this order, and no other H2:

- `## Purpose and audience`: what the project is for and who it serves.
- `## Actors`: who uses or operates it (visitors, editors, administrators,
  scheduled jobs, external systems).
- `## Capabilities`: one `###` entry per capability, grouped by bounded
  context. Each entry cites at least one rule id or surface id.
- `## Business flow`: the general flow across contexts, step by step, from
  first contact to outcome. Name the context that owns each step.
- `## Business rules by capability`: the named business rules under the
  capability they serve, cited by rule id. Group the rules by capability.
- `## Glossary`: the domain terms, taken from content type names and field
  labels.
- `## Integrations`: external systems and how the project reaches them.
- `## Open questions`: what the evidence does not settle (see below).

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
extractkit check --out {sidecar}
```
