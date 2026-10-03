# Headless and pipelines

`extractkit headless` runs the whole extract with no human: it calls an agent
CLI for the preflight and for each agent task, and reports through one JSON
document and an exit code. It is the only command that starts an agent CLI;
every other command never calls a model. For the procedure an interactive
agent follows, see [LLM instructions](llm.md). Flags are in [CLI](cli.md).

## What a pipeline supplies

A pipeline supplies four things. Nothing else is read: no step reads a file
or a database beyond the source checkout and the storage state, so there is
no resource type for either.

<!-- markdownlint-disable MD013 -->
| Resource | What | How to supply it | Checked by |
| --- | --- | --- | --- |
| Legacy checkout | The folder to extract. Mounted or checked out; the run writes `.extract/` there | `--source` / `EXTRACTKIT_SOURCE` | `doctor --source` |
| XP instance (optional) | A local or review XP with the app and a content dump. Production hosts are refused. Without it the run is offline and skips the CMS phase | `xp:` in the resources file, or the CMS flags | `xp host`, `guillotine` rows |
| Auth (needed for the XP) | A Playwright storage state for that XP | `auth.storage_state`, `--storage-state`, or `EXTRACTKIT_STORAGE_STATE_JSON` (the file contents) | `storage state` row |
| Agent | An agent CLI that is logged in or has an API key | `agent:` in the resources file, `--agent` | `agent cli`, `agent api key` rows |
<!-- markdownlint-enable MD013 -->

Headless needs a storage state to run the CMS phase. With none resolved the
`cms` stage is `skipped` and the run continues offline: merge, synthesis, the
agent tasks and check.

