# Task spec.enrich: rewrite spec and use-case prose

Sidecar: `{sidecar}`
Source (read-only): `{source}`
Profile: `{profile}`
Run: `{run_id}`

## Invariants

- The source checkout is read-only. Every run writes only
  `<source>/.extract/<run-id>/`. Only `promote` writes into the checkout, and
  only when the operator asked for it.
- There is no dry run. Every command writes on its first call.
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

This task is optional. It never blocks the agent phase. Re-running
`spec.kit` rewrites the specs from the maps, so enrich after the last run of
that slot.
