# Flow

How extractkit moves from a legacy checkout to a sidecar, then optionally
back into the checkout. Commands and artifacts are named as the CLI prints
them.

## Operator path

Install once with `./extractkit install` in the kit repo, then work from the
legacy checkout, in an agent session opened there. `deps` and
`doctor --source` repeat the install and suggest `run --until static`.
`doctor --source` first checks the target's Serena onboarding and Graphify
index. After that, `status`
(alias `next`) is the map: every phase is done, current, or pending. The
current phase's missing marker decides the command.

![Operator path](diagrams/operator-path.png)

A full Enonic run without `--until` includes CMS and needs `--branch` and
`--storage-state`. The skip path is the offline route in the
[usage guide](usage.md#static-extract).

<!-- markdownlint-disable MD013 -->
| Status | Meaning | Next |
| --- | --- | --- |
| `cms` | First incomplete slot is `inventory.runtime`, and more slots remain | `resume` with CMS flags, or `run --from merge` |
| `offline` | Only CMS is missing | `agent next` while a required agent task is pending, then `check`, or add CMS and rebuild merge and synthesis |
| `complete` | Every slot is done | `agent next` while a required agent task is pending, then `check` |
| `other:<slot>` | First incomplete slot is not CMS | `resume` from that slot |
<!-- markdownlint-enable MD013 -->

Optional slots (`inventory.baseline`, `report.compat`) do not change
these states. `status` marks a phase `optional, not captured` and prints
the `step` command that would add it.

In `complete` and `offline`, a pending required agent task (`rules.name`,
`business`) makes the agent phase current. The `next` block then offers
`agent next`, with `check` as the alternative line; `offline` shows its CMS
alternative again once the required tasks are done.

`promote` is explicit. After a clean promote, `next` is `git status` in the
checkout. The guard is in [CLI](cli.md#promote-guard).

## Phases

`profiles/core.yaml` groups the pipeline. `--from`, `--until`, and `step`
accept a phase id or number, or a slot or plugin id. Phases 1, 6, 7, and 8
are commands: passing them to `--from` / `--until` / `step` is refused.

![Phases](diagrams/phases.png)

Slot contents and done-markers are in [steps](steps.md). Command flags
are in [CLI](cli.md#phases). The agent phase runs prompts stored as data in
`agent-tasks/`; the kit lists them and checks what they write, and a skill
(`extract-agentic`) does the work.

## Sidecar lineage

The checkout is read-only until `promote`. Default `--out` is
`<source>/.extract/<run-id>/`. Maps and OpenAPI stay in the sidecar.

![Sidecar lineage](diagrams/sidecar-lineage.png)

`reports/spec-review.md` is optional agent output (the `spec.review` task).
It stays in the sidecar and `promote` never copies it.

`runtime.json` is optional. It comes from a local or review XP, not from
scanning the checkout.

Without it, `maps.merge` leaves page, layout, part, and macro as
`unverified-live`. With it, those kinds become `live`, `dead`,
`unobserved`, or `conditional`. A component the survey did not sample is
`dead` only when the usage probe counted exactly 0.

`controllers.json` comes from the static phase. `maps.normalize` copies
each controller's entry into its surface's `behavior`.

`templates.json` also comes from the static phase, for every profile.
`maps.normalize` turns each template file into a `component` or `partial`
surface, and joins an Enonic descriptor with its view into one surface, so a
`--until static` run already has a spec-ready component map. `rules.view`
runs in the merge phase after `maps.merge` and writes `rules/`. `spec.kit`
and `use_cases` cite its rule ids; `check` fails a business rule that no
spec cites.

CMS also patches `openapi.yaml` `x-production-endpoints`. Those URLs are
never fetched.

The two optional slots stay in the sidecar. `inventory.baseline` takes
page paths from `runtime.json` and writes `baseline/`.
`report.compat` reads `static.json` and `controllers.json` and writes
`reports/xp8-compat.md`. `promote` copies neither.

What each file is, and the promote map, is in [output](output.md).
