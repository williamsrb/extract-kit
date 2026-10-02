# Task rules.name: name the view-layer business rules

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

The kit extracts every rule in the view layer with `path:line` and scores it.
It does not know what a rule means. You name it. An analyst confirms it.

## Procedure

Step 1: Open `{sidecar}/rules/RULES.md`. Read the coverage line first. If
files were skipped, tell the operator which and why before going on.

Step 2: Open `{sidecar}/rules/review.md`. Each business rule is a checkbox
with `name:`, `intent:` and `out-of-scope:` lines.

Step 3: For each rule, read the source at the `path:line` it cites, under
`{source}`. Do not rely on the expression alone.

Step 4: Write `name:` as a short label and `intent:` as one sentence about
the business condition. End both with `_(inferred)_`.

Step 5: For each divergent group in `rules/RULES.md`, name every copy and say
nothing about which one is right. Do not pick a winner. The group is already
an open question in the spec, and the analyst answers it.

Step 6: Re-run the merge and synthesis slice so the names reach
`rules/view-rules.json`, `rules/RULES.md` and the specs. Ids carry your edits
over; an id that vanished is listed under `Removed`.

```bash
extractkit run --profile {profile} --source {source} --out {sidecar} \
  --from merge --until synthesis
extractkit check --out {sidecar}
```

A rule moves through three stages: `extracted` (the kit), `named` (you),
`confirmed` (the analyst ticks `[x]`).

## Do not

- Do not tick `[x]` in `rules/review.md`. Only the analyst confirms.
- Do not set `out-of-scope: yes` unless the operator told you to.
- Do not edit `rules/view-rules.json`, `rules/RULES.md`, `rules/literals.md`
  or any map or inventory file. Re-run the slot instead.
- Do not change a rule id, delete a rule entry, or rename a file.
- Do not invent a rule, an operand or a literal that is not in the source.
- Do not write port plans, `DECISIONS.md` or `IMPLEMENTATION.md`.
- Do not run graft, graphify, Serena onboarding or `git` writes in the source.
- Do not edit the source `.gitignore` or `.git/`.
- Do not skip `check`, and do not report a clean extract while it lists
  problems.
