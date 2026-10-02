# Headless run

There is no operator in this run and nobody to answer a question. These rules
override the task below wherever they conflict.

- Where the task says to stop and ask the operator, tell the operator, or
  wait: do not wait. Write `{sidecar}/reports/blockers/<task id>.md` with
  exactly these two lines, then stop and exit:

  ```text
  Reason: <one line: what is missing or wrong>
  Evidence: <paths, line numbers or command output that show it>
  ```

- A blocker means the task cannot be done from the inputs you have: a required
  input file is missing, a line the task cites does not exist, or
  `extractkit check` still fails after your second correction. Do not guess to
  avoid writing one.
- The analyst gates stay closed. Never tick `[x]` in `rules/review.md`, never
  set `out-of-scope: yes`, and when you are unsure whether a folder is part of
  the product, keep it.
- Run only the `extractkit` commands the task names, from `{source}`. Do not
  edit the checkout. Write only the files the task lists.
- After you stop, the driver re-runs the task's re-run command and
  `extractkit check` itself and, if `check` fails, starts you again with the
  problems. Where the task says to re-run the pipeline or run `check`, you may
  skip that step and stop once the files are written.
- Do not end with a question. End with one line: `done` or `blocked: <task id>`.
