# LLM instructions

For an agent that reads these docs and drives `extractkit`. Follow it as a
procedure. Facts about flags and files are in [CLI](cli.md),
[steps](steps.md) and [output](output.md); this page says what to do with
them.

## Invariants

- Run from the legacy checkout, in an agent session opened there, with
  `extractkit` on PATH (`./extractkit install` in a kit checkout puts it
  there as a detached copy; preflight only checks it). The CLI refuses to
  run when the working folder, `--source` or `--out` is inside the kit:
  Serena, Graphify and graft act on the session's folder, so a session in
  the kit would onboard and index the kit. If it refuses, stop and ask the
  operator to open the legacy checkout.
- The source checkout is read-only. Every run writes only
  `<source>/.extract/<run-id>/`, or `<source>/extract/<run-id>/` under
  `extractkit headless`. Only `promote` writes into the checkout, and only
  when the operator asked for it.
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
- Credentials are the operator's. Never read, print or log the files that hold
  them (the agent token, the XP login, the job environment); `extractkit assets`
  lists their types and file names only.
- The kit extracts and scores. It never infers. Anything you add beyond an
  extracted fact is marked `_(inferred)_` and keeps an `Evidence:` line.
- Migration means a mapped, spec-ready component structure. It does not
  mean converting code to another stack.
- Never pass `--allow-production`, and use `--force` on `promote` only when
  the operator says so.

## Command sequence

Run the phases in order. Each command ends with a `next` block; paste it
instead of rebuilding the command. The stack comes from the checkout: pass
`--profile` only when a command says it cannot detect one.

### 1 Preflight

```bash
extractkit deps --profile enonic
extractkit doctor --source .
```

Both first check the install: the kit copy in `~/.local/share/extractkit`,
the launcher in `~/.local/bin`, and the skill copies in `~/.agents/skills`
(linked from `~/.claude/skills`). Run from the kit checkout they install it;
run from the installed copy they only check it. An install row that fails
names its fix (`--force` for a foreign symlink, an `export PATH` line when
`~/.local/bin` is not on PATH). `deps` then runs every probe.
`doctor --source` adds the target's readiness: Serena onboarding, a
Graphify index (both must pass), a graft index (a warning), the stack it
would detect, and the build scope (a warning that lists top-level folders no
default-branch build names). The operator produces the indexes in a session
opened in the checkout.

### 2 Context

```bash
extractkit context --source <legacy>
```

`run` and `resume` do this on their own when the sidecar has no context yet,
so you rarely call it. It detects the stack (`enonic` from
`src/main/resources/application.xml` or `site/site.xml`, `php` from a root
`composer.json`), writes `context/build-scope.json` (the top-level folders
no default-branch build names) and the overlay `context/profile.yaml`. It
excludes nothing by itself. The overlay gets `exclude: []` only when the
build scope has nothing to decide. Otherwise `context.exclude` (an agent
task, below) decides, and the operator can still pass `--exclude` on the
first run. A checkout with no marker, or markers for both stacks, fails with
a `fix:` that passes `--profile`.

### 3 Static

```bash
extractkit run --source <legacy> --until static
extractkit status --source <legacy>
```

This writes the template inventory, the component map and the OpenAPI
harvest. When detection fails, pass `--profile enonic` for any stack that
has no adapter of its own: `core` cannot run alone, and `php` refuses on
purpose.

When the build scope left folders undecided, the `next` block now offers
`agent show context.exclude`. Run that task before the CMS and merge slots,
so the later scans skip what it excludes.

### 4 CMS (optional)

<!-- markdownlint-disable MD013 -->
```bash
extractkit resume --source <legacy> --branch draft --storage-state <state.json>
```
<!-- markdownlint-enable MD013 -->

Local or review XP only. Skip it with `--from merge` in the next phase.
Before this step, read the How-tos for the CMS in devkit's kb, under
`~/.local/share/devkit/current/core/kb/implementation/`:
`How-to-log-in-to-an-xp7-admin-and-keep-the-session.md` (log in, get a
storage state) and
`How-to-traverse-an-xp7-cms-through-guillotine-and-content-studio.md`
(Guillotine, Content Studio REST, Site Config, what to pin with `--cms-key`).
`enonic.cms` also writes `inventory/live-config-candidates.json`: the
Site Config and Config Env keys whose value is a URL or a host map, and
whether the current `live_config` rules cover them. The task
`context.live_config` reads it.

