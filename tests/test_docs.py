"""The docs stay true to the code: llm.md commands parse, every slot is documented."""

from __future__ import annotations

import re
import shlex
import unittest

from extractkit_cli import manifest
from extractkit_cli.cli import build_parser
from tests.support import REPO

LLM = REPO / "docs" / "llm.md"
FENCE = re.compile(r"```bash\n(.*?)```", re.DOTALL)
COMMAND = re.compile(r"^(?:\$ )?(?:\./)?extractkit\s+(.*)$")


def commands(text: str) -> list[list[str]]:
    found: list[list[str]] = []
    for block in FENCE.findall(text):
        for line in block.replace("\\\n", " ").splitlines():
            match = COMMAND.match(line.strip())
            if match:
                found.append(shlex.split(match.group(1), comments=True))
    return found


class LlmDocTests(unittest.TestCase):
    def test_every_command_line_parses(self) -> None:
        found = commands(LLM.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(found), 8)
        parser = build_parser()
        for argv in found:
            with self.subTest(argv=argv):
                try:
                    args = parser.parse_args(argv)
                except SystemExit as exc:
                    self.fail(f"extractkit {' '.join(argv)} does not parse (exit {exc.code})")
                self.assertTrue(hasattr(args, "func"))

    def test_readme_links_llm_md_first(self) -> None:
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        docs_line = next(line for line in readme.split("\n\n") if line.startswith("Docs:"))
        self.assertTrue(docs_line.startswith("Docs: [LLM instructions](docs/llm.md)"))

    def test_skill_points_at_llm_md(self) -> None:
        skill = (REPO / "skills" / "extract-legacy" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("docs/llm.md", skill)


class StepsDocTests(unittest.TestCase):
    def test_every_core_slot_is_in_steps_md(self) -> None:
        steps = (REPO / "docs" / "steps.md").read_text(encoding="utf-8")
        for slot in manifest.pipeline_ids(manifest.load("core")):
            with self.subTest(slot=slot):
                self.assertIn(f"`{slot}`", steps)
                self.assertRegex(steps, rf"(?m)^## {re.escape(slot)}\b")

    def test_core_phases_match_the_cli_table(self) -> None:
        cli = (REPO / "docs" / "cli.md").read_text(encoding="utf-8")
        for phase in manifest.load("core")["phases"]:
            for slot in phase.get("slots") or []:
                with self.subTest(slot=slot):
                    self.assertIn(slot, cli)


if __name__ == "__main__":
    unittest.main()
