---
name: extract-legacy
description: >
  Walk the 99x-extract-kit pipeline for a legacy checkout. Use when running
  extractkit, resuming an extract sidecar, promoting Spec Kit files, or
  deciding the next skill (impeccable, CMS survey). Not for XP8/React4XP ports.
---

# Extract a legacy spec

Kit: this repo (`./extractkit`). Plan and PRD live under `~/.agents/`, not
in the kit tree.

## Rules

- Source is read-only until the operator runs `extractkit promote`.
  Promote refuses files git cannot restore; pass `--force` only when the
  operator says so.
- Never edit source `.gitignore` or `.git/`. Never run `graft build` or
  graphify inside the source.
- Every command writes on the first call. `run` writes
  `<source>/.extract/<run-id>/`. Each run ends with a `next` block: the
  command to run next.
- Production CMS is refused. Local (`localhost` / `127.0.0.1`) or review
  (`*.k8s.seeds.no`) only.
- Spec Kit mode is as-is. Do not write port plans, `DECISIONS.md`, or
  `IMPLEMENTATION.md`.
- PHP profile is empty on purpose. Do not guess Laravel/Symfony parsers.

## Graph

Diagrams: `docs/flow.md` and `docs/diagrams/*.png`.

1. `extractkit doctor` and `extractkit deps --profile enonic`
2. Static: `extractkit run --profile enonic --source <legacy> --until static`
3. `extractkit status --source <legacy>` — every phase as done / current /
   pending, the current phase's missing artifacts, and skill names
4. Optional live CMS (Enonic profile only):

   `extractkit step enonic.cms ... --branch draft --storage-state <file>
   --guillotine <url> --cms-key /en`

   Writes `inventory/runtime.json` plus XP7 extras
   (`content-survey*.json`, `page-templates.json`).

   Resolve order and the 3-per-type cap are Enonic-only. Do not invent
   them for PHP.
5. Merge and synthesis: `extractkit resume --profile enonic --source
   <legacy> --until synthesis` (or, without CMS, `extractkit run --profile
   enonic --source <legacy> --out <sidecar> --from merge --until synthesis`)
6. `extractkit check --out <sidecar>`
7. Promote only when asked: `extractkit promote --source <legacy>
   --out <sidecar>`

`status` prints a skill of `impeccable` when PRODUCT/DESIGN are missing,
and `extract-legacy` for deterministic kit steps (including CMS HTTP).

Impeccable `init` / `document` may replace the as-is PRODUCT/DESIGN the
kit already wrote. Do not invent an XP8 visual world.

## Artifacts

See `docs/output.md`. What each slot reads, writes, and skips is in
`docs/steps.md`. Constitution promote path is
`.specify/memory/constitution.md`.
