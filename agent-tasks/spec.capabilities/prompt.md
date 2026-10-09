# Task spec.capabilities: write one spec-kit spec per business capability

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

Write `{sidecar}/spec-kit/specs/<capability-id>/spec.md` for every capability in
`{sidecar}/business/capabilities.json`. These are the specs an operator hands
to Spec Kit to plan and build the product on another stack. They say what the
product must do, so a team can build it and check the result without reading
the legacy source. They do not say how the legacy code does it.

## Inputs

Paths are under `{sidecar}`.

- `business/capabilities.json` and `business/BUSINESS.md`: the capabilities
  and what each is for. The capability `platform-and-operations` holds the
  cross-cutting facts: URL and locale scheme, market map, i18n, roles, CSP,
  caching, jobs.
- `domain/<capability-id>.md`: the behavior of each capability: states,
  formulas, external calls, emails, jobs, retries. This is the main input.
- `reports/do-not-port.md`: what a migration must not carry over. Never cite
  an entry of its `Defects` or `Dead code` sections as required behavior.
- `spec-kit/evidence/<context>.md`: the per-surface index with `path:line`.
  Use it to find the fields, types, routes and rules a requirement rests on.
- `rules/view-rules.json`: rule ids; a rule with `dead: true` is not behavior.
- `map/content-model.json`: content types and fields, for Key Entities.

Read the source under `{source}` only to confirm a claim at a `path:line`.

## Output

Each spec follows the Spec Kit layout. Write exactly these H2 sections, in this
order, and no other H2:

- `## User Scenarios & Testing`: prioritized user stories, each a `### User
  Story N - <title> (Priority: P1)` (then P2, P3). Each has a short story, a
  `**Why this priority**` line, an `**Independent Test**` line that a
  newcomer could run on their own, and `**Acceptance Scenarios**` as numbered
  `Given / When / Then` lines.
- `## Requirements`: functional requirements as bullets
  `- **FR-001**: System MUST <observable behavior>`. Number them in order.
  Each is about behavior a user, an operator or another system can observe.
  It never names a legacy file, function, library or call: no `Calls ...`,
  no `Exports ...`, no template or controller names. Put amounts, states,
  thresholds, rounding, roles, URLs and schedules in the requirement itself.
  A test on another stack must be able to check each requirement from its own
  text, so write into it: the trigger as something observable (a request with
  its parameter, header or body field names, a status value, a schedule, an
  event); each value with its unit and rounding (truncate, round or ceiling),
  operator (`==` or `>=`) and every floor, cap and exception; the sort key of
  any "newest" or "first"; and the response, status code or stored change that
  is the outcome. Restate a term the requirement relies on; do not point to
  another section for it. Open the source for a field name, order or
  operator the domain file leaves out. When two requirements or two files give
  a different rule for the same thing, read the code, write one rule, and list
  the conflict under Edge Cases.
- `## Key Entities`: the entities the capability owns, their fields and
  relationships, from the content model and the domain file.
- `## Success Criteria`: measurable outcomes (`SC-001`, ...), each a number,
  a state or a time that a test can read.
- `## Edge Cases`: what happens at the boundaries: empty, duplicate, late,
  refused, partially paid, expired.
- `## Evidence`: one bullet per requirement, in the form
  `- FR-001: `path:line`, `path:line``. A ref is a source `path:line` that
  exists under `{source}`, or a rule id `VR-` plus ten hex digits.

A spec is at most 60 KB. When a capability is larger, say so in `## Edge
Cases` and keep the P1 stories complete; do not split the file.

## Evidence contract

- Every `FR-###` of `## Requirements` has a bullet in `## Evidence` with at
  least one ref that resolves. A requirement without evidence fails `check`.
- State what the domain file and the code establish. End a requirement you
  worked out rather than read with `_(inferred)_`.
- Describe live behavior. Do not cite a dead rule, an unreferenced function,
  or anything listed under `Defects` or `Dead code` in `reports/do-not-port.md`.
- Mark the environment of a runtime observation (`review`, `local`). A value
  from a non-production environment is never written as the production value.
- Never write a secret value. Name the key and `path:line`.

## Do not

- Do not write port plans, XP8 or React4XP advice, stack choices, estimates
  or `DECISIONS.md` / `IMPLEMENTATION.md` content. Requirements are
  independent of the stack, in either direction.
- Do not copy the evidence specs. They are an index; you write behavior.
- Do not edit any file outside `{sidecar}/spec-kit/specs/`.
- Do not run graft, graphify, Serena onboarding or `git` writes in the source.
- Do not report done until `extractkit check --out {sidecar}` is clean.

Then run:

```bash
extractkit check --out {sidecar}
```
