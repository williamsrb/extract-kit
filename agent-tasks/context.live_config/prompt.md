# Task context.live_config: write the live_config rules

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

`enonic.cms` turns Site Config and Config Env values into endpoints
(`endpoints` in `inventory/runtime.json`, `x-production-endpoints` in
`integrations/openapi.yaml`). Which keys hold endpoints, which provider each
belongs to, and how an environment value picks an origin are project facts.
They live in the `live_config` key of `{sidecar}/context/profile.yaml`. The
kit reads the rules and never infers them; you write them from evidence.

## Inputs

- `{sidecar}/inventory/live-config-candidates.json`: every public Site Config
  and Config Env key whose value is a URL (`kind: url`) or a host map
  (`kind: hostmap`), with `origin: siteConfig|configEnv` and whether the
  current rules already cover it (`covered`). Secrets never appear.
- `{sidecar}/inventory/runtime.json`: `siteConfig`, `configEnv`, `endpoints`
  and `configenv`, as harvested.
- `{sidecar}/integrations/openapi.yaml`: the integrations the static
  inventory found.
- `{source}`: `site/site.xml` for the Site Config field names, the code that
  reads each key, and any environment files.

## What to write

Edit only the `live_config` key of `{sidecar}/context/profile.yaml`. Leave
`_comment`, `extends` and `exclude` alone, and write nothing under
`{source}`. Set `configenv_path` only when the source shows a Config Env admin tool; a stack profile does not set it.

```yaml
live_config:
  site_url_keys: [tourplanurl]
  hostmap_keys: [env-hostmap]
  providers:
    tourplan: Tourplan
  env_endpoints:
    - provider: Netaxept
      key: netaxeptEnv
      origins:
        test: https://test.example.test
      default: https://example.test
      urls:
        - /Pay/Register.aspx
```

- `site_url_keys`: Site Config leaf keys (case-insensitive) whose `http(s)`
  value is an endpoint.
- `hostmap_keys`: Config Env keys whose value is a comma list of
  `<path>=<host>` pairs (inbound hosts). Matched case-insensitively, and also
  as a suffix.
- `providers`: leaf substring (case-insensitive) mapped to a provider name,
  tried in order. A key that matches none is named by its leaf.
- `env_endpoints`: rules for a Site Config key whose value picks an
  environment. Each row has `provider`, `key` (the leaf), optional `path` (a
  substring of the full key, to tell two same-named leaves apart), `origins`
  (value to origin), `default` (the origin when no value matches) and `urls`
  (path suffixes appended to the chosen origin; one empty suffix by default).
- An empty `live_config` mapping is a valid answer when no candidate needs a rule.

## Rules for the evidence

1. Start from the candidate rows with `covered: false`. A covered row needs no
   rule. Skip keys that are internal or not an integration.
2. Every key, every URL path and every origin host must be grounded: it
   occurs in `{source}` (an origin host may be built in a template literal, so
   all its labels on one source line count) or among the harvested config.
   `extractkit check` rejects anything else. Never write a value you did not
   see.
3. Above each entry, add a YAML comment naming where you saw it: a source
   `file:line`, a candidate row (`candidates: configEnv env-hostMap`), or a
   `runtime.json` key.
4. URLs are metadata. Never fetch one, and do not copy the value of a key the
   candidates left out.
5. Re-run the CMS step so `runtime.json` is rebuilt with the new rules. The
   `Re-run:` line below prints only `step inventory.runtime`. Repeat the CMS
   flags of the run that wrote `runtime.json`: `--source {source}`,
   `--out {sidecar}`, `--branch`, `--storage-state`, `--guillotine` or
   `--xp-host`, and `--cms-key`. Then read `endpoints` in
   `inventory/runtime.json` and confirm each rule produced what you meant.
6. Run `extractkit check --out {sidecar}`. The `context_grounded` check
   names every ungrounded entry with its path in the overlay.
