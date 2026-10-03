# 99x Extract Kit (headless)

## Quick reference

- **Maintained by**: [99x Brazil](https://99x.io/services/web-solutions)
- **Where to get help**: the private team Slack

## Supported tags

- `latest`, `full`: every feature. Playwright with Chromium, PHP and Composer,
  and the `claude`, `codex` and `cursor-agent` CLIs.
- `slim`: no Playwright, Chromium, PHP or Composer. All three agent CLIs.
- `root`: the `full` image, started as root instead of uid 1000.
- `<kit-commit>`, `<kit-commit>-slim`, `<kit-commit>-root`: the same images
  pinned to one commit of the kit, so a pipeline run is reproducible.

Every tag includes the 1Password CLI (`op`) from the official apt repository,
unpinned. All tags are `linux/amd64`.

## What is it?

Extract Kit studies an existing software project and writes down what it
does: business rules, pages and components, data, and the systems it talks
to, as standard documents (Spec Kit, OpenAPI, DESIGN.md). This image runs it
with no human in the loop: it calls an agent CLI for each agent task and
reports through one JSON document and an exit code (`0` done, `1` failed,
`3` a human is needed).

The image holds the tools and a copy of the kit. Everything that varies per
run is supplied when the container starts: the checkout, the profile, the
agent and its credentials.

## Quick start

```bash
docker run --rm \
  -v "$PWD:/work" --user "$(id -u):$(id -g)" \
  -e ANTHROPIC_API_KEY \
  leanon/extractkit-headless:latest --source /work
```

The run writes `.extract/` into the mounted checkout and nothing else. The
checkout is otherwise read-only to the kit; production CMS hosts are refused.

## Starting the image

The entrypoint follows the `docker:cli` convention, so the image works both
as a command and inside a pipeline runner.

| You pass | What runs |
| --- | --- |
| nothing, or flags | `extractkit headless --json` and the flags |
| `headless ...` | the same, spelled out |
| an `extractkit` command | that command (`doctor`, `deps`, `status`) |
| anything else | exactly that (`sh`, `git`), same exit code |

The last row is what a pipeline needs. Runners such as GitLab CI start the
job container with a shell and pipe the job script into it. The image's
entrypoint hands that shell through unchanged, so `image:` works without
`entrypoint: [""]`. Clearing the entrypoint works too.

## In a pipeline

```yaml
extract:
  image: leanon/extractkit-headless:latest
  variables:
    EXTRACTKIT_AGENT: claude
  script:
    - extractkit headless --source "$CI_PROJECT_DIR" --json | tee extract-result.json
  artifacts:
    when: always
    paths:
      - .extract/
      - extract-result.json
```

Set the agent's API key (for example `ANTHROPIC_API_KEY`) as a masked
variable.

### The user and the checkout

The default image runs as uid 1000 (`extract`), because the Claude CLI
refuses its bypass permission mode as root. A runner that checks the source
out as root leaves it unwritable for that user. The run then stops before any
stage with the error `source_not_writable`.

- With plain `docker run`, pass `--user "$(id -u):$(id -g)"` as in the quick
  start.
- On a runner that clones as root, use the `root` tag. Its default permission
  mode (`allowlist`) works as root; `bypass` does not for `claude`.

## Credentials

The 1Password CLI is on PATH: `docker run IMAGE op --version`, or `op` in a
job script. It reads its own credentials, for example a service account
token in `OP_SERVICE_ACCOUNT_TOKEN`; the kit never reads or stores them.

Pass an API key as an environment variable (`ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, `CURSOR_API_KEY`). The agent CLIs also support a
subscription login, but the image has none: a login would have to be mounted
in or done inside the container, and subscription tokens expire.

## Choosing the agent and the profile

`--agent claude|codex|cursor` (or `EXTRACTKIT_AGENT`) picks the agent CLI.
`--profile` picks the stack profile; it is detected from the checkout when
omitted. An agent needs its own setup in the container: for the preflight, the
Serena MCP server must be registered in that agent's configuration.

## Building your own variant

The image is built from the `docker/Dockerfile` of the kit, and every part
is a build argument:

| Build argument | Default | Effect |
| --- | --- | --- |
| `WITH_PLAYWRIGHT` | `1` | `0` drops Playwright and Chromium |
| `WITH_PHP` | `1` | `0` drops PHP and Composer |
| `WITH_1PASSWORD` | `1` | `0` drops the 1Password CLI |
| `AGENTS` | `claude codex cursor` | The agent CLIs to install |
| `RUN_AS` | `extract` | `root` starts as root |

## Notes

- `cursor-agent` comes from Cursor's installer and is not pinned, so two
  builds on different days can contain different versions.
- Subscription logins, and running `--agent cursor` and `--agent codex`
  inside the image, have not been tested in the container.
