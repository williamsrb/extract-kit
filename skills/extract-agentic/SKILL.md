---
name: extract-agentic
description: >
  Run the agent tasks of a 99x-extract-kit sidecar after synthesis: name the
  view-layer business rules, write BUSINESS.md (the general business flow),
  optionally enrich specs. Use when `extractkit status` shows the agent
  phase as current, or when asked to run agent steps, write BUSINESS.md,
  name rules, or enrich a spec. Not for the deterministic pipeline (use
  extract-legacy) and not for XP8/React4XP ports.
---

# Run the agent tasks

The kit never calls a model. It stores each agent step as a prompt
(`agent-tasks/<id>/`), lists it, renders it with real paths, and checks what
you wrote. You do the task. Read `docs/llm.md` for the invariants first.

## Loop

Run from the kit repo. `<sidecar>` is the extract run directory
(`<legacy>/.extract/<run-id>`).

1. `extractkit agent next --out <sidecar> --json`. Read `next`. When it is
   `null` and `blocked` is empty, stop: no required task is pending. When
   `next` is `null` and `blocked` is not empty, tell the operator which
   inputs are missing and run `extractkit status --out <sidecar>`; do not
   skip the task.
2. `extractkit agent show <id> --out <sidecar>`. The output is the full task
   prompt plus the input and output files. Follow it.
3. Do the task in one fresh subagent per task, so a task never inherits the
   previous task's context. Pass the rendered prompt and nothing else.
4. When the task declares `rerun`, run `extractkit <rerun>` with
   `--profile`, `--source` and `--out` added (`agent list --json` shows it).
   `rules.name` needs this: `rules/view-rules.json` only changes on re-run,
   and that is what marks the task done.
5. `extractkit check --out <sidecar>`. Fix each listed problem in the file
   you wrote, then check again. Never report done while it lists problems.
6. Go back to step 1.

`spec.enrich` is optional and `agent next` never returns it. Run it only when
the operator asks: `extractkit agent show spec.enrich --out <sidecar>`.

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

- The source checkout is read-only. Write only under `<sidecar>`.
- Every claim beyond an extracted fact ends with `_(inferred)_` and sits
  under an `Evidence:` line.
- As-is only. No port plans, XP8 advice, `DECISIONS.md` or `IMPLEMENTATION.md`.
- Do not run graft, graphify, Serena onboarding or `git` writes in the source.
- `promote` copies `business/BUSINESS.md` to `BUSINESS.md` in the checkout.
  Run it only when the operator asks.
