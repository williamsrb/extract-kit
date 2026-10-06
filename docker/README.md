# 99x Extract Kit CI

## Quick reference

- **Maintained by**: [99x Brazil](https://99x.io/services/web-solutions)
- **Where to get help**: the private team Slack

## Supported tags

- `latest`: starts as uid 1000.
- `root`: the same image, started as root.

Both tags are `linux/amd64` and are rebuilt on every change to the kit; there
are no per-commit tags.

## What is it?

Extract Kit reads an existing software project and documents what it does:
business rules, pages and components, data, and the systems it talks to, as
standard documents (Spec Kit, OpenAPI, DESIGN.md). This image runs it
headless in a CI pipeline, calling an agent CLI for each agent task.

Included: the kit, the `claude`, `codex` and `cursor-agent` CLIs, Playwright
with Chromium, PHP and Composer, the 1Password CLI (`op`) and 7-Zip (`7z`).

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
    when: always
    paths:
      - .extract/
      - extract-result.json
```

The job needs the selected agent's credential in its environment. The image
needs no `entrypoint: [""]`: flags run `extractkit headless --json`, and any
other command (`sh`, `git`) runs unchanged.

On a runner that clones the source as root, use the `root` tag; otherwise the
run stops with `source_not_writable`.
