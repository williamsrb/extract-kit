---
name: extract-legacy
description: >
  Walk the 99x-extract-kit pipeline for a legacy checkout. Use when running
  extractkit, resuming an extract sidecar, promoting Spec Kit files, or
  deciding the next skill (impeccable, CMS survey). Not for XP8/React4XP ports.
---

# Extract a legacy spec

Kit: this repo (`./extractkit`). Plan and PRD live under `~/.agents/`, not in
the kit tree.

## Rules

- Source is read-only until the operator runs `extractkit promote --apply`.
- Never edit source `.gitignore` or `.git/`. Never run `graft build` or graphify
  inside the source.
- Dry-run first. `--apply` writes `<source>/.extract/<run-id>/`.
- Production CMS is deny-by-default. Local (`localhost` / `127.0.0.1`) or
  review (`*.k8s.seeds.no`) only.
- Spec Kit mode is **as-is**. Do not write port plans, `DECISIONS.md`, or
  `IMPLEMENTATION.md`.
- PHP profile is empty on purpose. Do not guess Laravel/Symfony parsers.

## Graph

1. `extractkit doctor` and `extractkit deps --profile enonic`
2. Static: `extractkit run --profile enonic --source <legacy> --apply
   --until inventory.integrations`
3. `extractkit next --source <legacy>` — first missing artifact + skill
   name
4. Optional live CMS (Enonic profile only): `extractkit step enonic.cms
   ... --branch draft --storage-state <file> --guillotine <url>
   --cms-key /en`. Writes `inventory/runtime.json` plus XP7 extras
   (`content-survey*.json`, `page-templates.json`). Resolve order and
   the 3-per-type cap are Enonic-only; do not invent them for PHP.
5. Maps, docs, spec-kit: `extractkit resume --profile enonic --source
   <legacy> --apply --until spec.kit`
6. `extractkit check --out <sidecar>`
7. Promote only when asked: `extractkit promote --source <legacy>
   --out <sidecar> --apply`

`next` prints a skill of `impeccable` when PRODUCT/DESIGN are missing, and
`extract-legacy` for deterministic kit steps (including CMS HTTP).

Impeccable `init` / `document` may replace the as-is PRODUCT/DESIGN the kit
already wrote. Do not invent an XP8 visual world.

## Artifacts

See `docs/output.md`. Constitution promote path is
`.specify/memory/constitution.md`.
