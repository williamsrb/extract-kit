"""Attachments are found by content: any name, 7z / zip / yaml / json, a password only when one is needed.

Nothing here may raise for a bad file or a bad password: each is a printed problem.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import yaml

from extractkit_cli import assets, cli
from tests.test_xp_login import PASSWORD, XP7, XP8, serve

SECRET = "tok-SECRET-value"
HAS_7Z = shutil.which("7z") is not None
AGENT = {"api_key_env": "CLAUDE_CODE_OAUTH_TOKEN", "conflicting_env": ["ANTHROPIC_API_KEY"]}


def resource(kind: str, **data: object) -> str:
    return yaml.safe_dump({"resource": {"type": kind, "data": data}})


def seven(archive: Path, member: str, text: str, password: str | None = None) -> None:
    source = archive.parent / member
    source.write_text(text, encoding="utf-8")
    command = ["7z", "a", "-bd", "-bso0", "-bsp0", str(archive), str(source)]
    if password:
        command.insert(2, f"-p{password}")
        command.insert(3, "-mhe=on")
    subprocess.run(command, check=True, capture_output=True)
    source.unlink()


class AssetsCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="assets-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.folder = self.tmp / "in"
        self.folder.mkdir()
        self.work = self.tmp / "work"
        self.work.mkdir()

    def collect(self, passwords: list[str] | None = None, **kw: object) -> assets.Bundle:
        args = {"directory": self.folder, "op_vault": None, "op_item": None, **kw}
        return assets.collect(passwords=passwords or [], workdir=self.work, environ=os.environ, **args)

    def assertNoSecret(self, bundle: assets.Bundle) -> None:
        for problem in bundle.problems:
            self.assertNotIn(SECRET, problem)


class ReadingTests(AssetsCase):
    def test_yaml_and_json_are_read_whatever_their_names(self) -> None:
        (self.folder / "a.yaml").write_text(resource("agent_api_key", token=SECRET), encoding="utf-8")
        (self.folder / "whatever.bin").write_text(json.dumps({"resource": {"type": "cms_url", "data": {"url": "u"}}}), encoding="utf-8")
        (self.folder / "no-extension").write_text(resource("other", x=1), encoding="utf-8")
        bundle = self.collect()
        self.assertEqual(sorted(r.type for r in bundle.resources), ["agent_api_key", "cms_url", "other"])
        self.assertEqual(bundle.problems, [])
        self.assertEqual(bundle.files, 3)

    @unittest.skipUnless(HAS_7Z, "7z is not installed")
    def test_archives_open_with_no_password_or_the_right_one(self) -> None:
        seven(self.folder / "plain.7z", "m.yaml", resource("agent_api_key", token=SECRET))
        seven(self.folder / "locked.7z", "n.yaml", resource("cms_url", url="u"), password="pw1")
        with zipfile.ZipFile(self.folder / "plain.zip", "w") as archive:
            archive.writestr("z.json", json.dumps({"resource": {"type": "third", "data": {}}}))
        bundle = self.collect(["wrong", "pw1"])
        self.assertEqual(sorted(r.type for r in bundle.resources), ["agent_api_key", "cms_url", "third"])
        self.assertEqual(bundle.problems, [])

    @unittest.skipUnless(HAS_7Z, "7z is not installed")
    def test_a_missing_or_wrong_password_is_a_problem_not_an_error(self) -> None:
        seven(self.folder / "locked.7z", "n.yaml", resource("agent_api_key", token=SECRET), password="right")
        (self.folder / "ok.yaml").write_text(resource("cms_url", url="u"), encoding="utf-8")
        for passwords in ([], ["wrong"]):
            with self.subTest(passwords=passwords):
                bundle = self.collect(passwords)
                self.assertEqual([r.type for r in bundle.resources], ["cms_url"])
                self.assertEqual(len(bundle.problems), 1)
                self.assertIn("locked.7z: could not be opened", bundle.problems[0])
                self.assertNoSecret(bundle)

    def test_bad_files_are_printed_and_skipped(self) -> None:
        (self.folder / "plain.txt").write_text(SECRET, encoding="utf-8")
        (self.folder / "list.json").write_text("[1, 2]", encoding="utf-8")
        (self.folder / "broken.json").write_text('{"resource": ' + SECRET, encoding="utf-8")
        (self.folder / "broken.yaml").write_text("a: [" + SECRET, encoding="utf-8")
        (self.folder / "image.png").write_bytes(b"\x89PNG\xff\xfe\x00")
        (self.folder / "good.yaml").write_text(resource("agent_api_key", token=SECRET), encoding="utf-8")
        bundle = self.collect()
        self.assertEqual([r.source for r in bundle.resources], ["good.yaml"])
        self.assertEqual(len(bundle.problems), 5)
        self.assertNoSecret(bundle)

    def test_a_value_the_parser_cannot_read_is_a_problem_not_an_exception(self) -> None:
        (self.folder / "date.yaml").write_text("resource:\n  type: t\n  data:\n    validity: 2027-02-30\n", encoding="utf-8")
        (self.folder / "deep.json").write_text("[" * 20000, encoding="utf-8")
        bundle = self.collect()
        self.assertEqual(bundle.resources, [])
        self.assertEqual(len(bundle.problems), 2)

    def test_a_missing_folder_or_no_source_is_not_an_error(self) -> None:
        self.assertEqual(self.collect(directory=self.tmp / "nope").resources, [])
        self.assertIn("does not exist", self.collect(directory=self.tmp / "nope").problems[0])
        self.assertEqual(self.collect(directory=None).problems, [])

    def test_a_symlink_is_not_followed(self) -> None:
        (self.folder / "real.yaml").write_text(resource("agent_api_key", token=SECRET), encoding="utf-8")
        outside = self.tmp / "outside.yaml"
        outside.write_text(resource("cms_url", url="u"), encoding="utf-8")
        (self.folder / "link.yaml").symlink_to(outside)
        self.assertEqual([r.source for r in self.collect().resources], ["real.yaml"])

    def test_one_file_works_as_well_as_a_folder(self) -> None:
        (self.folder / "only.json").write_text(json.dumps({"resource": {"type": "cms_url", "data": {}}}), encoding="utf-8")
        bundle = self.collect(directory=self.folder / "only.json")
        self.assertEqual([(r.type, r.source) for r in bundle.resources], [("cms_url", "only.json")])

    def test_a_missing_7z_binary_is_a_problem(self) -> None:
        (self.folder / "x.7z").write_bytes(assets.SEVEN_ZIP_MAGIC + b"\x00" * 20)
        with mock.patch.object(shutil, "which", return_value=None):
            bundle = self.collect()
        self.assertIn("7z is not installed", bundle.problems[0])


class ResolveTests(AssetsCase):
    def resolve(self, bundle: assets.Bundle, **kw: object) -> assets.Outcome:
        args = {"agent": "claude", "entry": AGENT, "xp_host": None, "want_state": False, "state_dir": self.tmp / "state", **kw}
        return assets.resolve(bundle, **args)

    def bundle(self, *resources: assets.Resource) -> assets.Bundle:
        return assets.Bundle(resources=list(resources))

    def test_the_token_goes_to_the_agents_variable(self) -> None:
        outcome = self.resolve(self.bundle(assets.Resource("agent_api_key", {"token": f" {SECRET}\n", "agent": "claude"}, "a.yaml")))
        self.assertEqual(outcome.agent_env, {"CLAUDE_CODE_OAUTH_TOKEN": SECRET})
        self.assertEqual(outcome.drop_env, ["ANTHROPIC_API_KEY"])
        self.assertNotIn(SECRET, " ".join(outcome.notes + outcome.problems))

    def test_a_token_for_another_agent_is_left_alone(self) -> None:
        other = assets.Resource("agent_api_key", {"token": "x", "agent": "codex"}, "codex.yaml")
        mine = assets.Resource("agent_api_key", {"token": SECRET, "agent": "claude"}, "claude.yaml")
        self.assertEqual(self.resolve(self.bundle(other)).agent_env, {})
        self.assertEqual(self.resolve(self.bundle(other, mine)).agent_env, {"CLAUDE_CODE_OAUTH_TOKEN": SECRET})

    def test_several_tokens_use_the_first_and_say_so(self) -> None:
        first, second = (assets.Resource("agent_api_key", {"token": t, "agent": "claude"}, f"{t}.yaml") for t in ("one", "two"))
        outcome = self.resolve(self.bundle(first, second))
        self.assertEqual(outcome.agent_env, {"CLAUDE_CODE_OAUTH_TOKEN": "one"})
        self.assertTrue(any("first is used" in note for note in outcome.notes))

    def test_a_token_without_an_agent_is_a_problem_and_is_not_used(self) -> None:
        for data in ({"token": SECRET}, {"token": SECRET, "agent": ""}, {"token": SECRET, "agent": 7}):
            with self.subTest(data=data):
                outcome = self.resolve(self.bundle(assets.Resource("agent_api_key", data, "n.yaml")))
                self.assertEqual(outcome.agent_env, {})
                self.assertEqual(outcome.problems, ["n.yaml: agent_api_key needs data.agent, the agent CLI it is for"])

    def test_a_token_less_resource_and_an_unknown_variable_are_problems(self) -> None:
        self.assertIn("has no token", self.resolve(self.bundle(assets.Resource("agent_api_key", {"agent": "claude"}, "e.yaml"))).problems[0])
        outcome = self.resolve(self.bundle(assets.Resource("agent_api_key", {"token": "x", "agent": "claude"}, "e.yaml")), entry={})
        self.assertEqual(outcome.agent_env, {})
        self.assertIn("api_key_env", outcome.problems[0])

    def cms(self, server_url: str, password: str = PASSWORD, **extra: str) -> assets.Resource:
        return assets.Resource("cms_url", {"url": server_url, "login": "su", "password": password, **extra}, "cms.yaml")

    def serve(self, *paths: str) -> str:
        server = serve(*paths)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def test_a_cms_resource_logs_in_on_xp8_and_on_xp7(self) -> None:
        for path in (XP8, XP7):
            with self.subTest(path=path):
                outcome = self.resolve(self.bundle(self.cms(self.serve(path))), want_state=True)
                self.assertTrue(outcome.storage_state and outcome.storage_state.is_file())
                self.assertEqual(outcome.problems, [])

    def test_a_refused_login_is_a_problem_and_no_state(self) -> None:
        outcome = self.resolve(self.bundle(self.cms(self.serve(XP8), password="wrong-one")), want_state=True)
        self.assertIsNone(outcome.storage_state)
        self.assertIn("login to 127.0.0.1 failed", outcome.problems[0])
        self.assertNotIn("wrong-one", outcome.problems[0])

    def test_only_the_resource_for_the_xp_host_is_used(self) -> None:
        url = self.serve(XP8)
        other = assets.Resource("cms_url", {"url": "https://review.other.k8s.seeds.no", "login": "a", "password": "b"}, "other.yaml")
        outcome = self.resolve(self.bundle(other, self.cms(url)), want_state=True, xp_host=url)
        self.assertIsNotNone(outcome.storage_state)
        outcome = self.resolve(self.bundle(other), want_state=True, xp_host=url)
        self.assertIsNone(outcome.storage_state)

    def test_a_production_host_is_never_sent_a_password(self) -> None:
        resource = assets.Resource("cms_url", {"url": "https://www.example.com", "login": "a", "password": "b"}, "p.yaml")
        with mock.patch("extractkit_cli.xp_login.login") as login:
            outcome = self.resolve(self.bundle(resource), want_state=True)
        login.assert_not_called()
        self.assertIn("not a local or review host", outcome.problems[0])

    def test_no_cms_resource_is_a_note_and_an_unwritable_state_is_a_problem(self) -> None:
        self.assertEqual(self.resolve(self.bundle(), want_state=True).notes, ["no cms_url resource, so no XP login"])
        blocked = self.tmp / "file"
        blocked.write_text("x", encoding="utf-8")
        outcome = self.resolve(self.bundle(self.cms(self.serve(XP8))), want_state=True, state_dir=blocked)
        self.assertIsNone(outcome.storage_state)
        self.assertIn("could not be written", outcome.problems[0])

    def test_the_state_is_not_made_when_it_is_not_wanted(self) -> None:
        outcome = self.resolve(self.bundle(self.cms(self.serve(XP8))), want_state=False)
        self.assertIsNone(outcome.storage_state)
        self.assertTrue(any("not used" in note for note in outcome.notes))


class OnePasswordTests(AssetsCase):
    def fake_op(self, listing: str, failing: str | None = None) -> dict[str, str]:
        """An `op` that prints `listing` (JSON text, or the word null for an error) and writes a resource per `op read`; fails for the name `failing`."""
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir(exist_ok=True)
        op = bin_dir / "op"
        op.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            f"listing, failing = {listing!r}, {failing!r}\n"
            "a = sys.argv[1:]\n"
            "if a[:2] == ['item', 'get']:\n"
            "    if listing == 'null': sys.exit('[ERROR] item not found')\n"
            "    print(listing); sys.exit(0)\n"
            "if a[0] == 'read':\n"
            "    ref = a[-1]\n"
            "    if failing and ref.endswith('/' + failing): sys.exit('[ERROR] no such file')\n"
            "    open(a[a.index('--out-file') + 1], 'w').write('resource: {type: agent_api_key, data: {token: from-op}}')\n",
            encoding="utf-8",
        )
        op.chmod(op.stat().st_mode | stat.S_IXUSR)
        return {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}

    def run_collect(self, env: dict[str, str], **kw: object) -> assets.Bundle:
        with mock.patch.dict(os.environ, env, clear=True):
            return assets.collect(directory=None, op_vault="V", op_item="I", passwords=[], workdir=self.work, environ=env, **kw)

    def test_every_attachment_is_downloaded_whatever_its_name(self) -> None:
        listing = json.dumps({"files": [{"name": "any name.bin"}, {"name": "other"}]})
        bundle = self.run_collect(self.fake_op(listing))
        self.assertEqual(len(bundle.resources), 2)
        self.assertEqual(bundle.problems, [])

    def test_one_failed_download_does_not_stop_the_others(self) -> None:
        listing = json.dumps({"files": [{"name": "good"}, {"name": "bad"}]})
        bundle = self.run_collect(self.fake_op(listing, failing="bad"))
        self.assertEqual(len(bundle.resources), 1)
        self.assertIn("could not download bad", bundle.problems[0])

    def test_a_missing_item_an_empty_item_and_no_op_are_problems(self) -> None:
        self.assertIn("could not read item", self.run_collect(self.fake_op("null")).problems[0])
        self.assertIn("no attachments", self.run_collect(self.fake_op(json.dumps({"files": []}))).problems[0])
        with mock.patch.object(shutil, "which", return_value=None):
            self.assertIn("op CLI is not installed", self.collect(op_vault="V", op_item="I", directory=None).problems[0])

    def test_a_vault_without_an_item_downloads_nothing(self) -> None:
        self.assertIn("both the vault and the item", self.collect(op_vault="V", directory=None).problems[0])


class CommandTests(AssetsCase):
    def setUp(self) -> None:
        super().setUp()
        previous = os.getcwd()
        os.chdir(self.tmp)  # the kit refuses to run from its own checkout
        self.addCleanup(os.chdir, previous)

    def run_command(self, *args: str) -> tuple[int, dict]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = cli.main(["assets", "--json", *args])
        return code, json.loads(buffer.getvalue())

    def test_it_reports_what_the_files_hold_and_never_a_secret(self) -> None:
        (self.folder / "a.yaml").write_text(resource("agent_api_key", token=SECRET, agent="claude"), encoding="utf-8")
        (self.folder / "b.txt").write_text(SECRET, encoding="utf-8")
        code, doc = self.run_command("--assets-dir", str(self.folder))
        self.assertEqual(code, 0, doc)
        self.assertEqual(doc["resources"], [{"type": "agent_api_key", "source": "a.yaml"}])
        self.assertEqual(len(doc["problems"]), 1)
        self.assertNotIn(SECRET, json.dumps(doc))

    def test_an_unwritable_output_path_is_a_problem_not_a_crash(self) -> None:
        server = serve(XP8)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_address[1]}"
        (self.folder / "c.json").write_text(
            json.dumps({"resource": {"type": "cms_url", "data": {"url": url, "login": "su", "password": PASSWORD}}}), encoding="utf-8",
        )
        blocker = self.tmp / "file"
        blocker.write_text("x", encoding="utf-8")
        code, doc = self.run_command("--assets-dir", str(self.folder), "--storage-state-out", str(blocker / "state.json"))
        self.assertEqual(code, 0, doc)
        self.assertIn("could not be written", doc["problems"][0])
        self.assertIsNone(doc["storage_state"])

    def test_nothing_to_read_still_exits_0(self) -> None:
        code, doc = self.run_command("--assets-dir", str(self.tmp / "missing"))
        self.assertEqual(code, 0, doc)
        self.assertIn("does not exist", doc["problems"][0])

    def test_it_writes_a_private_storage_state_from_the_cms_resource(self) -> None:
        server = serve(XP7)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_address[1]}"
        (self.folder / "c.json").write_text(
            json.dumps({"resource": {"type": "cms_url", "data": {"url": url, "login": "su", "password": PASSWORD}}}), encoding="utf-8",
        )
        out = self.tmp / "deep" / "state.json"
        code, doc = self.run_command("--assets-dir", str(self.folder), "--storage-state-out", str(out))
        self.assertEqual(code, 0, doc)
        self.assertEqual(out.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(out.read_text())["cookies"][0]["name"], "JSESSIONID")
        self.assertNotIn(PASSWORD, json.dumps(doc))


if __name__ == "__main__":
    unittest.main()
