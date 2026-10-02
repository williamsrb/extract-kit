# Headless preflight

You are running unattended in a pipeline. There is no operator to answer
questions, and nothing will read a reply except the exit code and the files
you leave behind. Work in `{source}`, which is the legacy checkout being
extracted.

Do exactly two things, in this order, then stop.

1. Serena onboarding for this project. Use the Serena MCP tools: activate the
   project at `{source}`, run the onboarding, and let it write its memories.
   Done means `.serena/project.yml` exists and `.serena/memories/` holds at
   least one `.md` file.
2. A Graphify index of `.`. Run `graphify update .` from `{source}`: it
   re-extracts the code graph and needs no model. If it does not produce
   `graphify-out/graph.json`, follow the graphify skill (`/graphify .`)
   instead. Done means `graphify-out/graph.json` exists.

Rules:

- Create nothing else. The only new folders are `.serena/` and
  `graphify-out/`. Do not edit, move or delete any other file in the checkout.
- Run no git write command (no add, commit, stash, checkout or reset).
- Do not run `extractkit`.
- Do not ask questions. If a step cannot be completed, leave the other step's
  output in place and say in your last message which step failed and why.