The default container image ([`docker/Dockerfile`](../docker/Dockerfile))
bundles the tools: Python 3.12 with `pyyaml` and `jsonschema`, git, Node with graft,
Graphify, Serena, Playwright with Chromium, and the `claude`, `codex` and
`cursor-agent` CLIs. The Compose example starts it, with an optional
`enonic/xp` service that is only useful when you also supply the
application and a content dump. [Building and reusing the
image](#building-and-reusing-the-image) covers slimmer variants.

## The resources file

`--resources FILE` (or `EXTRACTKIT_RESOURCES`) points at an operator-owned
YAML file. It is checked against `schemas/resources.schema.json`; agents never
write it. Values in it fill options that no flag and no env var set.

```yaml
xp:
  host: http://localhost:8080
  project: en
  branch: draft
  guillotine: http://localhost:8080/admin/site/preview/en/draft
  configenv: http://localhost:8080/admin/tool/example/config-env
  site_url: http://localhost:8080/admin/site/preview/en/draft
  cms_keys: [/site/start]
auth:
  storage_state: ./xp-storage-state.json   # relative to this file
agent:
  cli: claude                  # a name in the agents: block of extractkit.yaml
  permissions: allowlist       # or bypass
  allowed_tools: [Read, Write, Edit, Glob, Grep, "Bash(extractkit *)", mcp__serena]
  api_key_env: ANTHROPIC_API_KEY   # the variable's name, never a value
  timeout_seconds: 1800
```

Precedence is CLI flag, then env var, then this file, then the default. The
`config` section of every `--json` result shows where each option came from
(`cli`, `env`, `file`, `default`).

`doctor --source DIR --resources FILE` adds a row per declared resource, each
with a 5 second timeout and no retries:

<!-- markdownlint-disable MD013 -->
| Row | `ok` when |
| --- | --- |
| `xp host` | The host is local or review, and an HTTP GET answers. A production host is refused (`production_host`) |
| `guillotine` | A `{ __typename }` POST, with the storage-state cookies, returns JSON without `errors` |
| `storage state` | The file exists, parses, and holds a cookie for the XP host |
| `agent cli` | The agent's binary is on PATH |
| `agent api key` | The variable named by `agent.api_key_env` is non-empty. Only presence is checked; the value is never read into output |
<!-- markdownlint-enable MD013 -->

With no `xp:` the three CMS rows are `skipped` (`offline run: CMS phase will
be skipped`) and do not count as failures. A failing probe is `MISSING` with
the error code `resource_unreachable` and a fix that names the key.

## Environment variables

Every long option `--foo-bar` has an env form `EXTRACTKIT_FOO_BAR`. A flag on
the command line beats the env var. Booleans take `1|true|yes` and
`0|false|no`, case-insensitive; anything else fails with `bad_env`. Repeatable
options (`--exclude`, `--cms-key`, `--round2`, `--allowed-tools`) take a
comma-separated list, and a flag of the same name on the command line replaces
the env list. An env var satisfies a required option: `EXTRACTKIT_SOURCE=.` is
enough for `run`.

These variables never work, and setting them fails with `env_forbidden`:
`EXTRACTKIT_ALLOW_PRODUCTION` and `EXTRACTKIT_FORCE` (for `--allow-production`,
`promote --force` and `install --force`). Headless never passes either flag.

`EXTRACTKIT_STORAGE_STATE_JSON` holds the storage-state file contents (a
masked CI variable). It is written to a mode 0600 file in a private temp
folder, used as `--storage-state`, and deleted at exit. It conflicts with
`--storage-state` and `EXTRACTKIT_STORAGE_STATE`: set one (`bad_env`). Its
contents appear nowhere in stdout, the JSONL log or `MANIFEST.yaml`, and the
`config` section shows `<redacted>`.

Headless starts `extractkit` and the agent without any `EXTRACTKIT_*`
variable. It passes every setting as a flag, so a variable meant for headless
(`EXTRACTKIT_UNTIL` takes a stage id there) cannot leak into a child command.

<!-- markdownlint-disable MD013 -->
| Variable | Option | Commands |
| --- | --- | --- |
| `EXTRACTKIT_SOURCE` | `--source` | most commands |
| `EXTRACTKIT_OUT` | `--out` | commands that take a sidecar |
| `EXTRACTKIT_PROFILE` | `--profile` | `context`, `deps`, `doctor`, `headless`, `resume`, `run`, `status`, `step` |
| `EXTRACTKIT_FROM`, `EXTRACTKIT_UNTIL` | `--from`, `--until` | `run`, `resume` (`--until`); `headless` takes a stage id |
| `EXTRACTKIT_EXCLUDE` | `--exclude` | `context`, `headless`, `resume`, `run`, `step` |
| `EXTRACTKIT_BRANCH`, `EXTRACTKIT_XP_HOST`, `EXTRACTKIT_GUILLOTINE`, `EXTRACTKIT_PROJECT` | CMS options | `headless`, `resume`, `run`, `step` |
| `EXTRACTKIT_STORAGE_STATE` | `--storage-state` | `doctor`, `headless`, `resume`, `run`, `step` |
| `EXTRACTKIT_CMS_KEY`, `EXTRACTKIT_ROUND2`, `EXTRACTKIT_CONFIGENV`, `EXTRACTKIT_SITE_URL` | CMS options | `headless`, `resume`, `run`, `step` |
| `EXTRACTKIT_TASKS` | `--tasks` | `resume`, `run`, `step` |
| `EXTRACTKIT_RESOURCES` | `--resources` | `doctor`, `headless`, `resume`, `run`, `step` |
| `EXTRACTKIT_JSON`, `EXTRACTKIT_VERBOSE`, `EXTRACTKIT_QUIET` | `--json`, `-v`, `-q` | most commands |
| `EXTRACTKIT_AGENT`, `EXTRACTKIT_AGENT_PERMISSIONS`, `EXTRACTKIT_ALLOWED_TOOLS` | `--agent`, `--agent-permissions`, `--allowed-tools` | `headless` |
| `EXTRACTKIT_MAX_FIX_ATTEMPTS`, `EXTRACTKIT_TASK_TIMEOUT` | `--max-fix-attempts`, `--task-timeout` | `headless` |
| `EXTRACTKIT_PROMOTE` | `--promote` | `headless` |
| `EXTRACTKIT_STORAGE_STATE_JSON` | storage-state contents | commands with `--storage-state` |
<!-- markdownlint-enable MD013 -->

## The stages

`headless` runs eleven stages in order and stops at the first failure. The
same ids are the values of `--until`, the `stage` field of the JSONL log and
the entries of `stages[]` in the result.

![Headless pipeline](diagrams/headless-pipeline.png)

<!-- markdownlint-disable MD013 -->
| Stage | Does |
| --- | --- |
| `install` | `extractkit install --json` (a check when run from the installed copy) |
| `preflight` | Builds the graft index if `graft/` is missing. When Serena onboarding or the Graphify index is missing, starts one agent process with `headless/preflight.md`, then re-checks readiness (`readiness_missing`) |
| `doctor` | `doctor --source` with `--resources` |
| `static` | `run --until static` |
| `agent:context` | The agent loop, limited to `context.*` tasks |
| `cms` | `resume --until cms`, only when a storage state is resolved; otherwise `skipped` |
| `agent:live_config` | The same `context.*` loop, after the CMS slot |
| `synthesis` | `run --from merge --until synthesis` |
| `agent` | The full agent loop; `task_inputs_missing` when a task waits on a file nothing wrote |
| `check` | `check`; `check_failed` with the problems |
| `promote` | Only with `--promote`; never `--force` |
<!-- markdownlint-enable MD013 -->

The agent loop asks `agent next --json`. For each task it starts a fresh
agent process in the source folder with the rendered prompt behind
`headless/preamble.md` on stdin, runs the task's `rerun`, then `check`. When
`check` fails it starts a new process with the problems, up to
`--max-fix-attempts` (default 2) times, then writes a blocker. On the offline
route a `run` rerun whose range holds the CMS phase is split into the slice
before it and the slice after it, so it cannot fail at CMS preflight.

Re-running headless on the same source resumes the latest sidecar. A stage
whose outputs exist reports `ok (already done)` and starts no agent. The
`install`, `doctor` and `check` stages always run.

## Agent CLIs and permissions

The agent CLIs are data: the `agents:` block of `extractkit.yaml` gives each
one an `argv` template (the prompt is always sent on stdin), the flags for
`allowlist` and `bypass` permissions and a default tool allowlist.
`claude`, `codex` and `cursor` ship, with argv checked against `claude`
2.1.280, `codex-cli` 0.151.0 and `cursor-agent` 2026.10.01. Another CLI is a
new entry, no code change; `--agent` and `agent.cli` are checked against the
block when the command runs. The block is read by one function, so no flag or
env var can point headless at another binary.

What each assistant supports, checked on 2026-10-02 with one stdin run of each
CLI (run `extractkit --help`, write a file, call a Serena tool):

<!-- markdownlint-disable MD013 -->
| | Claude Code | Codex | Cursor |
| --- | --- | --- | --- |
| Interactive: reads `AGENTS.md` | yes (`CLAUDE.md` is a symlink to it) | yes | yes |
| Interactive: skills from | `~/.claude/skills` | `~/.agents/skills` | `~/.agents/skills`; depends on the Cursor version, not checked |
| `--agent` value | `claude` | `codex` | `cursor` (binary `cursor-agent`) |
| `allowlist` mode | per-tool: `allowed_tools` | `workspace-write` sandbox; `allowed_tools` is ignored | `--force` with `--sandbox enabled`; `allowed_tools` is ignored |
| `bypass` mode | `bypassPermissions` | `--dangerously-bypass-approvals-and-sandbox` | `--force --sandbox disabled` |
| Serena MCP in headless | needs the server in the agent's own config | same | same |
| In the default container image | yes, pinned | yes, pinned | yes, unpinned (official installer); key in `CURSOR_API_KEY` |
<!-- markdownlint-enable MD013 -->

Only Claude Code limits an agent to named tools. Codex and Cursor are limited
to a sandbox, so the `--allowed-tools` override has no effect on them. Cursor
in print mode waits for an approval no one answers unless `--force` is set,
which is why its allowlist route is the sandbox.

Permissions default to a narrow allowlist: the agent may read, edit files and
run `extractkit`, and the preflight may run `graphify` and use the Serena MCP.
Override it with `agent.allowed_tools` or `--allowed-tools`. Setting
`agent.permissions: bypass` (or `EXTRACTKIT_AGENT_PERMISSIONS=bypass`) skips
the allowlist; it is the operator's call and never a kit default. Prefer to
run a bypass only inside the container. The agent inherits the environment
(minus `EXTRACTKIT_*`) so its API key reaches it. Its output goes to
`<sidecar>/reports/headless/<stage>-<task>-<attempt>.log`; those logs are agent
output and may echo prompts.

Preflight needs the Serena MCP and, for the Graphify skill fallback, the
graphify skill configured for the agent on the runner. Headless detects a
missing readiness item and fails with `readiness_missing`; it does not
install tools. The container image has them.

## Blockers and exit 3

There is no operator in a headless run. `headless/preamble.md` tells the
agent that wherever a task prompt says to stop and ask, it writes
`<sidecar>/reports/blockers/<task id>.md` with a `Reason:` and an `Evidence:`
line, and stops. When that file exists after a task, headless stops with exit
3 and `error.code: "task_blocked"`. Exhausting the fix attempts writes a
blocker too. Before a task starts, headless deletes that task's old blocker,
so a re-run after a human fixed the input gets a fresh attempt.

The analyst gates are unchanged: no agent ticks `[x]` in `rules/review.md` or
sets `out-of-scope: yes`, and an agent keeps a folder when unsure.

## Output and exit codes

`--json` (or `EXTRACTKIT_JSON=1`) prints one document on stdout and nothing
else, for every command. The same envelope carries the failure: `ok: false`,
and `error` with a stable `code`, the `message`, the `fix` text and, when the
fix is a command, `fix_command`. Usage errors from argparse stay on stderr
with exit 2, because they happen before `--json` is read. The envelope is
defined in `schemas/result.schema.json`; `headless` adds `stages[]`, and
`<sidecar>/reports/headless.jsonl` holds one line per stage (and one per agent
attempt) with `ts`, `stage`, `task`, `attempt`, `ok`, `exit`, `code`,
`message`, `duration_s` and `log`.

<!-- markdownlint-disable MD013 -->
| Exit | Meaning | CI job |
| --- | --- | --- |
| 0 | Every stage passed | pass |
| 1 | A stage failed, or a flag was refused | fail |
| 2 | Bad flag or command (argparse) | fail |
| 3 | Blocked: an agent wrote a blocker, a human is needed | fail, or `allow_failure` |
<!-- markdownlint-enable MD013 -->

## Building and reusing the image

Build once, tag, push, and reuse: a run never builds an image. The image
freezes the toolchain and a detached copy of the kit, including every profile.
Everything that varies per run is supplied at run time: the checkout (mounted
at `/work`), `--profile`, `--agent`, the resources file and the credentials.

The default build has every feature. Build arguments drop parts you do not
need; each is optional and keeps the default when omitted.

<!-- markdownlint-disable MD013 -->
| Build argument | Default | Effect |
| --- | --- | --- |
| `WITH_PLAYWRIGHT` | `1` | `0` leaves out Playwright and Chromium. The `enonic` baseline step needs them |
| `WITH_PHP` | `1` | `0` leaves out `php-cli` and `composer`, which the `php` profile uses |
| `WITH_1PASSWORD` | `1` | `0` leaves out the 1Password CLI (`op`), installed from its apt repository and not pinned |
| `AGENTS` | `claude codex cursor` | The agent CLIs to install, space separated. An unknown name fails the build |
| `RUN_AS` | `extract` | `root` starts the container as root, for runners that check the source out as root |
| `*_VERSION` | pinned in the Dockerfile | Tool versions (`NODE`, `GRAFT`, `SERENA`, `GRAPHIFY`, `CLAUDE_CODE`, `CODEX`, ...). `cursor-agent` has no version argument |
<!-- markdownlint-enable MD013 -->

```bash
# the default, full image
docker build -f docker/Dockerfile -t extractkit-headless:full .
# a slim image for the core profile, Claude only
docker build -f docker/Dockerfile -t extractkit-headless:core-claude \
  --build-arg WITH_PLAYWRIGHT=0 --build-arg WITH_PHP=0 \
  --build-arg AGENTS=claude .
```

A slim image still runs every profile: the tools a profile needs are optional
dependencies, so a missing one is `skipped` in `doctor` and its step reports
what it lacks. Use the full image when in doubt. Tag images by the kit commit
(or release) and the variant, so a pipeline run is reproducible and a
regression rolls back by tag. A rebuild can pick up a newer `cursor-agent`
than the one this page names, because its installer is unpinned.

### How a pipeline starts the image

The entrypoint ([`docker/entrypoint.sh`](../docker/entrypoint.sh)) follows the
`docker:cli` convention: flags run `extractkit headless --json`, another
`extractkit` command runs as given, and anything else (`sh`, `git`) is
executed unchanged with its exit code. A runner that starts the job container
with a shell and pipes the job script into it therefore gets its shell, so the
`image:` keyword needs no `entrypoint: [""]`. [`docker/smoke.sh`](../docker/smoke.sh)
checks those ways of starting the image, and the CI job runs it before any push.

The default image runs as uid 1000. When the source is not writable for that
user, headless stops before any stage with `source_not_writable`. Pass
`--user` to `docker run`, or use the `root` variant on a runner that clones as
root. The `claude` bypass permission mode refuses root; the default
`allowlist` mode works.

### Publishing to Docker Hub

[`.gitlab-ci.yml`](../.gitlab-ci.yml) builds three variants on every change to
the kit on the `docker` branch, and on no other branch: `full` (tagged
`latest` and `full`), `slim` and `root`, each also tagged with the kit commit.
Each is smoke-tested before it is pushed. The Docker Hub description is
`docker/README.md`, pushed by `docker-pushrm` from a manual job in a `docker`
branch pipeline; it never runs on its own. The pipeline needs
`CI_DOCKER_TOKEN`, a Docker Hub access token with `admin` scope (pushrm needs
it to write the description); `DOCKERHUB_USER` and `DOCKERHUB_REPO` are
variables at the top of the file.

## GitLab CI

```yaml
extract:
  image: registry.example.com/tools/extractkit-headless:latest   # built from docker/Dockerfile
  variables:
    EXTRACTKIT_AGENT: claude
    EXTRACTKIT_RESOURCES: .extractkit/resources.yaml
    EXTRACTKIT_UNTIL: check
    # Masked CI/CD variables: the agent API key and the storage-state contents.
    # ANTHROPIC_API_KEY
    # EXTRACTKIT_STORAGE_STATE_JSON
  script:
    # The checkout is the legacy project, so cwd is the source.
    - extractkit headless --source "$CI_PROJECT_DIR" --json | tee extract-result.json
  artifacts:
    when: always
    paths:
      - .extract/
      - extract-result.json
    expire_in: 2 weeks
  # Exit 3 means a task is blocked and a person must look; make it non-fatal
  # only when that is what the team wants.
  allow_failure:
    exit_codes: [3]
```

`.extract/` is the artifact: the sidecar, `reports/headless.jsonl`, the agent
logs and any blocker file. In the container, flags go to
`extractkit headless --json`, so `docker run` and a Compose service take the
same flags; see [How a pipeline starts the image](#how-a-pipeline-starts-the-image).
