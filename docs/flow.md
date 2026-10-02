# Flow

How extractkit moves from a legacy checkout to a sidecar, then optionally
back into the checkout. Commands and artifacts are named as the CLI prints
them.

## Operator path

Install once with `./extractkit install` in the kit repo, then work from the
legacy checkout, in an agent session opened there. The install copies the kit
into your home, so the kit checkout can be deleted afterwards, and the CLI
refuses to run an extract from the kit repo.

![Install and where to run](diagrams/install-layout.png)

`deps` and `doctor --source` repeat the install and suggest
`run --until static`. `doctor --source` first checks the target's Serena
onboarding and Graphify index, and prints the stack it would detect. A run
then starts with the `context` phase: it detects the stack, records which
folders no default-branch build names, and writes the overlay `context/profile.yaml`
that the later phases compose on top of the stack profile (details in
[CLI](cli.md#context)). No client profile ships in the kit. After that,
`status` (alias `next`) is the map: every phase is done, current, or
pending. The current phase's missing marker decides the command.

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

In `complete` and `offline`, a pending required agent task (`context.exclude`,
`context.live_config`, `rules.name`, `business`) makes the agent phase
current. The `next` block then offers `agent next`, with `check` as the
alternative line; `offline` shows its CMS alternative again once the required
tasks are done. Two of those tasks are ready earlier. Once the static phase is
done and `context.exclude` is undecided, the `next` block in `cms` and
`other:<slot>` offers `agent show context.exclude` first, with the pipeline
route as the alternative; `context.live_config` is ready after the CMS slot.

`promote` is explicit. After a clean promote, `next` is `git status` in the
checkout. The guard is in [CLI](cli.md#promote-guard).

## Headless path

`extractkit headless` walks the same phases with no human. It starts an agent
CLI for the preflight and for each agent task, stops at the first failed
stage, and ends with exit 0 (every stage passed), 1 (a stage failed) or 3 (a
task is blocked and a person must look). The stages, the agent loop and
the blocker protocol are in [Headless](headless.md#the-stages).

![Headless pipeline](diagrams/headless-pipeline.png)

## Phases

`profiles/core.yaml` groups the pipeline. `--from`, `--until`, and `step`
accept a phase id or number, or a slot or plugin id. Phases 1, 2, 7, 8, and 9
are commands: passing them to `--from` / `--until` / `step` is refused.

![Phases](diagrams/phases.png)

Slot contents and done-markers are in [steps](steps.md). Command flags
are in [CLI](cli.md#phases). The agent phase runs prompts stored as data in
`agent-tasks/`; the kit lists them and checks what they write, and a skill
(`extract-agentic`) does the work.

## Inputs and outputs

Every phase, what it cannot run without, what it uses when present, and
what it leaves behind. Paths in **Output** are relative to the sidecar
unless they say `<checkout>`. An optional input that is absent never fails
the phase; it only makes the output thinner.

<!-- markdownlint-disable MD013 -->
| # | Phase | Required input | Optional input | Output |
| --- | --- | --- | --- | --- |
| 1 | `preflight` | Python 3.12+ with PyYAML and jsonschema; with `--source`: the checkout's Serena onboarding (`.serena/`) and Graphify index (`graphify-out/`) | graft index (`graft/`, a warning when absent); `--profile` (which deps to probe) | **No sidecar.** The install check, and a report with the stack it would detect and the build scope |
| 2 | `context` | `--source`; one stack marker unless `--profile` is given | `--profile` (skips detection); `--exclude`; `<checkout>/.extractkit/profile.yaml` | **`context/build-scope.json`**, **`context/profile.yaml`** (the overlay) |
| 3 | `static` | `--source`; the overlay from phase 2 (`run` writes it when missing) | `graft/`, `graphify-out/` (`map.code`, `map.semantic`); `--exclude`; the `exclude` decided by `context.exclude` | **`inventory/static.json`**, `inventory/controllers.json`, `inventory/templates.json`, **`map/*.json`**, **`integrations/openapi.yaml`**, `integrations/swagger-ui/`, `MANIFEST.yaml` |
| 4 | `cms` (optional phase) | A local or review XP; `--branch draft\|master`; `--storage-state` (a Playwright login) | `--guillotine`, `--xp-host`, `--project` (default `http://localhost:8080`, project `en`); `--cms-key` (default `/en`); `--configenv`; `--round2`; the overlay's `live_config`; `playwright-cli` and `--site-url` for `inventory.baseline` | **`inventory/runtime.json`**, `inventory/live-config-candidates.json`, `inventory/content-volume.{json,md}`, `x-production-endpoints` in `openapi.yaml`; `baseline/` (optional slot) |
| 5 | `merge` | Phase 3 output | `inventory/runtime.json` (without it, surfaces stay `unverified-live`) | **`map/bounded-contexts.json`**, `inventory/merge-report.md`, **`rules/`**, `docs/harvest/` |
| 6 | `synthesis` | Phase 5 output | `--tasks` (Spec Kit `tasks.md`) | **`spec-kit/`**, `product/PRODUCT.md`, `design/DESIGN.md`, `use-cases/`, `docs/technical/`, `docs/guide/`; `reports/xp8-compat.md` (optional slot) |
| 7 | `agent` | An AI assistant that runs the task prompts; each task's inputs (below) | `spec.enrich`, `spec.review` | The overlay's **`exclude`** and **`live_config`**, **`rules/review.md`** names, **`business/BUSINESS.md`**; `reports/spec-review.md` (optional) |
| 8 | `check` | `--out` of a sidecar with phase 3 done (`MANIFEST.yaml`, the four `map/*-map.json` / `content-model.json` files, `inventory/static.json`, `integrations/openapi.yaml`) | Every later file is checked only when it exists | **No file.** Exit 0, or exit 1 with every problem listed |
| 9 | `promote` | `--source` as a git work tree whose destinations git can restore | `--out` (default: latest sidecar); `--force` | **`<checkout>/.specify/memory/constitution.md`**, **`<checkout>/specs/<ctx>/spec.md`**, `PRODUCT.md`, `DESIGN.md`, `.impeccable/design.json`, `BUSINESS.md` |
<!-- markdownlint-enable MD013 -->

The agent tasks, in the order `agent next` offers them. A task is offered
only when every file in **Reads** exists; its **Re-run** carries the result
into the later phases (add `--source`, `--out` and the CMS flags of the
earlier run).

<!-- markdownlint-disable MD013 -->
| Task | Required | Ready after | Reads | Output | Re-run |
| --- | --- | --- | --- | --- | --- |
| `context.exclude` | Yes, while the build scope leaves folders undecided | `inventory.integrations` (phase 3) | `context/build-scope.json` | **`exclude`** in `context/profile.yaml` | `run --from static --until synthesis` (`--until inventory.integrations` without CMS flags) |
| `context.live_config` | Yes, after a live harvest; done without one | `inventory.runtime` (phase 4) | `inventory/runtime.json`, `inventory/live-config-candidates.json`, `integrations/openapi.yaml` (the prompt also reads `site/site.xml` in the checkout; it does not gate the task) | **`live_config`** in `context/profile.yaml` | `step inventory.runtime` |
| `rules.name` | Yes | `rules.view` (phase 5) | `rules/RULES.md`, `rules/review.md`, `rules/view-rules.json` | **names and intents** in `rules/review.md` | `run --from merge --until synthesis` |
| `business` | Yes | `spec.kit` (phase 6) | `map/bounded-contexts.json`, `use-cases/`, `rules/RULES.md`, `rules/view-rules.json`, `map/content-model.json`, `map/route-map.json`, `product/PRODUCT.md` | **`business/BUSINESS.md`** | none |
| `spec.enrich` | No | `spec.kit` | `spec-kit/specs/`, `use-cases/` | prose of `spec-kit/specs/` and `use-cases/` | none |
| `spec.review` | No | `spec.kit` | `spec-kit/specs/`, `rules/view-rules.json`, `map/bounded-contexts.json`; `business/BUSINESS.md` when present | **`reports/spec-review.md`** (never promoted) | none |
<!-- markdownlint-enable MD013 -->

The expected end state of a full run: `check` exits 0, `agent next`
reports no required task pending, and `promote` has copied the Spec Kit
files, `PRODUCT.md`, `DESIGN.md` and `BUSINESS.md` into the checkout. A
run without CMS reaches the same end state with every live surface
`unverified-live`.

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
