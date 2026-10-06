# 99x Extract Kit CI

## Quick reference

- **Maintained by**:
  [99x Brazil](https://99x.io/services/web-solutions)
- **Where to get help**:
  [the private team Slack](https://leanonteam.slack.com)

## Supported tags and respective image links

- [`latest`](https://hub.docker.com/layers/leanon/extractkit-ci/latest)
- [`root`](https://hub.docker.com/layers/leanon/extractkit-ci/root)

## Quick reference (cont.)

- **Published image artifact details**:
  [`docker/Dockerfile`](https://git.seeds.no/williams/99x-extract-kit/-/blob/docker/docker/Dockerfile)
  ([history](https://git.seeds.no/williams/99x-extract-kit/-/commits/docker/docker/Dockerfile))
- **Source of this description**:
  [`docker/README.md`](https://git.seeds.no/williams/99x-extract-kit/-/blob/docker/docker/README.md)
  ([history](https://git.seeds.no/williams/99x-extract-kit/-/commits/docker/docker/README.md))

## What is it?

Extract Kit reads an existing software project and documents what it does:
business rules, pages and components, data, and the systems it talks to, as
standard documents (Spec Kit, OpenAPI, DESIGN.md). This image runs it
headless in a CI pipeline, calling an agent CLI for each agent task.

Included: the kit, the `claude`, `codex` and `cursor-agent` CLIs, Playwright
with Chromium, PHP and Composer, the 1Password CLI (`op`) and 7-Zip (`7z`).

### `latest`

Starts as uid 1000 (`extract`).

- **Dockerfile**: [`docker/Dockerfile`](https://git.seeds.no/williams/99x-extract-kit/-/blob/docker/docker/Dockerfile)
- **Architecture**: `linux/amd64`
- **Pull command**: `docker pull leanon/extractkit-ci:latest`

### `root`

The same image, started as root. Use it on runners that clone the source as
root; with `latest` the run stops there with `source_not_writable`.

- **Dockerfile**: [`docker/Dockerfile`](https://git.seeds.no/williams/99x-extract-kit/-/blob/docker/docker/Dockerfile)
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

The run writes `.extract/` into the mounted checkout and prints one JSON
document. Exit codes: `0` done, `1` failed, `3` a human is needed.

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
      - .extract/
      - extract-result.json
```

The job needs the selected agent's credential in its environment. The image
needs no `entrypoint: [""]`: flags run `extractkit headless --json`, and any
other command (`sh`, `git`) runs unchanged.
