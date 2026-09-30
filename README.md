# 99x Extract Kit

Read a legacy checkout and write a **stack-agnostic extract tree**. Enonic XP7
is the first adapter. PHP is an empty placeholder. Spec Kit is an as-is sink
of that tree, not an XP8/React4XP port. Every command writes on the first call.

Docs: [profiles](docs/profiles.md), [CLI](docs/cli.md), [output](docs/output.md).

## Install

Python 3.12+ with PyYAML and jsonschema (already on the reference box).

```bash
chmod +x ./extractkit
./extractkit --help
```

No bootstrap, no desktop forks, no writes into `~/.agents-profiles`.

## Commands

```bash
./extractkit profile list
./extractkit profile show enonic
./extractkit profile show php
./extractkit doctor --profile php          # empty PHP is allowed
./extractkit deps --profile enonic
./extractkit run --profile enonic --source /path/to/legacy --until static
./extractkit status --source /path/to/legacy
./extractkit resume --profile enonic --source /path/to/legacy
./extractkit check --out /path/to/legacy/.extract/<run-id>
./extractkit promote --source /path/to/legacy
```

`run` writes `<source>/.extract/<run-id>/`. Each run prints the phases it
touched and ends with a `next` block holding the command to paste next.
`status` (alias `next`) shows every phase as done, current, or pending. See
[CLI](docs/cli.md) for phases, `-v` / `-q`, and the promote guard. The kit
never edits the source `.gitignore` or `.git/`. `.extract/.gitignore`
contains `*` so the sidecar is self-ignored.

`./extractkit run --profile php --source …` exits non-zero with the unfinished
work list. It does not parse PHP.

## Static extract

A full pipeline includes live CMS and requires `--branch`. For descriptors,
maps, and OpenAPI only:

```bash
./extractkit run --profile enonic --source /path/to/legacy --until static
```

Then merge, docs, and Spec Kit without CMS:

```bash
./extractkit run --profile enonic --source /path/to/legacy \
  --out /path/to/legacy/.extract/<run-id> \
  --from merge --until synthesis
```

`extractkit check` validates schemas, FR-10 descriptor coverage, OpenAPI
`x-source`, optional runtime inventory, bounded contexts, and spec.md FR cites.

Static harvest writes `integrations/openapi.yaml` and a **read-only**
Swagger UI under `integrations/swagger-ui/` (`swagger-ui-dist` 5.30.2).
Try it out is disabled. The spec is inlined in `spec.js` so `index.html`
works from `file://`. Live CMS then patches `x-production-endpoints` and
refreshes `spec.js`. Those URLs are never fetched.

## Runtime CMS

`enonic.cms` surveys a **local or review** XP only. Pass `--branch draft|master`.
The Guillotine GraphQL URL is a run parameter (`--guillotine`); production
hosts are refused. Auth is a Playwright storage-state file (`--storage-state`).
Pin keys with `--cms-key`; do not walk the tree. Enonic still samples
**3 contents per type** (`queryConnection` `first=3`) and resolves pages
as customized > explicit `page.template` > implicit `data.supports` in
`/_templates` folder order. That logic is XP7-only
(`steps/enonic/page_templates.py`). PHP has no equivalent.

After the page survey, the same session reads **Site Config** (Content Studio
REST) and **Config Env** (`--configenv`, default XP7
`/admin/tool/no.seeds.configenv/module-config`). Live provider URLs are written
to `inventory/runtime.json` `endpoints` and merged into OpenAPI
`x-production-endpoints` as metadata. Secrets are dropped. Those URLs are
never fetched.

```bash
./extractkit step enonic.cms --profile enonic --source /path/to/legacy \
  --out /path/to/legacy/.extract/<run-id> \
  --branch draft \
  --storage-state ~/.agents/.auth/xp7-localhost.json \
  --guillotine http://localhost:8080/admin/site/preview/en/draft \
  --cms-key /en
```

`maps.merge` then marks surveyed page/layout/part/macro surfaces `live` or
`dead`, writes `inventory/merge-report.md`, and splits
`map/bounded-contexts.json`.

## Promote

Explicit. Copies as-is Spec Kit constitution to
`.specify/memory/constitution.md` (the path Spec Kit reads), plus PRODUCT,
DESIGN, and `specs/<context>/spec.md`. Does not copy the sidecar into git.
Refuses, writing nothing, when an existing destination has changes git cannot
restore (modified, staged, untracked, ignored, or a source outside git). Pass
`--force` to overwrite anyway.

## Tests

```bash
python3 -m unittest discover -s tests
```

Fixtures under `tests/fixtures/enonic-mini/`. No GitLab CI in this kit.
No `PLAN.md` in this repo; the harness plan is `~/.agents/plans/legacy-spec-extractor.md`.
