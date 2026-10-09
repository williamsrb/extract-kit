# Task domain.behavior: write the domain behavior of each business capability

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

Write one file `{sidecar}/domain/<capability-id>.md` for every capability in
`{sidecar}/business/capabilities.json`. A spec writer reads these files to
learn what the product does when a booking changes state, a price is worked
out, an email is sent or a job runs. The legacy source is not their input:
you are. Write what the code does, not what the structure of the code is.

## Inputs

Paths are under `{sidecar}`.

- `business/capabilities.json`: the capabilities (`id`, `title`, optional
  `modules`). One output file per entry.
- `business/BUSINESS.md`: what each capability is for.
- `domain/packet/INDEX.json` and `domain/packet/<module>.json`: for each
  source module, what it exports, which platform and library calls it makes,
  which HTTP requests it sends, which request inputs, responses and auth
  checks its services have, which jobs, listeners and external callers start
  it, and which rules sit in it. Each fact carries `path:line`. This is a
  map to the code, not the code.
- `rules/view-rules.json`: rules with `scope: server` are the status
  comparisons, amount arithmetic, date math and role checks of the server
  code. A rule with `dead: true` never runs; do not describe it as behavior.
- `integrations/openapi.yaml`: inbound services with inputs, auth and
  response codes; outbound calls with the line that makes them.
- `map/route-map.json`: `cron`, `init` and `external-caller` surfaces with
  their schedule source.

You map modules to capabilities: a capability's `modules` list is a hint, not
a rule. Open the packets of the modules you need, then read the source at the
`path:line` a fact cites, under `{source}`, to work out what the code does. A
packet is bounded on purpose; the source is where the behavior is.

## Output

Each `domain/<capability-id>.md` starts with `# <capability title>` and has
exactly these H2 sections, in this order, and no other H2:

- `## State machines`: the states of each record the capability owns, each
  transition (from, to), and what triggers it (a request, a callback, a job,
  an event). One bullet per transition. Every value of a status the packets
  and `scope: server` rules compare or assign gets a bullet: a transition
  into it, or `never set in the extracted code` when only a comparison reads
  it.
- `## Formulas`: each calculation worked out end to end: inputs, the steps in
  order, units, currency, rounding and the order of operations. One bullet
  per formula. Cover every exported function of the capability's modules
  that computes an amount, a price, a total, a deposit, a discount, a rate or
  a number of days, and each variant of one calculation (for example a full
  and a lite version of the same price), as its own bullet. Write every
  condition with the operator the code uses (`==`, `>=`, `>`), and every
  minimum, maximum, cap, floor and rounding step the code applies, even one
  that only matters for small amounts. For a lookup or a conversion, name the
  source and the target in the order the code passes them.
- `## External calls`: each system the capability calls or is called by: the
  direction, the operation, the message fields sent and read, the success and
  failure outcomes. Say which environment a documented URL came from when the
  extract marks one (`env`); never present a review or local value as
  production.
- `## Emails`: each email: what triggers it, who receives it, the template
  key and the fields it fills.
- `## Scheduled and external jobs`: each cron job, task and external caller:
  the schedule and where it comes from (a config key, a crontab line, a
  literal), what it runs, and what it changes.
- `## Idempotency and retries`: what happens when the same request, callback
  or job runs twice, and every retry, back-off or lock.

## Evidence contract

- Every bullet ends with `Evidence:` and one or more refs in backticks,
  separated by commas. Every ref is a source `path:line` that exists under
  `{source}`. A bullet whose ref does not resolve fails `check`.
- State what the code does. Add nothing the code does not do. End any claim
  you worked out rather than read with `_(inferred)_`, in the same bullet.
- When a section has nothing for this capability, write one plain sentence
  (not a bullet): `None found in the extracted module facts.`
- Describe live behavior only. A rule or branch the packet marks `dead`, or a
  function marked `unreferenced`, is not behavior: leave it out. It belongs
  to `donotport`.
- Behavior that is wrong, unsafe or missing in the source is written as the
  code does it, once, and `donotport` lists it. Do not repair it in prose.

## Do not

- Do not write port plans, XP8 or React4XP advice, stack choices, estimates
  or `DECISIONS.md` / `IMPLEMENTATION.md` content. This is as-is.
- Do not copy a secret value, key or token from the source. Name the key and
  `path:line`, never the value.
- Do not write call graphs: no "Calls `X`" or "Exports `Y`" bullets. A bullet
  says what happens to the product's data.
- Do not edit any file outside `{sidecar}/domain/`. Do not edit
  `domain/packet/`, maps, inventories, rules or specs.
- Do not run graft, graphify, Serena onboarding or `git` writes in the source.
- Do not report done until `extractkit check --out {sidecar}` is clean.

Then run:

```bash
extractkit check --out {sidecar}
```
