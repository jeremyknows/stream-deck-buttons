"""Tests for sdeck.py against a fake ProfilesV3 tree shaped like a real saved one."""
import contextlib
import io
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "stream-deck-buttons", "scripts"))
import sdeck  # noqa: E402

ROOT_PAGE = "AAAA1111-0000-4000-8000-000000000001"
FOLDER = "BBBB2222-0000-4000-8000-000000000002"


def action(uuid_, name, settings, title=None, image=None):
    st = {}
    if title is not None:
        st["Title"] = title
    if image:
        st["Image"] = image
    return {"ActionID": "x", "LinkedTitle": True, "Name": name,
            "Plugin": {"Name": name, "UUID": uuid_, "Version": "1.0"}, "Resources": None,
            "Settings": settings, "State": 0, "States": [st], "UUID": uuid_}


def make_tree(base):
    root = os.path.join(base, "ProfilesV3")
    prof = os.path.join(root, "6B77C52F-0000-4000-8000-00000000000A.sdProfile")
    os.makedirs(os.path.join(prof, "Profiles", ROOT_PAGE, "Images"))
    os.makedirs(os.path.join(prof, "Profiles", FOLDER, "Images"))
    with open(os.path.join(prof, "manifest.json"), "w") as f:
        json.dump({"Device": {"Model": "20GBA9901", "UUID": "dev"}, "Name": "Default Profile",
                   "Pages": {"Current": ROOT_PAGE.lower(), "Default": ROOT_PAGE.lower(),
                             "Pages": [ROOT_PAGE.lower()]}, "Version": "3.0"}, f)
    root_page = {"Controllers": [{"Type": "Keypad", "Actions": {
        "0,0": action("com.elgato.streamdeck.profile.openchild", "Create Folder",
                      {"ProfileUUID": FOLDER.lower()}, title="Showtime"),
        "3,1": action("com.ceylon-systems.shell-commands.runner", "Runner",
                      {"commandToRun": "echo hi"}, title="Fleet Status"),
    }}], "Icon": "", "Name": ""}
    with open(os.path.join(prof, "Profiles", ROOT_PAGE, "manifest.json"), "w") as f:
        json.dump(root_page, f, indent=4)
    with open(os.path.join(prof, "Profiles", FOLDER, "Images", "lava.png"), "wb") as f:
        f.write(b"\x89PNG fake")
    folder_page = {"Controllers": [{"Type": "Keypad", "Actions": {
        "0,0": action("com.elgato.streamdeck.profile.backtoparent", "Parent Folder", {}),
        "0,1": action("com.elgato.streamdeck.system.open", "Open",
                      {"path": '"/Applications/Lava Ticker.app"'}, title="", image="Images/lava.png"),
        "1,1": action("com.elgato.streamdeck.system.website", "Website",
                      {"browser": "", "openInBrowser": True, "path": "https://example.com"},
                      title="Shows"),
    }}], "Icon": "", "Name": ""}
    with open(os.path.join(prof, "Profiles", FOLDER, "manifest.json"), "w") as f:
        json.dump(folder_page, f, indent=4)
    return root, prof


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root, self.prof = make_tree(self.tmp)
        self.backups = os.path.join(self.tmp, "backups")
        os.environ["SDECK_ASSUME_APP"] = "stopped"
        os.environ["SDECK_SKIP_PREFS"] = "1"  # never touch the real app's prefs

    def tearDown(self):
        shutil.rmtree(self.tmp)
        os.environ.pop("SDECK_ASSUME_APP", None)
        os.environ.pop("SDECK_SKIP_PREFS", None)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = sdeck.main(["--root", self.root, "--backups", self.backups] + list(args))
        return rc, out.getvalue(), err.getvalue()

    def page(self, uuid_):
        with open(os.path.join(self.prof, "Profiles", uuid_, "manifest.json")) as f:
            return json.load(f)["Controllers"][0]["Actions"]


