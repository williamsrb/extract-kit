# Task context.exclude: decide which folders are not part of the product

Sidecar: `{sidecar}`
Source (read-only): `{source}`
Profile: `{profile}`
Run: `{run_id}`

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

The `context` phase records which top-level folders no default-branch build
touches, in `{sidecar}/context/build-scope.json`: `branch`, `entry_points`,
`in_scope` and `out_of_scope`. It never excludes any of them. A folder outside
the build is not always outside the product: cron scripts, shared config and
deploy files often are. Your job is the judgment the kit cannot make.

1. Read `{sidecar}/context/build-scope.json`. If `out_of_scope` is empty,
   or `entry_points` is, there is nothing to decide; the kit already wrote
   `exclude: []`.
2. For each folder in `out_of_scope`, open it in `{source}` and read enough
   to tell what it is: its README, a few files, the build files named in
   `entry_points`, and how the rest of the code refers to it. A folder is
   **not part of the product** when it is a prototype, a retired copy of code
   that nothing runs, an experiment, or a vendored sample. It **is** part of
   the product when something the product runs lives there (cron or batch
   scripts, migrations, shared assets, environment config the app reads).
3. Edit only the `exclude` key of `{sidecar}/context/profile.yaml`. Leave
   `_comment`, `extends` and `live_config` alone, and write nothing under
   `{source}`. Set `exclude` to the folder names you decided are not part
   of the product, written as in `out_of_scope`. `exclude: []` is a valid
   answer. Above the key, add one YAML comment line per folder in
   `out_of_scope`, saying `excluded` or `kept` and the evidence (a
   `file:line` or the `build-scope.json` row), for example
   `# prototype: excluded, ships from the prototype branch only (.gitlab-ci.yml:42)`.
4. Choose only from `out_of_scope`. `extractkit check` rejects an entry that is
   not in it. When you cannot tell, keep the folder: an exclusion cannot be
   undone in this sidecar, because exclude lists merge as a union across
   layers and a resumed run keeps what `MANIFEST.yaml` already excluded.
   Fixing a wrong exclusion means a new sidecar.
5. Re-run the pipeline so the scans skip the excluded folders. The `Re-run:`
   line below prints only `run --from static --until synthesis`. Add the
   flags of the run that wrote this sidecar: `--source {source}`,
   `--out {sidecar}`, and, when the CMS was captured, `--branch`,
   `--storage-state`, `--guillotine` or `--xp-host`, and `--cms-key`. If the
   earlier run had no CMS flags, stop at `--until inventory.integrations`
   instead, because the CMS slot refuses to run without them.
6. Run `extractkit check --out {sidecar}`. The `context_grounded` check
   fails when an `exclude` entry is outside `out_of_scope`.
