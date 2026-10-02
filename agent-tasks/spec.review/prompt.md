# Task spec.review: review the generated specs

Sidecar: `{sidecar}`
Source (read-only): `{source}`
Profile: `{profile}`
Run: `{run_id}`

## Invariants

- Run from the legacy checkout, in an agent session opened there, with
  `extractkit` on PATH (`./extractkit install` in the kit repo puts it
  there; preflight repeats the install). Do not drive an extract from a
  session opened in the kit repo: Serena, Graphify and graft act on the
  session's folder, so they would onboard and index the kit. If you are in
  the kit repo, tell the operator to open the checkout and stop.
- The source checkout is read-only. Every run writes only
  `<source>/.extract/<run-id>/`. Only `promote` writes into the checkout, and
  only when the operator asked for it.
- There is no dry run. Every command writes on its first call.
- The profile is not yours to write. The only profile file an agent task
  edits is `<sidecar>/context/profile.yaml`, and only the key the task names.
  `<source>/.extractkit/profile.yaml` is the operator's override: read it,
  never create or edit it.
- The kit never runs Serena, graphify or graft. It detects them and prints
  the fix. Do not run them inside the source yourself; tell the operator and
  wait.
- Production CMS hosts are refused. Use a local or review XP only.
- The kit extracts and scores. It never infers. Anything you add beyond an
  extracted fact is marked `_(inferred)_` and keeps an `Evidence:` line.
- Migration means a mapped, spec-ready component structure. It does not
  mean converting code to another stack.
- Never pass `--allow-production`, and use `--force` on `promote` only when
  the operator says so.

Review `{sidecar}/spec-kit/specs/*/spec.md` for meaning, and write one findings
report. The kit proves structure with `extractkit check`; you check what it
cannot: whether the specs are right. Read the source (`{source}`) wherever a
spec cites it.

## What to review

1. Does an FR say what the code at its cited `file:line` does? Flag a misread
   or an overstated claim.
2. Are the specs split along the right contexts? Compare them with
   `{sidecar}/map/bounded-contexts.json`.
3. Are there duplicate or conflicting FRs across specs? Compare rule FRs with
   `{sidecar}/rules/view-rules.json`.
4. Does any spec contradict `{sidecar}/business/BUSINESS.md`? If that file is
   absent (the `business` task has not run), skip this point.
5. Is there behavior in the source that no spec covers?
6. Is a spec clear enough to hand to `/speckit.plan`? Flag vague or untestable
   `Acceptance:` bullets.

Do not repeat what `extractkit check` already reports (a missing `Evidence:`
line, an unresolved ref, an `_(inferred)_` paragraph without evidence). Run
it first and skip those.

## Read-only

Write only `{sidecar}/reports/spec-review.md`. Do not edit anything under
`{sidecar}/spec-kit/`, `{sidecar}/use-cases/`, `{sidecar}/business/` or
`{sidecar}/rules/review.md`. Re-running `spec.kit` rewrites the specs from the
maps, so edits would be lost and would put your inference into files that
hold extracted facts. Each finding says where the fix belongs instead.

## Report format

The file opens with the H1 `# Spec review`. Each finding is an H3
`### SR-<n>: <title>` (numbered from 1) followed by four lines:

- `Spec:` a `spec-kit/specs/<slug>/spec.md` path, optionally followed by an FR
  id.
- `Severity:` one of `high`, `medium`, `low`.
- `Fix in:` one of `extractor`, `rules/review.md`, `spec.enrich`, `source`.
- `Evidence:` at least one ref: a source `path:line`, a map id, a context id
  or a rule id.

A sentence of explanation may follow the four lines. Example:

```markdown
# Spec review

### SR-1: FR-3 states the wrong default

Spec: spec-kit/specs/news-list/spec.md FR-3
Severity: medium
Fix in: extractor
Evidence: src/main/resources/site/parts/news-list/news-list.js:42

The FR says the list shows 5 items; the code reads the default from config.
```

With no findings, write `No findings.` under the H1 and nothing else.

Run `extractkit check --out {sidecar}` afterwards. It validates this file's
format: the H1, the four fields, the allowed values, that `Spec:` exists and
that every `Evidence:` ref resolves. It never fails because of what you found.

This task is optional. It never blocks the agent phase and `promote` never
copies the report into the checkout.
