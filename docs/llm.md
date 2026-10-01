# LLM instructions

For an agent that reads these docs and drives `extractkit`. Follow it as a
procedure. Facts about flags and files are in [CLI](cli.md),
[steps](steps.md) and [output](output.md); this page says what to do with
them.

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

## Command sequence

Run the phases in order. Each command ends with a `next` block; paste it
instead of rebuilding the command.

### 1 Preflight

```bash
extractkit deps --profile enonic
extractkit doctor --profile enonic --source <legacy>
```

`deps` runs every probe. `doctor --source` adds the target's readiness:
Serena onboarding, a Graphify index (both must pass) and a graft index (a
warning).

### 2 Static

```bash
extractkit run --profile enonic --source <legacy> --until static
extractkit status --source <legacy>
```

This writes the template inventory, the component map and the OpenAPI
harvest. Use `--profile enonic` for any stack that has no adapter of its
own: `core` cannot run alone, and `php` refuses on purpose.

### 3 CMS (optional)

<!-- markdownlint-disable MD013 -->
```bash
extractkit resume --profile enonic --source <legacy> --branch draft --storage-state <state.json>
```
<!-- markdownlint-enable MD013 -->

Local or review XP only. Skip it with `--from merge` in the next phase.

### 4 Merge and 5 Synthesis

<!-- markdownlint-disable MD013 -->
```bash
extractkit run --profile enonic --source <legacy> --out <sidecar> --from merge --until synthesis
```
<!-- markdownlint-enable MD013 -->

Merge also writes `rules/`. Synthesis cites the rules in the specs.

### 6 Check and 7 Promote

```bash
extractkit check --out <sidecar>
extractkit promote --source <legacy> --out <sidecar>
```

Promote only when the operator asks.

## Exit codes and `next`

<!-- markdownlint-disable MD013 -->
| Result | Do |
| --- | --- |
| Exit 0 and a `next` block | Run that block, or stop if the operator asked for less |
| Exit 0, `or continue without CMS` alternative | Pick the CMS line only when a local or review XP and a storage state exist; otherwise the offline line |
| Exit 1 with `error:` and `fix:   $ <command>` | Run the fix command. It is your own command with the missing flag added |
| Exit 1 with a prose `fix:` | Do what it says, or report it to the operator when it needs a decision |
| `check` exit 1 | Fix each listed problem at its source, re-run the slot that writes the file, then `check` again |
| Exit 2 | A wrong flag or command. Read `--help`; do not retry blindly |
<!-- markdownlint-enable MD013 -->

## Failures and fixes

<!-- markdownlint-disable MD013 -->
| Symptom | Cause | Fix |
| --- | --- | --- |
| `BROKEN` in `deps` | The tool is on PATH but its probe failed (for example `graphify` with a missing package) | Report the printed `fix:`; reinstall is the operator's call |
| `serena onboarding` MISSING | No `.serena/project.yml` or no memory file | Ask the operator to onboard the project in an agent with Serena |
| `graphify index` MISSING | No `graphify-out/graph.json` | Ask the operator to run `/graphify .` in the source |
| `graft index` warning | No `graft/` | Optional. `map.code` skips until the operator runs `graft build` |
| `profile 'core' has unbound required adapters` | `core` has no stack adapters | Use `enonic` (or `as`) |
| `enonic.cms requires --branch` | The slice includes CMS | Add `--branch draft`, or stop at `--until static` |
| a production host is refused | The URL is not local or review | Use a local or review XP; never override |
| `promote` refuses | A destination git cannot restore | Commit or stash it. `--force` only on the operator's word |
| `template … maps to no component surface` | A surface was removed from `map/component-map.json` | Re-run `maps.normalize`, never edit the map |
| `component … is not spec-ready` | A `template` block lost a required key | Re-run `maps.normalize` |
| `business rule VR-… is not cited` | A business rule is in no spec FR and not dropped | Re-run `spec.kit`; if the operator says the rule is dropped, set `out-of-scope: yes` in `rules/review.md` |
<!-- markdownlint-enable MD013 -->

## Naming the rules

The kit extracts every rule in the view layer with `path:line` and scores it.
It does not know what a rule means. You name it. An analyst confirms it.

Step 1: Open `rules/RULES.md`. Read the coverage line first. If files were
skipped, tell the operator which and why before going on.

Step 2: Open `rules/review.md`. Each business rule is a checkbox with
`name:`, `intent:` and `out-of-scope:` lines.

Step 3: For each rule, read the source at the `path:line` it cites. Do not
rely on the expression alone.

Step 4: Write `name:` as a short label and `intent:` as one sentence about
the business condition. End both with `_(inferred)_`.

Step 5: For each divergent group in `rules/RULES.md`, name every copy and say
nothing about which one is right. Do not pick a winner. The group is already
an open question in the spec, and the analyst answers it.

Step 6: Re-run the merge and synthesis slice so the names reach
`rules/view-rules.json`, `rules/RULES.md` and the specs. Ids carry your edits
over; an id that vanished is listed under `Removed`.

<!-- markdownlint-disable MD013 -->
```bash
extractkit run --profile enonic --source <legacy> --out <sidecar> --from merge --until synthesis
extractkit check --out <sidecar>
```
<!-- markdownlint-enable MD013 -->

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
