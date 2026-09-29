"""The one exception type extractkit raises for expected, actionable failures."""

from __future__ import annotations


class ExtractkitError(Exception):
    """A failure that names the command which fixes it.

    Raise this for anything the operator can act on: a missing profile, an
    unbound adapter, a failed check gate. Programming errors stay as ordinary
    exceptions so they keep their traceback.
    """

    def __init__(self, message: str, fix: str | None = None) -> None:
        super().__init__(message)
        self.fix = fix
