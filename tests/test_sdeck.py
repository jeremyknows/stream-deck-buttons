"""Tests for sdeck.py against a fake ProfilesV3 tree shaped like a real saved one."""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

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


class SdeckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root, self.prof = make_tree(self.tmp)
        self.backups = os.path.join(self.tmp, "backups")
        os.environ["SDECK_ASSUME_APP"] = "stopped"

    def tearDown(self):
        shutil.rmtree(self.tmp)
        os.environ.pop("SDECK_ASSUME_APP", None)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = sdeck.main(["--root", self.root, "--backups", self.backups] + list(args))
        return rc, out.getvalue(), err.getvalue()

    def page(self, uuid_):
        with open(os.path.join(self.prof, "Profiles", uuid_, "manifest.json")) as f:
            return json.load(f)["Controllers"][0]["Actions"]

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
        rc, _, err = self.run_cli("remove", "Showtime", "1,1")
        self.assertEqual(rc, 0, err)
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

    def test_saved_indentation_is_kept(self):
        self.run_cli("add", "Page 1", "1,0", "--type", "website", "--url", "https://x.test")
        with open(os.path.join(self.prof, "Profiles", ROOT_PAGE, "manifest.json")) as f:
            self.assertIn("\n    ", f.read())


if __name__ == "__main__":
    unittest.main()
