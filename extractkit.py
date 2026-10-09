#!/usr/bin/env python3
"""extractkit — read a legacy checkout and write a stack-agnostic extract tree."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from extractkit_cli.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
