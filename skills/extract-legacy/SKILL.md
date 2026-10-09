---
name: extract-legacy
description: >
  Walk the extractkit pipeline for a legacy checkout. Use when running
  extractkit, resuming an extract sidecar, promoting Spec Kit files, or
  deciding the next skill (impeccable, CMS survey). Not for XP8/React4XP ports.
---

# Extract a legacy spec

Run from the legacy checkout, in a session opened there, with `extractkit`
on PATH. If `extractkit` is not found, ask the operator to run
`./extractkit install` once in a kit checkout. The install copies the kit
out of the checkout, so the checkout can be deleted afterwards; to update,
run `./extractkit install` again from a fresh checkout. A session opened in
the kit repo cannot prepare Serena or Graphify for the target: tell the
operator to open the checkout instead. Plan and PRD live under `~/.agents/`,
not in the kit tree.

Read `~/.local/share/extractkit/docs/llm.md` first. It holds the invariants,
the command sequence per phase, what to do for each exit code and `next`
block, the failure table and the agent phase. This skill only adds what is
specific to a skill run.

## Rules

- Prefer `--json` on every command: one JSON document on stdout with `ok`,
  `error.code`, `error.fix_command` and `next_command.argv` an agent can act
  on without parsing text. The kit refuses to run from its own repo
  (`kit_workspace`): stop and ask for the legacy checkout.
- Source is read-only until the operator runs `extractkit promote`.
  Promote refuses files git cannot restore; pass `--force` only when the
  operator says so.
- Never edit source `.gitignore` or `.git/`. Never run `graft build` or
  graphify inside the source.
- Every command writes on the first call. `run` writes
  `<source>/.extract/<run-id>/`. Each run ends with a `next` block: the
  command to run next.
- Production CMS is refused. Local (`localhost` / `127.0.0.1`) or review
  (a suffix in `EXTRACTKIT_REVIEW_SUFFIXES`) only.
- Spec Kit mode is as-is. Do not write port plans, `DECISIONS.md`, or
  `IMPLEMENTATION.md`.
- PHP profile is empty on purpose. Do not guess Laravel/Symfony parsers.
- No client profile lives in the kit. Never create or edit
  `<source>/.extractkit/profile.yaml`; it is the operator's override. The
  only profile file an agent edits is `<sidecar>/context/profile.yaml`, and
  only through `context.exclude` and `context.live_config`.

## Graph

Diagrams live in the kit repo (`docs/diagrams/*.png`), not in the install.
Required and optional inputs and the output of every phase and agent task:
`~/.local/share/extractkit/docs/flow.md#inputs-and-outputs`.

1. `extractkit deps --profile enonic` and
   `extractkit doctor --source <legacy>` (Serena onboarding and a Graphify
   index must be ready; the operator fixes them). The `stack` row says what
   detection would pick; a `build scope` warning lists top-level folders no
   default-branch build names
2. Context and static: `extractkit run --source <legacy> --until static`.
   The `context` phase runs first on its own: it detects the stack (pass
   `--profile enonic` only when it finds no marker), writes
   `context/build-scope.json` and the overlay `context/profile.yaml`. An
   operator who already knows a folder is not the product can add
   `--exclude <folder>`; otherwise the `context.exclude` task decides
3. `extractkit status --source <legacy>` — every phase as done / current /
   pending, the current phase's missing artifacts, and skill names. While
   `context.exclude` is undecided its `next` block offers
   `extractkit agent show context.exclude`: invoke the `extract-agentic`
   skill for it before step 4, because the CMS and merge scans read what it
   excludes
4. Optional live CMS (Enonic profile only):

   Read the CMS How-tos first, in `~/.local/share/devkit/current/core/kb/implementation/`:
   `How-to-log-in-to-an-xp7-admin-and-keep-the-session.md` (login and storage
   state) and `How-to-traverse-an-xp7-cms-through-guillotine-and-content-studio.md`
   (traversal, what to pin).

   `extractkit step enonic.cms ... --branch draft --storage-state <file>
   --guillotine <url> --cms-key /en`

   Writes `inventory/runtime.json` plus XP7 extras
   (`content-survey*.json`, `page-templates.json`).

   Resolve order and the 3-per-type cap are Enonic-only. Do not invent
   them for PHP.
   After the CMS step, `inventory/live-config-candidates.json` lists the
   Site Config and Config Env keys that hold URLs or host maps. The
   `context.live_config` task (`extract-agentic`) writes the project's
   `live_config` rules from it, and its re-run repeats this step.
5. Merge and synthesis: `extractkit resume --source <legacy> --until
   synthesis` (or, without CMS, `extractkit run --source <legacy> --out
   <sidecar> --from merge --until synthesis`)
6. Agent phase (decide the context, name the rules, write `BUSINESS.md`):
   invoke the `extract-agentic` skill. It runs `extractkit agent next --out <sidecar>`
   until nothing is pending, then `extractkit check --out <sidecar>`
7. Promote only when asked: `extractkit promote --source <legacy>
   --out <sidecar>`

`status` prints a skill of `impeccable` when PRODUCT/DESIGN are missing,
`extract-agentic` for the agent phase, and `extract-legacy` for
deterministic kit steps (including CMS HTTP).

Impeccable `init` / `document` may replace the as-is PRODUCT/DESIGN the
kit already wrote. Do not invent an XP8 visual world.

## Spec enrich (optional, after `spec.kit`)

The prompt moved into the agent task registry. Run
`extractkit agent show spec.enrich --out <sidecar>` and follow it, through
the `extract-agentic` skill.

## Optional slots

- `inventory.baseline` (after `inventory.runtime`) captures desktop 1440 and
  mobile 390 screenshots, rendered HTML and the network list per surveyed
  page into `baseline/`. It needs the CMS flags (`--branch` at least),
  `playwright-cli` and `--storage-state`; without the last two it records a
  skip and `status` prints the command. Local or review hosts only;
  `--site-url` overrides the page base URL.
- `report.compat` (after `spec.kit`) writes `reports/xp8-compat.md`, a factual
  XP7 to XP8 list outside `spec-kit/`. `promote` ignores it.

## Artifacts

See `~/.local/share/extractkit/docs/output.md`. What each slot reads,
writes, and skips is in `~/.local/share/extractkit/docs/steps.md`.
Constitution promote path is `.specify/memory/constitution.md`.
