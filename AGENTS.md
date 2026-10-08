# Agent instructions

This repo is Extract Kit. Any coding assistant can drive it; the kit
never calls a model, except `extractkit headless`, which starts an agent CLI
for a pipeline run. Read [docs/llm.md](docs/llm.md) first: it holds the
invariants, the command sequence per phase, and the failure table.

Sessions opened in this repo are for working on the kit. To extract a
project, run `./extractkit install` here once, then open the legacy
checkout in a new session and run `extractkit` from there.

## Skills

The canonical skills live in `skills/`. `.agents/skills/` (Codex, Cursor and
other assistants) and `.claude/skills/` (Claude Code) are symlinks to them;
edit only `skills/`. `extractkit install` copies them into
`~/.agents/skills/` (and links `~/.claude/skills/` to those copies), so a
session opened in the legacy checkout loads them too. The install is
detached: it also copies the kit to `~/.local/share/extractkit`, so the
kit checkout can be deleted afterwards.

<!-- markdownlint-disable MD013 -->
| Skill | Use it to |
| --- | --- |
| [extract-legacy](skills/extract-legacy/SKILL.md) | Walk the deterministic pipeline, resume a sidecar, promote Spec Kit files |
| [extract-agentic](skills/extract-agentic/SKILL.md) | Run the agent tasks: decide the context (`context.exclude`, `context.live_config`), name the rules, write `BUSINESS.md`, enrich specs |
<!-- markdownlint-enable MD013 -->

An assistant that does not load skills reads the `SKILL.md` file and
follows it as a procedure.

## Knowledge base

`kb/<bucket>/How-to-*.md` holds How-tos in the devkit KB layout (frontmatter
plus a generated `llm-index.md` per bucket). `extractkit kb list` and
`kb show ID` print them. The CMS phase reads `kb/enonic/` (log in to an XP7,
traverse its CMS). The source of each file is `~/.agents/kb/implementation/`;
edit it there, then copy it here and rebuild the index with devkit's
`llm_index.py`. The How-tos keep the KB's long lines, so they do not pass
markdownlint at 80 columns.

## Agent tasks

The prompts are in `agent-tasks/<id>/prompt.md`. Render one with real paths
with `extractkit agent show <id> --out <sidecar>`, and validate the result
with `extractkit check --out <sidecar>`. Run each task in a fresh context:
a subagent when your assistant has them, otherwise a new session.

## Tests

```bash
python3 -m unittest discover -s tests
```