class SdeckTest(Base):
    def test_list_names_root_page_and_folder_by_its_key_title(self):
        rc, out, _ = self.run_cli("list")
        self.assertEqual(rc, 0)
        self.assertIn("Page 1 [page]", out)
        self.assertIn("Showtime [folder]", out)
        self.assertIn("Fleet Status", out)

    def test_add_website_to_empty_slot_with_backup(self):
        rc, out, err = self.run_cli("add", "Showtime", "2,0", "--type", "website",
                                    "--url", "https://example.org", "--title", "Docs")
        self.assertEqual(rc, 0, err)
        a = self.page(FOLDER)["2,0"]
        self.assertEqual(a["UUID"], "com.elgato.streamdeck.system.website")
        self.assertEqual(a["Settings"]["path"], "https://example.org")
        self.assertEqual(a["States"][0]["Title"], "Docs")
        self.assertNotEqual(a["ActionID"], "x")
        self.assertEqual(len(os.listdir(self.backups)), 1)

    def test_add_refuses_occupied_slot_without_replace(self):
        rc, _, err = self.run_cli("add", "Showtime", "1,1", "--type", "website",
                                  "--url", "https://example.org")
        self.assertEqual(rc, 2)
        self.assertIn("taken", err)
        self.assertEqual(self.page(FOLDER)["1,1"]["Settings"]["path"], "https://example.com")

    def test_writes_refused_while_app_running(self):
        os.environ["SDECK_ASSUME_APP"] = "running"
        rc, _, err = self.run_cli("add", "Page 1", "1,0", "--type", "shell", "--command", "ls")
        self.assertEqual(rc, 2)
        self.assertIn("overwrite", err)
        self.assertNotIn("1,0", self.page(ROOT_PAGE))
        self.assertFalse(os.path.exists(self.backups))

    def test_add_open_quotes_path_and_checks_it_exists(self):
        rc, _, err = self.run_cli("add", "Page 1", "1,0", "--type", "open",
                                  "--path", "/nope/Missing.app")
        self.assertEqual(rc, 2)
        self.assertIn("does not exist", err)
        target = os.path.join(self.tmp, "My Launcher.app")
        os.makedirs(target)
        rc, _, err = self.run_cli("add", "Page 1", "1,0", "--type", "open", "--path", target)
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.page(ROOT_PAGE)["1,0"]["Settings"]["path"], '"%s"' % target)

    def test_add_shell_matches_saved_runner_shape(self):
        rc, _, err = self.run_cli("add", "Page 1", "4,2", "--type", "shell",
                                  "--command", "uptime", "--title", "Up")
        self.assertEqual(rc, 0, err)
        a = self.page(ROOT_PAGE)["4,2"]
        self.assertEqual(a["UUID"], "com.ceylon-systems.shell-commands.runner")
        self.assertEqual(a["Plugin"]["UUID"], "com.ceylon-systems.shell-commands")
        self.assertEqual(a["Settings"], {"commandToRun": "uptime"})

    def test_copy_across_pages_carries_image_and_overrides(self):
        rc, _, err = self.run_cli("copy", "Showtime", "0,1", "Page 1", "2,2",
                                  "--title", "Lava", "--set", 'path="/Applications/Other.app"')
        self.assertEqual(rc, 0, err)
        a = self.page(ROOT_PAGE)["2,2"]
        self.assertEqual(a["Settings"]["path"], "/Applications/Other.app")
        self.assertEqual(a["States"][0]["Title"], "Lava")
        img = a["States"][0]["Image"]
        self.assertTrue(os.path.isfile(os.path.join(self.prof, "Profiles", ROOT_PAGE, img)))
        self.assertNotEqual(a["ActionID"], self.page(FOLDER)["0,1"]["ActionID"])

    def test_copy_refuses_folder_key(self):
        rc, _, err = self.run_cli("copy", "Page 1", "0,0", "Page 1", "1,0")
        self.assertEqual(rc, 2)
        self.assertIn("folder", err)

    def test_dry_run_changes_nothing(self):
        before = self.page(ROOT_PAGE)
        rc, out, _ = self.run_cli("add", "Page 1", "1,0", "--type", "website",
                                  "--url", "https://x.test", "--dry-run")
        self.assertEqual(rc, 0)
        self.assertIn("https://x.test", out)
        self.assertEqual(self.page(ROOT_PAGE), before)
        self.assertFalse(os.path.exists(self.backups))

    def test_remove_and_restore_round_trip(self):
        rc, _, err = self.run_cli("backup")
        self.assertEqual(rc, 0, err)
        snap = os.path.join(self.backups, os.listdir(self.backups)[0])
        rc, out, err = self.run_cli("remove", "Showtime", "1,1")
        self.assertEqual(rc, 0, err)
        self.assertIn("Cancel", out)
        self.assertNotIn("1,1", self.page(FOLDER))
        rc, _, err = self.run_cli("restore", snap)
        self.assertEqual(rc, 0, err)
        self.assertIn("1,1", self.page(FOLDER))

    def test_bad_slot_and_unknown_page(self):
        self.assertEqual(self.run_cli("add", "Page 1", "a,b", "--type", "website",
                                      "--url", "https://x.test")[0], 2)
        rc, _, err = self.run_cli("add", "Nope", "1,0", "--type", "website", "--url", "https://x.test")
        self.assertEqual(rc, 2)
        self.assertIn("Known:", err)

    def test_replace_refuses_folder_opener(self):
        rc, _, err = self.run_cli("add", "Page 1", "0,0", "--type", "website",
                                  "--url", "https://x.test", "--replace")
        self.assertEqual(rc, 2)
        self.assertIn("opens a folder", err)
        self.assertEqual(self.page(ROOT_PAGE)["0,0"]["Settings"]["ProfileUUID"], FOLDER.lower())

    def test_folder_named_by_opener_not_by_other_mentions(self):
        # A shell key that happens to mention the folder UUID must not steal its name.
        p = os.path.join(self.prof, "Profiles", ROOT_PAGE, "manifest.json")
        with open(p) as f:
            data = json.load(f)
        data["Controllers"][0]["Actions"]["0,0"]["States"][0]["Title"] = "Showtime"
        data["Controllers"][0]["Actions"]["1,0"] = action(
            "com.ceylon-systems.shell-commands.runner", "Runner",
            {"commandToRun": "echo %s" % FOLDER}, title="Decoy")
        with open(p, "w") as f:
            json.dump(data, f)
        rc, out, _ = self.run_cli("list")
        self.assertIn("Showtime [folder]", out)
        self.assertNotIn("Decoy [folder]", out)

    def test_restore_rejects_empty_backup(self):
        bad = os.path.join(self.tmp, "bad")
        os.makedirs(os.path.join(bad, "X.sdProfile"))
        rc, _, err = self.run_cli("restore", bad)
        self.assertEqual(rc, 2)
        self.assertIn("usable", err)
        self.assertIn("1,1", self.page(FOLDER))

    def test_restore_rejects_backup_missing_a_listed_page(self):
        bad = os.path.join(self.tmp, "partial")
        shutil.copytree(self.root, bad)
        prof = os.path.join(bad, os.path.basename(self.prof))
        shutil.rmtree(os.path.join(prof, "Profiles", ROOT_PAGE))
        rc, _, err = self.run_cli("restore", bad)
        self.assertEqual(rc, 2)
        self.assertIn("incomplete", err)
        self.assertIn("3,1", self.page(ROOT_PAGE))

    def test_unknown_app_state_fails_closed(self):
        os.environ.pop("SDECK_ASSUME_APP")
        orig = sdeck.subprocess.run

        class R:
            returncode = 3
        sdeck.subprocess.run = lambda *a, **k: R()
        try:
            rc, _, err = self.run_cli("add", "Page 1", "1,0", "--type", "website",
                                      "--url", "https://x.test")
        finally:
            sdeck.subprocess.run = orig
        self.assertEqual(rc, 2)
        self.assertIn("Can't tell", err)
        self.assertNotIn("1,0", self.page(ROOT_PAGE))

    def test_remove_dry_run(self):
        rc, out, _ = self.run_cli("remove", "Showtime", "1,1", "--dry-run")
        self.assertEqual(rc, 0)
        self.assertIn("would_remove", out)
        self.assertIn("1,1", self.page(FOLDER))

    def make_old_backups(self, n):
        os.makedirs(self.backups, exist_ok=True)
        names = ["ProfilesV3-202601%02d-120000" % (i + 1) for i in range(n)]
        for name in names:
            shutil.copytree(self.root, os.path.join(self.backups, name))
        return names

    def test_backups_pruned_to_keep_newest(self):
        self.make_old_backups(12)
        os.makedirs(os.path.join(self.backups, "my-own-copy"))  # not ours: never touched
        rc, out, err = self.run_cli("backup")
        self.assertEqual(rc, 0, err)
        left = sorted(os.listdir(self.backups))
        ours = [n for n in left if n.startswith("ProfilesV3-")]
        self.assertEqual(len(ours), 10)
        self.assertIn(os.path.basename(out.strip()), ours)  # the new one survives
        self.assertNotIn("ProfilesV3-20260101-120000", ours)
        self.assertIn("my-own-copy", left)

    def test_keep_zero_keeps_all(self):
        self.make_old_backups(12)
        rc, _, err = self.run_cli("--keep-backups", "0", "backup")
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(os.listdir(self.backups)), 13)

    def test_restore_from_oldest_backup_is_not_pruned_away(self):
        # 10 backups at the keep limit; restore's own safety backup makes 11, and the
        # backup being restored from is the oldest, so plain pruning would delete it.
        names = self.make_old_backups(10)
        oldest = os.path.join(self.backups, names[0])
        rc, _, err = self.run_cli("remove", "Showtime", "1,1", "--no-backup")
        self.assertEqual(rc, 0, err)
        rc, _, err = self.run_cli("restore", oldest)
        self.assertEqual(rc, 0, err)
        self.assertIn("1,1", self.page(FOLDER))
        self.assertTrue(os.path.isdir(oldest))

    def test_restore_source_given_as_subfolder_survives_pruning(self):
        names = self.make_old_backups(10)
        src = os.path.join(self.backups, names[0]) + "/"
        rc, _, err = self.run_cli("restore", src)
        self.assertEqual(rc, 0, err)
        self.assertTrue(os.path.isdir(src))

    def test_live_root_inside_backups_is_never_pruned(self):
        store = os.path.join(self.tmp, "store")
        live = os.path.join(store, "ProfilesV3-20200101-000000")
        shutil.copytree(self.root, live)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = sdeck.main(["--root", live, "--backups", store, "--keep-backups", "1", "backup"])
        self.assertEqual(rc, 0, err.getvalue())
        self.assertTrue(os.path.isdir(live))

    def test_same_second_backups_stay_ordered(self):
        for _ in range(5):
            self.run_cli("--keep-backups", "2", "backup")
        left = sorted(os.listdir(self.backups))
        self.assertEqual(len(left), 2)

    def test_name_with_trailing_newline_is_not_ours(self):
        os.makedirs(self.backups)
        odd = os.path.join(self.backups, "ProfilesV3-20200101-000000\n")
        os.makedirs(odd)
        self.run_cli("--keep-backups", "1", "backup")
        self.assertTrue(os.path.isdir(odd))

    def test_failed_copy_leaves_no_backup(self):
        orig = sdeck.shutil.copytree
        def boom(src, dst, *a, **k):
            os.makedirs(dst)
            raise OSError("disk full")
        sdeck.shutil.copytree = boom
        try:
            rc, _, err = self.run_cli("backup")
        finally:
            sdeck.shutil.copytree = orig
        self.assertNotEqual(rc, 0)
        self.assertEqual(os.listdir(self.backups), [])

    def test_symlinked_backup_name_is_ignored(self):
        self.make_old_backups(1)
        os.symlink(self.root, os.path.join(self.backups, "ProfilesV3-19990101-000000"))
        rc, _, err = self.run_cli("--keep-backups", "1", "backup")
        self.assertEqual(rc, 0, err)
        self.assertTrue(os.path.islink(os.path.join(self.backups, "ProfilesV3-19990101-000000")))

    def test_backups_lists_sizes(self):
        self.make_old_backups(2)
        rc, out, _ = self.run_cli("backups")
        self.assertEqual(rc, 0)
        self.assertIn("2 backup(s)", out)
        self.assertIn("MB", out)

    def test_saved_indentation_is_kept(self):
        self.run_cli("add", "Page 1", "1,0", "--type", "website", "--url", "https://x.test")
        with open(os.path.join(self.prof, "Profiles", ROOT_PAGE, "manifest.json")) as f:
            self.assertIn("\n    ", f.read())


