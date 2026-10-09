# Task donotport: list what a migration must not carry over

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

Write `{sidecar}/reports/do-not-port.md`: the behavior of the legacy product
that a migration must **not** reproduce. The capability specs describe what
the product should do; this file lists what the code does that it should not,
so a team building the replacement does not copy it.

## Inputs

Paths are under `{sidecar}`.

- `business/capabilities.json`: the capability ids an entry can touch.
- `rules/view-rules.json`: rules with `dead: true` (inside a comment, behind a
  constant gate or `th:if="false"`, with `deadAt`) and rules with
  `unreferenced: true` (in a function nothing calls). Rules with
  `scope: server` are the status, amount, date and role conditions of the
  server code.
- `map/route-map.json`: `cron`, `init` and `external-caller` surfaces; a
  schedule or caller that nothing wires is a finding too.
- `integrations/openapi.yaml`: `x-auth` of each inbound service, and
  `x-observed-endpoints` with `dangling: true` for a configured endpoint no
  inbound route serves.
- `domain/packet/`: per-module facts with `path:line`. Open the ones you need.

Read the source under `{source}` at each `path:line` before you list it.

## Output

Write exactly these H2 sections, in this order, and no other H2:

- `## Security behavior`: unauthenticated or under-protected services,
  elevated contexts that do more than their caller needs, secrets or
  credentials committed to the source, values trusted from the request
  without a check, TLS verification turned off. Also every exported handler
  that is gated to an environment or left for testing (a name such as
  `testOnly`, a comment such as "not running in prod"), and every inbound
  service whose `x-auth` is `none` and that writes, sends or calls out.
- `## Defects`: behavior that is wrong: arithmetic or rounding errors,
  conditions that cannot be true, state transitions that skip a state, a
  retry that duplicates an effect, swallowed errors, wrong cites in comments.
- `## Dead code`: rules and branches the extract marks `dead`, functions
  marked `unreferenced`, jobs and callbacks nothing triggers, endpoints
  nothing serves.

Under each section write one bullet per entry:

```
- **DNP-001** <what the code does>. Reason: <why a migration must not copy it>. Capability: `<capability-id>`. Evidence: `path:line`
```

Ids run `DNP-001`, `DNP-002`, ... across the file. `Capability:` is an id from
`business/capabilities.json`, or `platform-and-operations` for a cross-cutting
finding.

## Evidence contract

- Every entry has `Evidence:` with one or more refs in backticks, separated
  by commas. A ref is a source `path:line` that exists under `{source}`, or a
  rule id `VR-` plus ten hex digits from `rules/view-rules.json`. A ref that
  does not resolve fails `check`.
- A defect is an agent judgment: state it as one (`_(inferred)_`) and cite
  the lines that show it. Do not list a style preference.
- For a committed credential write the key name and `path:line` only. Never
  write, quote or paraphrase the value. `check` fails the file if it holds a
  literal from a credential key (`password`, `secret`, `token`, `apiKey`,
  `sharedKey`) of the source's config.
- An item listed under `Defects` or `Dead code` must not be cited as intended
  behavior by any capability spec. The ids and `path:line` you list here are
  what `check` compares against.

## Do not

- Do not list behavior the product should have. That is a capability spec.
- Do not write fixes, port plans, XP8 or React4XP advice, or estimates.
- Do not edit any file outside `{sidecar}/reports/do-not-port.md`.
- Do not run graft, graphify, Serena onboarding or `git` writes in the source.
- Do not report done until `extractkit check --out {sidecar}` is clean.

Then run:

```bash
extractkit check --out {sidecar}
```