### 5 Merge and 6 Synthesis

<!-- markdownlint-disable MD013 -->
```bash
extractkit run --source <legacy> --out <sidecar> --from merge --until synthesis
```
<!-- markdownlint-enable MD013 -->

Merge also writes `rules/`. Synthesis cites the rules in the specs. The
next phase is the agent phase (7); `run` and `step` refuse it.

### 7 Agent

The kit stores each agent step as a prompt in `agent-tasks/<id>/`. It never
calls a model. After synthesis, `extractkit status` shows the agent phase as
current while a required task is pending. Two tasks come earlier, because
the later phases read what they write: `context.exclude` is ready after the
static phase, and `context.live_config` after the CMS slot.

```bash
extractkit agent list --out <sidecar>
extractkit agent next --out <sidecar> --json
extractkit agent show <id> --out <sidecar>
```

`agent next` names the first required task whose inputs exist. `agent show`
prints its prompt with the real sidecar and source paths, then the input and
output files. Do the task, run its `rerun` command when it declares one
(with the CMS flags of the earlier run added), run `check`, and ask for the
next task. Stop when `agent next` reports none pending. The `extract-agentic`
skill runs this loop.

<!-- markdownlint-disable MD013 -->
| Task | Writes | Done when |
| --- | --- | --- |
| `context.exclude` | `exclude` in `context/profile.yaml` | the overlay has an `exclude` key; `[]` counts. It is already `[]` when the build scope has nothing to decide |
| `context.live_config` | `live_config` in `context/profile.yaml` | the overlay has a `live_config` key, or there is no `inventory/live-config-candidates.json` (no live harvest) |
| `rules.name` | `rules/review.md` (names and intents) | no business rule in `rules/view-rules.json` is still `extracted` |
| `business` | `business/BUSINESS.md` and `business/capabilities.json`, then re-runs `step product.impeccable` | both files exist |
| `constitution` | `spec-kit/constitution/project.md`, then re-runs `step spec.kit` | the file exists |
| `domain.behavior` | `domain/<capability>.md` (states, formulas, calls, emails, jobs, retries) | every capability in `business/capabilities.json` has its file |
| `donotport` | `reports/do-not-port.md` (security behavior, defects, dead code) | the file exists |
| `spec.capabilities` | `spec-kit/specs/<capability>/spec.md` (spec-kit layout, stack independent) | every capability has its spec |
| `spec.review` | `reports/spec-review.md` (findings only; edits no spec) | optional, never blocks |
<!-- markdownlint-enable MD013 -->

The two `context.*` tasks decide, they do not invent: `check` rejects an
`exclude` entry that is not in `context/build-scope.json` `out_of_scope`,
and a `live_config` key, URL path or origin host that is in neither the
source nor the harvested live config. `context.exclude` re-runs
`run --from static --until synthesis`. `context.live_config` re-runs
`step inventory.runtime`. The `Re-run:` line prints only those tokens, so
add `--source`, `--out` and the CMS flags (`--branch`, `--storage-state`,
`--guillotine` or `--xp-host`, `--cms-key`) of the run that wrote the
sidecar. `rules.name` needs a re-run too: the names reach
`rules/view-rules.json` only when you run the merge and synthesis slice. The
procedure and the analyst gates are in each task's prompt. The agent never
ticks `[x]` in `rules/review.md`.

### 8 Check and 9 Promote

```bash
extractkit check --out <sidecar>
extractkit promote --source <legacy> --out <sidecar>
```

`check` validates `business/BUSINESS.md` and
`spec-kit/constitution/project.md` only when they exist. Promote only when the
operator asks.

## Exit codes and `next`

