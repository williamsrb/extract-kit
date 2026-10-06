# 99x Extract Kit (headless)

## Quick reference

- **Maintained by**: [99x Brazil](https://99x.io/services/web-solutions)
- **Where to get help**: the private team Slack

## Supported tags

- `latest`: every feature. Playwright with Chromium, PHP and Composer, and
  the `claude`, `codex` and `cursor-agent` CLIs. Starts as uid 1000.
- `root`: the same image, started as root instead of uid 1000.

Each tag is rebuilt on every change to the kit and replaces the previous one;
there are no per-commit tags.

Every tag includes the 1Password CLI (`op`) from the official apt repository,
unpinned, and 7-Zip (`7z`, Debian's `p7zip-full`). All tags are `linux/amd64`.

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
  leanon/extractkit-ci:latest --source /work
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
  image: leanon/extractkit-ci:latest
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

Give the job the agent's credential; see [Credentials](#credentials) for
the 1Password flow.

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

### Agent credentials from 1Password

A pipeline can read the agent's credential from 1Password at run time instead
of keeping it in a GitLab variable. One item in the vault holds a
password-protected 7z archive for each agent the project may run, attached to
the item and named after the variable that agent's CLI reads. The job reads
`EXTRACTKIT_AGENT`, downloads that agent's attachment, opens it with the
passphrase in `PASSWORD` and exports the credential before `extractkit`
starts; the kit passes the environment to the agent and never reads the value.

| `EXTRACTKIT_AGENT` | Attachment | Credential |
| --- | --- | --- |
| `claude` | `CLAUDE_CODE_OAUTH_TOKEN.yaml.7z` | A `claude setup-token` token |
| `codex` | `OPENAI_API_KEY.yaml.7z` | An OpenAI API key |
| `cursor` | `CURSOR_API_KEY.yaml.7z` | A Cursor API key |

Each archive holds one YAML file with the same name minus `.7z`. Its `token`
key holds the credential; other keys, such as `validity`, are not read. The
Claude token is valid for one year, needs a Claude Pro, Max, Team or Enterprise
plan, and covers model requests only. The image has no subscription login for
`codex` and `cursor`, so they take API keys. The item needs only the
attachments of the agents the project runs.

Make an archive once per agent, on your machine. Never put the credential or
the passphrase in a command argument: `-p` without a value makes `7z` ask for
the passphrase. For Claude:

```bash
umask 077
```

```bash
claude setup-token
```

Put the printed token in `CLAUDE_CODE_OAUTH_TOKEN.yaml` under the key `token`,
for example `token: "<token>"`. `-mhe=on` also encrypts the file names.

```bash
7z a -mhe=on -p CLAUDE_CODE_OAUTH_TOKEN.yaml.7z CLAUDE_CODE_OAUTH_TOKEN.yaml
```

Attach the `.7z` file to the item in the 1Password app, then delete both local
files. Repeat with `OPENAI_API_KEY` and `CURSOR_API_KEY` for the other agents.

```bash
shred -u CLAUDE_CODE_OAUTH_TOKEN.yaml CLAUDE_CODE_OAUTH_TOKEN.yaml.7z
```

Set these GitLab variables. The service account must be able to read the
vault.

| Variable | Holds |
| --- | --- |
| `OP_SERVICE_ACCOUNT_TOKEN_FACTORY` | The 1Password service account token |
| `OP_VAULT_NAME_FACTORY` | The vault name (one vault must match) |
| `OP_EXTRACT_NAME_FACTORY` | The title of the item with the archives |
| `PASSWORD` | The archives' passphrase, set on each pipeline run |

The job script. The image ships `/filter-by-name.sh`, which turns the vault
name into the vault ID, and `7z`:

```yaml
variables:
  EXTRACTKIT_AGENT: claude
  CI_SERVICE_ACCOUNT_TOKEN: $OP_SERVICE_ACCOUNT_TOKEN_FACTORY
  CI_VAULT_NAME: $OP_VAULT_NAME_FACTORY
  CI_AGENT_SECRET_NAME: $OP_EXTRACT_NAME_FACTORY
script:
  - export OP_SERVICE_ACCOUNT_TOKEN=$CI_SERVICE_ACCOUNT_TOKEN
  - OP_VAULT_ID=$(op vault list | /filter-by-name.sh "${CI_VAULT_NAME}")
  - |
    # For claude an API key outranks the OAuth token, so a leftover one is dropped.
    case "$EXTRACTKIT_AGENT" in
      claude) AGENT_KEY_VAR=CLAUDE_CODE_OAUTH_TOKEN; unset ANTHROPIC_API_KEY ;;
      codex) AGENT_KEY_VAR=OPENAI_API_KEY ;;
      cursor) AGENT_KEY_VAR=CURSOR_API_KEY ;;
      *)
        echo "no 1Password credential mapped for agent '$EXTRACTKIT_AGENT'" >&2
        exit 1 ;;
    esac
    : "${PASSWORD:?the passphrase of the credential archives}"
    AGENT_KEY_DIR=$(mktemp -d)
    AGENT_KEY_REF="op://${OP_VAULT_ID}/${CI_AGENT_SECRET_NAME}/${AGENT_KEY_VAR}.yaml.7z?attribute=content"
    op read "$AGENT_KEY_REF" > "$AGENT_KEY_DIR/archive.7z"
    AGENT_KEY=$(7z x -so -p"$PASSWORD" "$AGENT_KEY_DIR/archive.7z" \
      | python3 -c '
    import sys, yaml
    data = yaml.safe_load(sys.stdin)
    if not isinstance(data, dict) or not data.get("token"):
        sys.exit("no token in the archive (wrong PASSWORD?)")
    print(data["token"])
    ')
    rm -rf "$AGENT_KEY_DIR"
  - export "${AGENT_KEY_VAR}=${AGENT_KEY}"
  # The agent inherits the environment; drop what opens the vault.
  - unset PASSWORD OP_SERVICE_ACCOUNT_TOKEN OP_SERVICE_ACCOUNT_TOKEN_FACTORY CI_SERVICE_ACCOUNT_TOKEN
  - extractkit headless --source "$CI_PROJECT_DIR" --json | tee extract-result.json
```

- **The run picks the agent.** `EXTRACTKIT_AGENT` selects both the agent CLI
  and the attachment. Set it in the job's `variables:`, or when running the job:
  a variable set on the Run pipeline page overrides the YAML. Set it there, not
  only as `agent.cli` in a resources file, or the job loads Claude's attachment
  for another agent. An agent missing from the `case` stops the job before
  `op read`; add a line when you add an agent to `extractkit.yaml`.
- **Assign first, `export` after.** `export VAR=$(...)` hides a failed
  `7z` or `op read`, and the agent would then fail on authentication far from
  the cause. A missing `PASSWORD`, a wrong one, or an archive without a `token`
  key stops the job with a message.
- **The credential never touches a file unencrypted.** `7z x -so` writes it to
  a pipe that `python3` reads as YAML; only the encrypted archive sits in a
  temporary directory, which the job removes. `7z` takes the passphrase as
  `-p` on its command line, so other processes in the job container can see it
  while `7z` runs; the agent has not started yet.
- **Claude's API key outranks the OAuth token** (and in `-p` mode a present key
  is always used), so the job unsets it in case an old variable is still
  defined. To use an Anthropic API key instead, put it in an archive named
  `ANTHROPIC_API_KEY.yaml.7z`, set `AGENT_KEY_VAR` to that name and drop the
  `unset`.
- **The job unsets the passphrase and the service account token** before the
  agent starts. The agent inherits the environment, and one that can run `env`
  would write them into logs that the job keeps as artifacts.
- The Claude token lasts a year. To renew it, make a new archive and replace
  the attachment; the pipeline needs no change.

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
- The credential archives from 1Password (the `claude setup-token` token,
  `OPENAI_API_KEY`, `CURSOR_API_KEY`), and running `--agent codex` and
  `--agent cursor` inside the image, have not been tested in the container by
  this repository.
