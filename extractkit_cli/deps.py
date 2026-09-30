"""`extractkit deps` — every binary a profile declares is on PATH."""

from __future__ import annotations

import shutil
from argparse import Namespace

from . import guide, manifest


def cmd_deps(args: Namespace) -> int:
    profile = manifest.load(args.profile)
    required = manifest.provided_binaries(profile, include_optional=False)
    optional = [
        b for b in manifest.provided_binaries(profile) if b not in required
    ]
    missing: list[str] = []
    print(f"deps: profile {profile['name']}")
    for binary in required:
        found = shutil.which(binary)
        if found:
            print(f"  ok       {binary:22s} {found}")
        else:
            print(f"  MISSING  {binary:22s}")
            missing.append(binary)
    for binary in optional:
        found = shutil.which(binary)
        print(
            f"  {'ok      ' if found else 'skipped '} {binary:22s} "
            f"{found or '(optional)'}"
        )
    if missing:
        print(f"\n{len(missing)} required tool(s) missing: {', '.join(missing)}")
        return 1
    suggestion = guide.next_for("deps", "clean", args)
    print()
    guide.emit(guide.render_next(suggestion, guide.style_for()))
    return 0