<!-- markdownlint-disable MD013 -->
| Result | Do |
| --- | --- |
| Exit 0 and a `next` block | Run that block, or stop if the operator asked for less |
| Exit 0, `or continue without CMS` alternative | Pick the CMS line only when a local or review XP and a storage state exist; otherwise the offline line |
| Exit 1 with `error:` and `fix:   $ <command>` | Run the fix command. It is your own command with the missing flag added |
| Exit 1 with a prose `fix:` | Do what it says, or report it to the operator when it needs a decision |
| Exit 0, `Agent is next` | Run `extractkit agent next`, or the `or skip to check` line when the operator asked for less |
| Exit 3 (`headless` only) | A task is blocked and a person must look. Read the blocker file the error names; do not retry the run |
| `check` exit 1 | Fix each listed problem at its source, re-run the slot that writes the file, then `check` again |
| Exit 2 | A wrong flag or command. Read `--help`; do not retry blindly |
| Any command with `--json` | Read the one JSON document on stdout: `ok`, `error.code`, `error.fix` and `error.fix_command` (run it as given), `next_command.argv` (exec it without shell parsing), `rows`, `problems`. Exit codes are the same as in text mode |
<!-- markdownlint-enable MD013 -->

## Failures and fixes

<!-- markdownlint-disable MD013 -->
| Symptom | Cause | Fix |
| --- | --- | --- |
| `devkit` MISSING in `deps`, `doctor` or the headless `doctor` stage | devkit (99x-dev-kit) is not installed | Report the printed `fix:` (clone devkit, run its `bootstrap.sh` and `install.py` with `--profile extract`); installing it is the operator's call |
| `BROKEN` in `deps` | The tool is on PATH but its probe failed (for example `graphify` with a missing package) | Report the printed `fix:`; reinstall is the operator's call |
| `./extractkit: No such file or directory` or `extractkit: command not found` | The kit is not on PATH; `./extractkit` only works inside the kit repo | Ask the operator to run `./extractkit install` once in a kit checkout, then use `extractkit`. The checkout can be deleted afterwards |
| `extractkit on PATH` MISSING | `~/.local/bin` is not on PATH | Report the printed `export PATH=` line; editing shell profiles is the operator's call |
| `install`, `launcher …` or `skill …` BROKEN | A symlink there points elsewhere, a file or folder the install did not create is in the way, or the installed copy is from another commit | Report the fix. `install --force` only on the operator's word; a real file or folder is the operator's to move. For a commit mismatch the operator runs `./extractkit install` from a kit checkout |
| `kit_workspace` (exit 1) | The working folder, `--source` or `--out` is inside the kit repo or the installed kit | `cd` into the legacy checkout and run `extractkit` there. Do not work around it |
| `readiness_missing` | `headless` preflight ran the agent and Serena onboarding or the Graphify index is still missing, or the preflight was skipped because no agent credential was found (see the `attachments:` lines) | The agent CLI needs the Serena MCP and the graphify skill on this runner; fix that and re-run |
| `resource_unreachable` | A resource in the resources file does not answer: XP host, Guillotine, storage state, agent CLI or API key variable | The row names the key to fix; re-run `doctor --source --resources` |
| `bad_env`, `env_forbidden` | An `EXTRACTKIT_*` value is not valid, two forms of the storage state are set, or `EXTRACTKIT_ALLOW_PRODUCTION` / `EXTRACTKIT_FORCE` is set | Fix or unset the variable. Those two variables never work |
| `source_not_writable` | `headless` cannot write `<source>/extract/` as the current user, typically a container running as uid 1000 on a checkout cloned as root | Report it; the operator mounts the checkout writable, runs the container with `--user`, or uses the `root` image tag. Do not change permissions yourself |
| `no_source` | `--source` is missing or is not a folder | Pass the legacy checkout; an agent never guesses it |
| `no_stack_marker`, `multiple_stacks` | `context` found no stack marker, or markers for more than one stack | Pass `--profile enonic` (or `php`) as the printed `fix_command` says |
| `missing_branch` | The CMS phase runs without `--branch draft\|master` | Pass `--branch`, or run the offline route |
| `promote_refused` | `promote` would overwrite a file git cannot restore (untracked, ignored or modified), or would write through a symlink | Report it; `--force` only on the operator's word, and it never allows a symlink |
| `redirect_refused` | The XP answered with a redirect to another host, or a URL that is not http(s) | Point `--xp-host`, `--guillotine` or `--site-url` at the final host; do not follow it by hand |
| `unsafe_output` | `<source>/.extract` or `<source>/extract` is a symlink, so the sidecar would land outside the source | Report it; the operator removes the link |
| `kit_failed` | A `headless` child command exited without a JSON result | Read the message it carries; it names the command and its last stderr lines |
| `task_blocked` (exit 3) | An agent wrote `<sidecar>/reports/blockers/<id>.md`, `check` still failed after the fix attempts, or `check` passed but the task is still not done (the blocker names which) | A person reads the blocker, fixes the input, and re-runs headless |
| `task_inputs_missing` | In the final `agent` stage a task waits on a file no earlier stage wrote | A pipeline failure, not a question: run the phases that write it |
| `agent_timeout`, `agent_failed`, `unknown_agent` | The agent CLI ran past `--task-timeout`, exited non-zero, or is not in the `agents:` block | See `reports/headless/*.log`; check the CLI login or API key |
| `credentials_exhausted` | Every `agent_api_key` for the agent stopped answering (quota, expiry) | Run headless again later or with more credentials; finished tasks are kept |
| `serena onboarding` MISSING | No `.serena/project.yml` or no memory file | Ask the operator to onboard the project in an agent session opened in the checkout, not in the kit |
| `graphify index` MISSING | No `graphify-out/graph.json` | Ask the operator to build a Graphify index from a session opened in the checkout (the graphify skill, for example `/graphify .`) |
| `graft index` warning | No `graft/` | Optional. `map.code` skips until the operator runs `graft build` |
| `build scope` warning | A top-level folder no default-branch build names | Advisory. `context.exclude` decides which are not part of the product; the operator can also pass `--exclude` on the first `run` (the sidecar keeps it) |
| `no stack marker found` or `markers for more than one stack` | Detection found no `application.xml`, `site/site.xml` or root `composer.json`, or found both stacks | Run the printed `fix:` (it passes `--profile`); pick the stack the operator wants |
| `context/profile.yaml: … is in neither the source nor the harvested live config` | The agent wrote a key, URL path or host it did not see | Remove it, or cite where it is; do not widen the source. Fix only the overlay, then `check` again |
| `context/profile.yaml: exclude '…' is not in context/build-scope.json out_of_scope` | `exclude` names a folder the build scope did not report | Choose from `out_of_scope` only |
| `… has no evidence`, `does not resolve to a path:line`, `reads as a call graph`, `does not use MUST` | A `domain/`, `spec-kit/specs/` or `reports/do-not-port.md` file broke its gate | Fix the line it names; cite a source `path:line` that exists, and write behavior, not `Calls`/`Exports` bullets |
| `holds the literal of credential key` | A sidecar Markdown file contains a secret value from the source config | Remove the value; write the key and `path:line` only. Never print the value |
| `enonic.cms.configenv` skip, HTTP 404 | The Config Env admin tool is not installed on that XP | Harmless. Pass `--configenv <url>` if it lives elsewhere |
| `profile overlay … sets 'adapters'` | An overlay set a key other than `exclude` or `live_config` | Remove the key; the stack is not an overlay's to change |
| `exclude … is not a path relative to the source` | An absolute `--exclude` or one with `..` | Name the folder relative to `--source` |
| `profile 'core' has unbound required adapters` | `core` has no stack adapters | Pass `--profile enonic`, or let detection pick the stack |
| `enonic.cms requires --branch` | The slice includes CMS | Add `--branch draft`, or stop at `--until static` |
| a production host is refused | The URL is not local or review | Use a local or review XP; never override |
| `promote` refuses | A destination git cannot restore | Commit or stash it. `--force` only on the operator's word |
| `template … maps to no component surface` | A surface was removed from `map/component-map.json` | Re-run `maps.normalize`, never edit the map |
| `component … is not spec-ready` | A `template` block lost a required key | Re-run `maps.normalize` |
| `business/BUSINESS.md … does not resolve` | An `Evidence:` ref is not a source `path:line`, a map id, a context id or a rule id | Fix the ref in `business/BUSINESS.md`; do not edit the maps |
| `spec-kit/constitution/project.md …` | A section is missing, has no `Evidence:` line, or cites a ref that does not resolve | Fix `spec-kit/constitution/project.md`, then re-run `step spec.kit`; never edit `spec-kit/constitution.md` |
| `reports/spec-review.md …` | The report breaks its format: no `# Spec review` H1, a finding without `Spec:`, `Severity:`, `Fix in:` or `Evidence:`, a value outside its set, a `Spec:` path not in the sidecar, or an `Evidence:` ref that does not resolve | Fix the report; never edit the specs. Findings never fail `check` |
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
