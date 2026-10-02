---
name: extract-agentic
description: >
  Run the agent tasks of a 99x-extract-kit sidecar after synthesis: name the
  view-layer business rules, write BUSINESS.md (the general business flow),
  optionally enrich specs. Also decides the project context
  (`context.exclude`, `context.live_config`). Use when `extractkit status` shows the agent
  phase as current, or when asked to run agent steps, write BUSINESS.md,
  name rules, or enrich a spec. Not for the deterministic pipeline (use
  extract-legacy) and not for XP8/React4XP ports.
---

# Run the agent tasks

The kit never calls a model, except `extractkit headless`, which starts an
agent CLI for a pipeline run. It stores each agent step as a prompt
(`agent-tasks/<id>/`), lists it, renders it with real paths, and checks what
you wrote. You do the task. Read `~/.local/share/extractkit/docs/llm.md` for
the invariants first.

## Loop

Run from the legacy checkout, in a session opened there, so Serena and
file reads resolve against the code being described. `extractkit` must be
on PATH (`./extractkit install` in a kit checkout; the checkout can be
deleted afterwards). `<sidecar>` is the extract run directory
(`.extract/<run-id>` under the checkout).

In a headless run there is no operator. The prompt you are given then starts
with the headless preamble: where a task says to stop and ask the operator,
write `<sidecar>/reports/blockers/<task id>.md` (`Reason:` and `Evidence:`
lines) and stop. The analyst gates stay: never tick a review box, never set
`out-of-scope`.

1. `extractkit agent next --out <sidecar> --json`. Read `next`. When it is
   `null` and `blocked` is empty, stop: no required task is pending. When
   `next` is `null` and `blocked` is not empty, tell the operator which
   inputs are missing and run `extractkit status --out <sidecar>`; do not
   skip the task.
2. `extractkit agent show <id> --out <sidecar>`. The output is the full task
   prompt plus the input and output files. Follow it.
3. Do each task in a fresh context, so a task never inherits the previous
   task's context: one subagent per task when your assistant has subagents,
   otherwise a new session. Pass the rendered prompt and nothing else.
4. When the task declares `rerun`, run `extractkit <rerun>` with
   `--source` and `--out` added, plus `--profile` when detection needs it
   (`agent list --json` shows the tokens). `rules.name` needs this:
   `rules/view-rules.json` only changes on re-run, and that is what marks the
   task done. The two `context.*` tasks must also repeat the CMS flags of
   the earlier run (`--branch`, `--storage-state`, `--guillotine` or
   `--xp-host`, `--cms-key`), because the `Re-run:` line prints only the
   `rerun` tokens.
5. `extractkit check --out <sidecar>`. Fix each listed problem in the file
   you wrote, then check again. Never report done while it lists problems.
6. Go back to step 1.

The two `context.*` tasks come before the rest in `agent next` and are ready
earlier than the agent phase: `context.exclude` after the static phase,
`context.live_config` after the CMS slot. Do them when `next` offers them,
not at the end. Both write into `<sidecar>/context/profile.yaml`, only
their own key, and cite their evidence in YAML comments. `check` rejects an
`exclude` outside `context/build-scope.json` `out_of_scope` and a
`live_config` fact the source and the harvested config do not support. When
unsure whether a folder is part of the product, keep it: an exclusion cannot
be undone in the same sidecar.

`spec.enrich` is optional and `agent next` never returns it. Run it only when
the operator asks: `extractkit agent show spec.enrich --out <sidecar>`.
`spec.review` is optional too, and `agent next` never returns it. It reviews the
generated specs for meaning and writes only `reports/spec-review.md`; it
edits no spec, and `promote` never copies the report. Run it when the
operator asks: `extractkit agent show spec.review --out <sidecar>`. `check`
validates the report's format, never its findings.

## Analyst gates

- Never tick `[x]` in `rules/review.md`. Only the analyst confirms a rule.
- Never set `out-of-scope: yes` unless the operator said so.
- Do not choose between divergent copies of a rule. List them as open
  questions.

## Stop and ask the operator when

- `agent next` is blocked on a missing input.
- A source file the task cites does not exist or has no such line.
- `check` still fails after two fix attempts on the same problem.
- The task would need a write outside `<sidecar>`.

## Rules

- The source checkout is read-only. Write only under `<sidecar>`. Never
  create or edit `<source>/.extractkit/profile.yaml`; it is the operator's.
- Every claim beyond an extracted fact ends with `_(inferred)_` and sits
  under an `Evidence:` line.
- As-is only. No port plans, XP8 advice, `DECISIONS.md` or `IMPLEMENTATION.md`.
- Do not run graft, graphify, Serena onboarding or `git` writes in the source.
- `promote` copies `business/BUSINESS.md` to `BUSINESS.md` in the checkout.
  Run it only when the operator asks.
