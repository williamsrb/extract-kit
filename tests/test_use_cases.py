"""use_cases: every surveyed runtime page gets a journey."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from extractkit_cli import manifest
from extractkit_cli.common import Plan
from extractkit_cli.runner import RunContext
from steps.core.use_cases import UseCasesStep


def _ctx(parent: Path, pages: list[dict], contexts: list[dict]) -> RunContext:
    out = parent / "out"
    for folder in ("inventory", "map"):
        (out / folder).mkdir(parents=True)
    (out / "inventory/runtime.json").write_text(json.dumps({"pages": pages}), encoding="utf-8")
    (out / "map/bounded-contexts.json").write_text(json.dumps({"contexts": contexts}), encoding="utf-8")
    return RunContext(source=parent, out=out, profile=manifest.load("enonic"), plan=Plan(), run_id="t")


class RuntimeJourneyTests(unittest.TestCase):
    def test_a_page_outside_any_runtime_context_still_gets_a_journey(self) -> None:
        pages = [
            {"key": "/en", "path": "/en", "round": 1, "context": "page", "templateOrder": ["a:part:p"]},
            {"key": "/en/bare", "path": "/en/bare", "round": 1, "context": "page"},
            {"key": "/en/shop", "path": "/en/shop", "round": 1, "context": "shop"},
        ]
        contexts = [{"id": "runtime-page", "title": "Runtime: page", "surfaces": ["a:part:p"]}]
        with tempfile.TemporaryDirectory() as raw:
            ctx = _ctx(Path(raw), pages, contexts)
            UseCasesStep().run(ctx)
            text = "".join(p.read_text() for p in (ctx.out / "use-cases").glob("*.md"))
            for path in ("/en", "/en/bare", "/en/shop"):
                self.assertIn(f"## Open `{path}`", text)
            self.assertEqual(text.count("## Open `/en`"), 1)