class FakeDefaults:
    """Stands in for subprocess.run, emulating `defaults export/write` on an in-memory domain."""

    def __init__(self, report, fail=False):
        self.domain = {"other_pref": "keep", sdeck.SESSION_KEY: dict(report)}
        self.fail = fail
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if self.fail:
            raise OSError("defaults not found")
        rc, out = 0, b""
        if cmd[:2] == ["defaults", "export"] and cmd[2] == sdeck.PREFS_DOMAIN:
            out = plistlib.dumps(self.domain)
        elif cmd[:2] == ["defaults", "write"] and cmd[2:5] == [sdeck.PREFS_DOMAIN, sdeck.SESSION_KEY,
                                                               "-dict-add"]:
            k, typ, v = cmd[5:8]
            assert typ == "-int"
            self.domain[sdeck.SESSION_KEY][k] = int(v)
        else:
            rc = 1
        return subprocess.CompletedProcess(cmd, rc, stdout=out)

    def writes(self):
        return [c for c in self.calls if c[:2] == ["defaults", "write"]]


class SessionCountTest(Base):
    # Fixture: Page 1 has 2 keys (folder opener + shell); the folder has 3 (incl. back key).
    def setUp(self):
        super().setUp()
        os.environ.pop("SDECK_SKIP_PREFS")

    def run_with(self, fake, *args):
        with mock.patch.object(sdeck.sys, "platform", "darwin"), \
                mock.patch.object(sdeck.subprocess, "run", fake):
            return self.run_cli(*args)

    def test_count_includes_pages_but_not_folders(self):
        self.assertEqual(sdeck.session_action_count(self.root), 2)
        # A second listed page and an unlisted Default page both count; folders still don't.
        p2, p3 = "CCCC3333-0000-4000-8000-000000000003", "DDDD4444-0000-4000-8000-000000000004"
        for u, n in ((p2, 3), (p3, 1)):
            os.makedirs(os.path.join(self.prof, "Profiles", u))
            acts = {"%d,0" % i: action("com.elgato.streamdeck.page.next", "Next Page", {})
                    for i in range(n)}
            with open(os.path.join(self.prof, "Profiles", u, "manifest.json"), "w") as f:
                json.dump({"Controllers": [{"Type": "Keypad", "Actions": acts},
                                           {"Type": "Encoder", "Actions": None}]}, f)
        mp = os.path.join(self.prof, "manifest.json")
        with open(mp) as f:
            m = json.load(f)
        m["Pages"]["Pages"].append(p2.lower())
        m["Pages"]["Default"] = p3.lower()
        with open(mp, "w") as f:
            json.dump(m, f)
        self.assertEqual(sdeck.session_action_count(self.root), 2 + 3 + 1)

    def test_remove_lowers_saved_count_and_keeps_other_keys(self):
        fake = FakeDefaults({"action_count": 2, "session_count": 41})
        rc, out, err = self.run_with(fake, "remove", "Page 1", "3,1")
        self.assertEqual(rc, 0, err)
        self.assertEqual(fake.domain[sdeck.SESSION_KEY], {"action_count": 1, "session_count": 41})
        self.assertEqual(fake.domain["other_pref"], "keep")
        self.assertEqual(len(fake.writes()), 1)
        self.assertIn("2 -> 1", out)
        self.assertNotIn("Cancel", out)

    def test_no_write_when_saved_count_not_higher(self):
        # Removing a folder key doesn't change the counted total, so stored 2 <= computed 2.
        for stored in (2, 1):
            fake = FakeDefaults({"action_count": stored, "session_count": 5})
            rc, out, err = self.run_with(fake, "remove", "Showtime", "1,1" if stored == 2 else "0,1")
            self.assertEqual(rc, 0, err)
            self.assertEqual(fake.writes(), [])
            self.assertEqual(fake.domain[sdeck.SESSION_KEY]["action_count"], stored)
            self.assertNotIn("Cancel", out)

    def test_prefs_failure_is_not_fatal(self):
        fake = FakeDefaults({"action_count": 9, "session_count": 1}, fail=True)
        rc, out, err = self.run_with(fake, "remove", "Page 1", "3,1")
        self.assertEqual(rc, 0, err)
        self.assertNotIn("3,1", self.page(ROOT_PAGE))
        self.assertIn("couldn't check", out)
        self.assertIn("Cancel", out)

    def test_missing_report_falls_back_to_note(self):
        fake = FakeDefaults({})
        del fake.domain[sdeck.SESSION_KEY]
        rc, out, _ = self.run_with(fake, "remove", "Page 1", "3,1")
        self.assertEqual(rc, 0)
        self.assertEqual(fake.writes(), [])
        self.assertIn("Cancel", out)

    def test_skipped_off_macos_and_with_env(self):
        fake = FakeDefaults({"action_count": 9, "session_count": 1})
        with mock.patch.object(sdeck.sys, "platform", "linux"), \
                mock.patch.object(sdeck.subprocess, "run", fake):
            self.assertFalse(sdeck.sync_session_count(self.root))
        os.environ["SDECK_SKIP_PREFS"] = "1"
        with mock.patch.object(sdeck.sys, "platform", "darwin"), \
                mock.patch.object(sdeck.subprocess, "run", fake):
            self.assertFalse(sdeck.sync_session_count(self.root))
        self.assertEqual(fake.calls, [])

    def test_restore_lowers_saved_count(self):
        os.environ["SDECK_SKIP_PREFS"] = "1"
        self.run_cli("remove", "Page 1", "3,1")
        self.run_cli("backup")
        snap = os.path.join(self.backups, sorted(os.listdir(self.backups))[-1])
        os.environ.pop("SDECK_SKIP_PREFS")
        fake = FakeDefaults({"action_count": 2, "session_count": 3})
        rc, out, err = self.run_with(fake, "restore", snap)
        self.assertEqual(rc, 0, err)
        self.assertEqual(fake.domain[sdeck.SESSION_KEY], {"action_count": 1, "session_count": 3})


if __name__ == "__main__":
    unittest.main()
