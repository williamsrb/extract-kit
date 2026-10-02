"""The one exception type extractkit raises for expected, actionable failures."""

from __future__ import annotations


class ExtractkitError(Exception):
    """A failure that names the command which fixes it.

    Raise this for anything the operator can act on: a missing profile, an
    unbound adapter, a failed check gate. Programming errors stay as ordinary
    exceptions so they keep their traceback.

    `fix_args` maps a flag to its value (`None` for a boolean flag). When set,
    the CLI prints the operator's own command with those flags applied.

    `code` is a stable machine id for `--json` consumers (`error.code`); it
    stays `"error"` where no specific code applies.
    """

    def __init__(
        self,
        message: str,
        fix: str | None = None,
        fix_args: dict[str, str | None] | None = None,
        code: str = "error",
    ) -> None:
        super().__init__(message)
        self.fix = fix
        self.fix_args = fix_args
        self.code = code
