# Agent instructions

This repo is 99x Extract Kit. Any coding assistant can drive it; the kit
never calls a model. Read [docs/llm.md](docs/llm.md) first: it holds the
invariants, the command sequence per phase, and the failure table.

Sessions opened in this repo are for working on the kit. To extract a
project, run `./extractkit install` here once, then open the legacy
checkout in a new session and run `extractkit` from there.

## Skills

The canonical skills live in `skills/`. `.agents/skills/` (Codex, Cursor and
other assistants) and `.claude/skills/` (Claude Code) are symlinks to them;
edit only `skills/`. `extractkit install` links them into
`~/.agents/skills/` and `~/.claude/skills/`, so a session opened in the
legacy checkout loads them too.

<!-- markdownlint-disable MD013 -->
| Skill | Use it to |
| --- | --- |
| [extract-legacy](skills/extract-legacy/SKILL.md) | Walk the deterministic pipeline, resume a sidecar, promote Spec Kit files |
| [extract-agentic](skills/extract-agentic/SKILL.md) | Run the agent tasks: decide the context (`context.exclude`, `context.live_config`), name the rules, write `BUSINESS.md`, enrich specs |
<!-- markdownlint-enable MD013 -->

An assistant that does not load skills reads the `SKILL.md` file and
follows it as a procedure.

## Agent tasks

The prompts are in `agent-tasks/<id>/prompt.md`. Render one with real paths
with `extractkit agent show <id> --out <sidecar>`, and validate the result
with `extractkit check --out <sidecar>`. Run each task in a fresh context:
a subagent when your assistant has them, otherwise a new session.

## Tests

```bash
python3 -m unittest discover -s tests
```
