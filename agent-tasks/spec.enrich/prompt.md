# Task spec.enrich: rewrite spec and use-case prose

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
- The kit extracts and scores. It never infers. Anything you add beyond an
  extracted fact is marked `_(inferred)_` and keeps an `Evidence:` line.
- Migration means a mapped, spec-ready component structure. It does not
  mean converting code to another stack.
- Never pass `--allow-production`, and use `--force` on `promote` only when
  the operator says so.

The kit writes behavior text from extracted facts only and never infers. Rewrite
the prose of a `{sidecar}/spec-kit/specs/*/spec.md` FR or a
`{sidecar}/use-cases/*.md` journey so it reads better, under this contract:

- Every FR keeps its `Acceptance:` bullets and its `Evidence:` line. Do not
  drop or reword a `file:line`, map id, `runtime:` or `baseline:` ref.
- Every sentence you add beyond the extracted facts ends with `_(inferred)_`,
  and the paragraph that holds it is followed by (or contains) an
  `Evidence:` line.
- Add no port plan, XP8 advice, or stack choice. Those stay out of
  `spec-kit/` (as-is).
- Run `extractkit check --out {sidecar}` afterwards. It fails an FR without
  an `Evidence:` line and an `_(inferred)_` paragraph without one.

Work in this order, and stop when the specs read well or the time runs short:

1. FRs that say "no behavior was extracted for it". Read the component's
   template, controller and descriptor at the cited paths and state what it
   renders and when, each sentence ending with `_(inferred)_`.
2. FRs whose acceptance is only a field list. Say in one or two sentences
   what the content type or component is for and who uses it.
3. The `use-cases/*.md` journeys of the same contexts.

`business/BUSINESS.md`, when it exists, gives the business names to use.

Last, after every spec and use-case edit, write
`{sidecar}/reports/spec-enrich.md`: an H1 `# Spec enrich`, then one bullet per
file you rewrote with the FR numbers you changed. The task counts as done
while this report is newer than every `spec.md`.

This task is optional. It never blocks the agent phase. Re-running
`spec.kit` rewrites the specs from the maps, so enrich after the last run of
that slot. `extractkit headless` runs it after the required tasks unless it
gets `--no-enrich`.
