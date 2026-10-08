"""The bundled How-tos keep the devkit KB layout and the `kb` command prints them."""

from __future__ import annotations

import unittest

from extractkit_cli import kb
from tests.support import REPO, run

KB = REPO / "kb"


class BundledHowTosTests(unittest.TestCase):
    def test_every_how_to_has_frontmatter_matching_its_file(self) -> None:
        rows = kb.entries(KB)
        self.assertTrue(rows)
        for row in rows:
            with self.subTest(how_to=row["id"]):
                meta, body = kb.split(row["path"].read_text(encoding="utf-8"))
                self.assertEqual(meta.get("id"), row["path"].stem.lower())
                self.assertIn(meta.get("read"), ("section", "whole"))
                self.assertTrue(body.lstrip().startswith("# "))

    def test_every_bucket_index_lists_its_files(self) -> None:
        for bucket in sorted(p for p in KB.iterdir() if p.is_dir()):
            index = (bucket / "llm-index.md").read_text(encoding="utf-8")
            paths = {line.split("\t")[0] for line in index.splitlines() if "\t" in line}
            with self.subTest(bucket=bucket.name):
                self.assertEqual(paths, {p.name for p in bucket.glob("How-to-*.md")})

    def test_no_how_to_names_a_client_host(self) -> None:
        for row in kb.entries(KB):
            text = row["path"].read_text(encoding="utf-8").lower()
            with self.subTest(how_to=row["id"]):
                self.assertNotIn("k8s.seeds.no", text)


class KbCommandTests(unittest.TestCase):
    def test_list_names_every_how_to(self) -> None:
        result = run("kb", "list")
        self.assertEqual(result.returncode, 0, result.stderr)
        for row in kb.entries(KB):
            self.assertIn(row["id"], result.stdout)

    def test_show_prints_the_body_without_frontmatter(self) -> None:
        result = run("kb", "show", "xp7-admin")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("# How to log in to an XP7 admin"))
        self.assertNotIn("when_skills", result.stdout)

    def test_show_refuses_an_unknown_id_with_the_list_fix(self) -> None:
        result = run("kb", "show", "nope")
        self.assertEqual(result.returncode, 1)
        self.assertIn("extractkit kb list", result.stderr)

    def test_show_refuses_an_ambiguous_id(self) -> None:
        result = run("kb", "show", "xp7")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no single how-to", result.stderr)

    def test_kb_runs_from_inside_the_kit(self) -> None:
        result = run("kb", "list", cwd=REPO)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
