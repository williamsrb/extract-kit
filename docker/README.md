# Extract Kit CI

## Quick reference

- **Where to get help**:
  [the private team Slack](https://leanonteam.slack.com)

## Supported tags and respective image links

- [`latest`](https://hub.docker.com/layers/leanon/extractkit-ci/latest)
- [`root`](https://hub.docker.com/layers/leanon/extractkit-ci/root)

## Quick reference (cont.)

- **Published image artifact details**:
  `docker/Dockerfile`
- **Source of this description**:
  `docker/README.md`

## What is it?

Extract Kit reads an existing software project and documents what it does:
business rules, pages and components, data, and the systems it talks to, as
standard documents (Spec Kit, OpenAPI, DESIGN.md). This image runs it
headless in a CI pipeline, calling an agent CLI for each agent task.

Included: the kit, the `claude`, `codex` and `cursor-agent` CLIs, Playwright
with Chromium, PHP and Composer, the 1Password CLI (`op`), and what devkit's
`extract` profile installs in headless mode: node, graft, Serena, Graphify,
`playwright-cli` and 7-Zip (`7z`). The agent starts as the profile wrapper
(`claude-extract`).

Build it with a checkout of devkit (99x-dev-kit) as the `devkit` build context:

```bash
docker build -f docker/Dockerfile --build-context devkit=<path-to-99x-dev-kit> \
  -t extractkit-ci .
```

In GitLab CI the `docker-build` job fetches devkit at `DEVKIT_REF` from
`DEVKIT_URL` with the job token. That works when 99x-dev-kit lists this project
under Settings > CI/CD > Job token permissions. If it does not, an operator
creates the masked CI variable `CI_DEVKIT_TOKEN` (a token with
`read_repository` on 99x-dev-kit), which the job uses as a fallback. Pin
`DEVKIT_REF` to a devkit tag or commit before the first run.

### `latest`

Starts as uid 1000 (`extract`).

- **Dockerfile**: `docker/Dockerfile`
- **Architecture**: `linux/amd64`
- **Pull command**: `docker pull leanon/extractkit-ci:latest`

### `root`

The same image, started as root. Use it on runners that clone the source as
root; with `latest` the run stops there with `source_not_writable`.

- **Dockerfile**: `docker/Dockerfile`
  with `--build-arg RUN_AS=root`
- **Architecture**: `linux/amd64`
- **Pull command**: `docker pull leanon/extractkit-ci:root`

Both tags are rebuilt on every change to the kit; there are no per-commit
tags.

## Quick start

```bash
docker run --rm \
  -v "$PWD:/work" --user "$(id -u):$(id -g)" \
  -e ANTHROPIC_API_KEY \
  leanon/extractkit-ci:latest --source /work
```

The run writes `extract/` (a visible folder, no `.gitignore`) into the mounted
checkout and prints one JSON document. Exit codes: `0` done, `1` failed, `3` a
human is needed.

## In a pipeline

```yaml
extract:
  image: leanon/extractkit-ci:latest
  variables:
    EXTRACTKIT_AGENT: claude
  script:
    - extractkit headless --source "$CI_PROJECT_DIR" --json | tee extract-result.json
  artifacts:
    name: extract_${PROJECT_SHORT_NAME}_artifacts
    when: always
    paths:
      - extract/
      - extract-result.json
```

The job needs the selected agent's credential, either in its environment or as
an attachment (`EXTRACTKIT_OP_VAULT` and `EXTRACTKIT_OP_ITEM`; see
`docs/headless.md`, section Attachments).
The image
needs no `entrypoint: [""]`: flags run `extractkit headless --json`, and any
other command (`sh`, `git`) runs unchanged.
