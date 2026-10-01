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

Merge also writes `rules/`. Synthesis cites the rules in the specs. The
next phase is the agent phase (6); `run` and `step` refuse it.

### 6 Agent

The kit stores each agent step as a prompt in `agent-tasks/<id>/`. It never
calls a model. After synthesis, `extractkit status` shows the agent phase as
current while a required task is pending.

```bash
extractkit agent list --out <sidecar>
extractkit agent next --out <sidecar> --json
extractkit agent show <id> --out <sidecar>
```

`agent next` names the first required task whose inputs exist. `agent show`
prints its prompt with the real sidecar and source paths, then the input and
output files. Do the task, run its `rerun` command when it declares one, run
`check`, and ask for the next task. Stop when `agent next` reports none
pending. The `extract-agentic` skill runs this loop.

<!-- markdownlint-disable MD013 -->
| Task | Writes | Done when |
| --- | --- | --- |
| `rules.name` | `rules/review.md` (names and intents) | no business rule in `rules/view-rules.json` is still `extracted` |
| `business` | `business/BUSINESS.md` | the file exists |
| `spec.enrich` | `spec-kit/specs/`, `use-cases/` (prose only) | optional, never blocks |
<!-- markdownlint-enable MD013 -->

`rules.name` needs a re-run: the names reach `rules/view-rules.json` only
when you run the merge and synthesis slice. The procedure and the analyst
gates are in each task's prompt. The agent never ticks `[x]` in
`rules/review.md`.

### 7 Check and 8 Promote

```bash
extractkit check --out <sidecar>
extractkit promote --source <legacy> --out <sidecar>
```

`check` validates `business/BUSINESS.md` only when it exists. Promote only
when the operator asks.

## Exit codes and `next`

<!-- markdownlint-disable MD013 -->
| Result | Do |
| --- | --- |
| Exit 0 and a `next` block | Run that block, or stop if the operator asked for less |
| Exit 0, `or continue without CMS` alternative | Pick the CMS line only when a local or review XP and a storage state exist; otherwise the offline line |
| Exit 1 with `error:` and `fix:   $ <command>` | Run the fix command. It is your own command with the missing flag added |
| Exit 1 with a prose `fix:` | Do what it says, or report it to the operator when it needs a decision |
| Exit 0, `Agent is next` | Run `extractkit agent next`, or the `or skip to check` line when the operator asked for less |
| `check` exit 1 | Fix each listed problem at its source, re-run the slot that writes the file, then `check` again |
| Exit 2 | A wrong flag or command. Read `--help`; do not retry blindly |
<!-- markdownlint-enable MD013 -->

## Failures and fixes

<!-- markdownlint-disable MD013 -->
| Symptom | Cause | Fix |
| --- | --- | --- |
| `BROKEN` in `deps` | The tool is on PATH but its probe failed (for example `graphify` with a missing package) | Report the printed `fix:`; reinstall is the operator's call |
| `serena onboarding` MISSING | No `.serena/project.yml` or no memory file | Ask the operator to onboard the project in an agent with Serena |
| `graphify index` MISSING | No `graphify-out/graph.json` | Ask the operator to build a Graphify index in the source (the graphify skill, for example `/graphify .`) |
| `graft index` warning | No `graft/` | Optional. `map.code` skips until the operator runs `graft build` |
| `profile 'core' has unbound required adapters` | `core` has no stack adapters | Use `enonic` (or `as`) |
| `enonic.cms requires --branch` | The slice includes CMS | Add `--branch draft`, or stop at `--until static` |
| a production host is refused | The URL is not local or review | Use a local or review XP; never override |
| `promote` refuses | A destination git cannot restore | Commit or stash it. `--force` only on the operator's word |
| `template … maps to no component surface` | A surface was removed from `map/component-map.json` | Re-run `maps.normalize`, never edit the map |
| `component … is not spec-ready` | A `template` block lost a required key | Re-run `maps.normalize` |
| `business/BUSINESS.md … does not resolve` | An `Evidence:` ref is not a source `path:line`, a map id, a context id or a rule id | Fix the ref in `business/BUSINESS.md`; do not edit the maps |
| `run --from agent` refuses | The agent phase is a command | `extractkit agent next --out <sidecar>` |
| `business rule VR-… is not cited` | A business rule is in no spec FR and not dropped | Re-run `spec.kit`; if the operator says the rule is dropped, set `out-of-scope: yes` in `rules/review.md` |
<!-- markdownlint-enable MD013 -->

## Do not

- Do not tick `[x]` in `rules/review.md` or set `out-of-scope: yes`. The
  agent tasks say the rest.
- Do not edit a map, an inventory file or `rules/view-rules.json`. Re-run
  the slot instead.
- Do not write port plans, `DECISIONS.md` or `IMPLEMENTATION.md`.
- Do not run graft, graphify, Serena onboarding or `git` writes in the source.
- Do not edit the source `.gitignore` or `.git/`.
- Do not skip `check`, and do not report a clean extract while it lists
  problems.
