"""Operator excludes (`--exclude`, profile `exclude:`) and the doctor build-scope row."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from extractkit_cli import buildscope, scope
from extractkit_cli.errors import ExtractkitError
from tests.support import STATIC_UNTIL, as_profile, copy_fixture, run, sidecar_run_dir


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class ScopeTests(unittest.TestCase):
    def test_normalize_sorts_dedups_and_strips(self) -> None:
        self.assertEqual(
            scope.normalize(["./prototype/", "prototype", "apps\\old", "."]),
            ["apps/old", "prototype"],
        )

    def test_normalize_refuses_paths_outside_the_source(self) -> None:
        for bad in ("/etc", "../other", "a/../../b", ""):
            with self.assertRaises(ExtractkitError, msg=bad):
                scope.normalize([bad])

    def test_is_excluded_matches_whole_segments(self) -> None:
        self.assertTrue(scope.is_excluded("prototype", ["prototype"]))
        self.assertTrue(scope.is_excluded("prototype/js/a.js", ["prototype"]))
        self.assertFalse(scope.is_excluded("prototype-old/a.js", ["prototype"]))
        self.assertFalse(scope.is_excluded("xp/prototype/a.js", ["prototype"]))

    def test_iter_files_prunes_skip_dirs_and_excludes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for rel in ("xp/a.js", "proto/b.js", "xp/node_modules/c.js", "xp/proto/d.js"):
                _write(root / rel, "x")
            found = sorted(p.relative_to(root).as_posix() for p in scope.iter_files(root, ["proto"]))
        self.assertEqual(found, ["xp/a.js", "xp/proto/d.js"])


class ExcludeRunTests(unittest.TestCase):
    def _source(self, parent: Path) -> Path:
        source = copy_fixture(parent)
        _write(source / "prototype" / "js" / "app.js", "$('.title').on('click', function () {})\n")
        _write(source / "prototype" / "index.html", '<script src="jquery.min.js"></script>\n')
        return source

    @staticmethod
    def _template_paths(out: Path) -> list[str]:
        data = json.loads((out / "inventory" / "templates.json").read_text())
        return [row["path"] for row in data["files"]]

    def test_without_exclude_the_folder_is_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = self._source(Path(raw))
            result = run("run", "--profile", "enonic", "--source", str(source), *STATIC_UNTIL)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            paths = self._template_paths(sidecar_run_dir(source))
        self.assertTrue(any(p.startswith("prototype/") for p in paths), paths)

    def test_exclude_is_honoured_recorded_and_kept_on_a_later_step(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = self._source(Path(raw))
            result = run(
                "run", "--profile", "enonic", "--source", str(source),
                "--exclude", "prototype/", *STATIC_UNTIL,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            out = sidecar_run_dir(source)
            self.assertFalse(any(p.startswith("prototype/") for p in self._template_paths(out)))
            coverage = json.loads((out / "inventory" / "templates.json").read_text())["coverage"]
            self.assertIn("prototype", coverage["excluded"])
            self.assertEqual(yaml.safe_load((out / "MANIFEST.yaml").read_text())["exclude"], ["prototype"])

            again = run(
                "step", "inventory.templates", "--profile", "enonic",
                "--source", str(source), "--out", str(out),
            )
            self.assertEqual(again.returncode, 0, again.stderr + again.stdout)
            self.assertFalse(any(p.startswith("prototype/") for p in self._template_paths(out)))
            self.assertEqual(yaml.safe_load((out / "MANIFEST.yaml").read_text())["exclude"], ["prototype"])

    def test_exclude_outside_the_source_exits_with_a_fix(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = self._source(Path(raw))
            result = run(
                "run", "--profile", "enonic", "--source", str(source),
                "--exclude", "../elsewhere", *STATIC_UNTIL,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("not a path relative to the source", result.stdout + result.stderr)

    def test_the_as_override_excludes_the_prototypes(self) -> None:
        self.assertEqual(as_profile().get("exclude"), ["prototype", "prototype-old"])


CI = """\
stages: [build]
.build_template:
  before_script:
    - cd app/
    - ./gradlew build
master_build:
  extends: .build_template
  only: [master]
review_build:
  extends: .build_template
  only: [review]
prototype_build:
  script: [docker build proto/]
  only: [prototype]
nightly:
  script: [run tools/nightly.sh]
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
reference_job:
  script: !reference [.build_template, before_script]
  except: [master]
"""

MAKEFILE = """\
APP := app
PROTO := proto
all: up

up:
\tdocker-compose -f docker/dev/docker-compose.yml up

protoUp:## [Prototype] run it
\tdocker-compose -f $(PROTO)/docker-compose.yml up
"""


class BuildScopeTests(unittest.TestCase):
    def _tree(self, root: Path, *dirs: str) -> None:
        for name in dirs:
            (root / name).mkdir()

    def test_reports_folders_no_default_branch_build_names(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            subprocess.run(["git", "init", "-q", "-b", "master", str(root)], check=True)
            self._tree(root, "app", "docker", "proto", "old", "tools", "src", "node_modules", ".vscode")
            _write(root / ".gitlab-ci.yml", CI)
            _write(root / "Makefile", MAKEFILE)
            found = buildscope.analyze(root, [])
            self.assertEqual(found.entry_points, [".gitlab-ci.yml", "Makefile"])
            self.assertEqual(found.in_scope, ["app", "docker", "tools"])
            self.assertEqual(found.out_of_scope, ["old", "proto", "src"])

            row = buildscope.check(root, ["old"])
            self.assertEqual(row.state, "warn")
            self.assertFalse(row.failed)
            self.assertIn("proto, src", row.detail)
            self.assertIn("--exclude proto --exclude src", row.fix)

    def test_root_gradle_build_keeps_src(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._tree(root, "src")
            _write(root / "build.gradle", "plugins { id 'java' }\n")
            row = buildscope.check(root)
        self.assertEqual(row.state, "ok")

    def test_package_scripts_count_as_an_entry_point(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._tree(root, "web", "legacy")
            _write(root / "package.json", json.dumps({"scripts": {"build": "cd web && vite build"}}))
            found = buildscope.analyze(root, [])
        self.assertEqual((found.in_scope, found.out_of_scope), (["web"], ["legacy"]))

    def test_no_entry_point_skips(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._tree(root, "anything")
            row = buildscope.check(root)
        self.assertEqual(row.state, "skipped")
        self.assertFalse(row.failed)


if __name__ == "__main__":
    unittest.main()
