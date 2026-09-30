# 99x Extract Kit

Read a legacy checkout and write a **stack-agnostic extract tree**. Enonic XP7
is the first adapter. PHP is an empty placeholder. Spec Kit is an as-is sink
of that tree, not an XP8/React4XP port. Dry-run is the default.

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
./extractkit run --profile enonic --source /path/to/legacy
./extractkit run --profile enonic --source /path/to/legacy --apply
./extractkit check --out /path/to/legacy/.extract/<run-id>
./extractkit next --source /path/to/legacy
./extractkit resume --profile enonic --source /path/to/legacy --apply
./extractkit promote --source /path/to/legacy --apply
```

`--apply` writes `<source>/.extract/<run-id>/`. The kit never edits the source
`.gitignore` or `.git/`. `.extract/.gitignore` contains `*` so the sidecar is
self-ignored.

`./extractkit run --profile php --source …` exits non-zero with the unfinished
work list. It does not parse PHP.

## Static extract

A full pipeline includes live CMS and requires `--branch`. For descriptors,
maps, and OpenAPI only:

```bash
./extractkit run --profile enonic --source /path/to/legacy --apply \
  --until inventory.integrations
```

Then merge, docs, and Spec Kit without CMS:

```bash
./extractkit run --profile enonic --source /path/to/legacy \
  --out /path/to/legacy/.extract/<run-id> --apply \
  --from maps.merge --until spec.kit
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
./extractkit step enonic.cms --profile enonic --source /path/to/legacy --apply \
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

## Tests

```bash
python3 -m unittest discover -s tests
```

Fixtures under `tests/fixtures/enonic-mini/`. No GitLab CI in this kit.
No `PLAN.md` in this repo; the harness plan is `~/.agents/plans/legacy-spec-extractor.md`.
