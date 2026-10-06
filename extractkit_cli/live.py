"""Live progress lines on stderr, so a long run is not silent.

stdout stays for the command's result (text or the `--json` envelope); progress
goes to stderr. `run`, `step` and `resume` print theirs only with `--progress`;
`extractkit headless` always does and passes `--progress` to the children it
starts, then forwards their lines.
"""

from __future__ import annotations

import sys
import time
from argparse import Namespace

_enabled = False


def enable(args: Namespace) -> None:
    global _enabled
    _enabled = bool(getattr(args, "progress", False))


def stamp() -> str:
    return time.strftime("%H:%M:%S")


def say(text: str, *, indent: int = 0, force: bool = False) -> None:
    if _enabled or force:
        print(f"{stamp()} {'  ' * indent}{text}", file=sys.stderr, flush=True)


def duration(seconds: float) -> str:
    seconds = round(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, rest = divmod(seconds, 60)
    return f"{minutes}m{rest:02d}s" if minutes < 60 else f"{minutes // 60}h{minutes % 60:02d}m"
