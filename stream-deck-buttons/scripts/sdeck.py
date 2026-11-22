#!/usr/bin/env python3
"""sdeck: add and copy Elgato Stream Deck buttons by editing the saved profile on macOS.

Elgato has no public "add a button" API, so this edits the profile JSON on disk.
The Stream Deck app keeps its config in memory and writes it back on quit, so every
write here refuses to run while the app is open (quit -> edit -> launch).

Standard library only. Python 3.8+.

  sdeck.py locate                          where the live profiles are
  sdeck.py list [--profile NAME]           every page/folder, slot by slot
  sdeck.py show PAGE SLOT                  one button's saved JSON (learn a format)
  sdeck.py quit | launch | status          control the app
  sdeck.py backup                          copy ProfilesV3 somewhere safe
  sdeck.py restore BACKUP_DIR              put a backup back (backs up current first)
  sdeck.py add PAGE SLOT --type open|website|shell ...
  sdeck.py copy FROM_PAGE FROM_SLOT TO_PAGE TO_SLOT [--title T] [--set key=value]
  sdeck.py remove PAGE SLOT

PAGE is a page/folder name from `list` (e.g. "Page 1", "Showtime") or a page UUID.
SLOT is "col,row" counted from 0 at the top-left key.
"""
import argparse
import copy as copymod
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid

APP_NAME = "Elgato Stream Deck"
DEFAULT_ROOT = os.path.expanduser(
    "~/Library/Application Support/com.elgato.StreamDeck/ProfilesV3")
DEFAULT_BACKUPS = os.path.expanduser("~/StreamDeckBackups")

BUILTIN = {
    "open": ("Open", "com.elgato.streamdeck.system.open"),
    "website": ("Website", "com.elgato.streamdeck.system.website"),
}
# Third-party "Shell Commands" plugin (Ceylon Systems). Must be installed on the deck's Mac.
SHELL_PLUGIN = {"Name": "Shell Commands", "UUID": "com.ceylon-systems.shell-commands",
                "Version": "0.1.0.0"}
SHELL_ACTION = "com.ceylon-systems.shell-commands.runner"
FOLDER_ACTIONS = ("com.elgato.streamdeck.profile.openchild",)
SLOT_RE = re.compile(r"^\d+,\d+$")


class SdeckError(Exception):
    pass


# ---------------------------------------------------------------- app control

def app_running():
    if os.environ.get("SDECK_ASSUME_APP") in ("running", "stopped"):  # tests
        return os.environ["SDECK_ASSUME_APP"] == "running"
    r = subprocess.run(["pgrep", "-f", APP_NAME + ".app/Contents/MacOS"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0


def app_quit(timeout=15):
    if not app_running():
        return True
    subprocess.run(["osascript", "-e", 'tell application "%s" to quit' % APP_NAME],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # -128 is benign
    end = time.time() + timeout
    while time.time() < end:
        if not app_running():
            time.sleep(1)  # let the on-quit write finish
            return True
        time.sleep(0.5)
    return False


def app_launch():
    subprocess.run(["open", "-a", APP_NAME], check=False)


def require_quit():
    if app_running():
        raise SdeckError(
            "The Stream Deck app is running. It would overwrite this edit when it quits.\n"
            "Run `sdeck.py quit` first, then `sdeck.py launch` after editing.")


# ---------------------------------------------------------------- profile model

def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json_atomic(path, data, like=None):
    indent = None
    if like is not None:
        with open(like, encoding="utf-8") as f:
            indent = 4 if "\n" in f.read(4096) else None
    tmp = path + ".sdeck-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)
    read_json(tmp)  # must parse before it replaces anything
    os.replace(tmp, path)


class Page:
    def __init__(self, profile, uuid_dir, path):
        self.profile = profile
        self.uuid = uuid_dir
        self.dir = path
        self.manifest_path = os.path.join(path, "manifest.json")
        self.data = read_json(self.manifest_path)
        self.name = None
        self.kind = "folder"

    def keypad(self, create=False):
        for c in self.data.get("Controllers", []):
            if c.get("Type") == "Keypad":
                c.setdefault("Actions", {})
                if c["Actions"] is None:
                    c["Actions"] = {}
                return c["Actions"]
        if not create:
            return {}
        c = {"Actions": {}, "Type": "Keypad"}
        self.data.setdefault("Controllers", []).append(c)
        return c["Actions"]

    def save(self):
        write_json_atomic(self.manifest_path, self.data, like=self.manifest_path)


class Profile:
    def __init__(self, path):
        self.dir = path
        self.manifest = read_json(os.path.join(path, "manifest.json"))
        self.name = self.manifest.get("Name") or os.path.basename(path)
        self.pages = []
        pdir = os.path.join(path, "Profiles")
        if os.path.isdir(pdir):
            for d in sorted(os.listdir(pdir)):
                mp = os.path.join(pdir, d, "manifest.json")
                if os.path.isfile(mp):
                    self.pages.append(Page(self, d, os.path.join(pdir, d)))
        self._name_pages()

    def _name_pages(self):
        listed = [p.lower() for p in (self.manifest.get("Pages") or {}).get("Pages", [])]
        by_uuid = {p.uuid.lower(): p for p in self.pages}
        for i, u in enumerate(listed, 1):
            if u in by_uuid:
                by_uuid[u].kind = "page"
                by_uuid[u].name = "Page %d" % i
        # A folder is named by the key that opens it: any parent action whose
        # Settings mention the folder's UUID (key name varies by app version).
        for parent in self.pages:
            for slot, a in parent.keypad().items():
                vals = json.dumps(a.get("Settings") or {}).lower()
                for p in self.pages:
                    if p.kind == "folder" and p.name is None and p.uuid.lower() in vals:
                        p.name = title_of(a) or ("Folder " + p.uuid[:8])
                        p.parent = (parent, slot)
        for p in self.pages:
            if p.name is None:
                p.name = (p.data.get("Name") or "").strip() or ("Unlinked " + p.uuid[:8])

    def find_page(self, ref):
        ref_l = ref.lower()
        hits = [p for p in self.pages if p.uuid.lower() == ref_l or p.name.lower() == ref_l]
        if not hits:
            names = ", ".join(sorted({p.name for p in self.pages}))
            raise SdeckError("No page or folder named %r in profile %r. Known: %s"
                             % (ref, self.name, names))
        if len(hits) > 1:
            raise SdeckError("%r matches %d pages; use the page UUID from `list --uuids`."
                             % (ref, len(hits)))
        return hits[0]


def title_of(action):
    for s in action.get("States") or []:
        t = (s or {}).get("Title")
        if t:
            return t.strip()
    n = action.get("Name") or ""
    return "" if n in ("Open", "Website", "Runner") else n


def load_profiles(root):
    if not os.path.isdir(root):
        raise SdeckError("Profile folder not found: %s\n(Is the Stream Deck app installed? "
                         "Older installs use ProfilesV2; pass --root.)" % root)
    out = []
    for d in sorted(os.listdir(root)):
        p = os.path.join(root, d)
        if d.endswith(".sdProfile") and os.path.isfile(os.path.join(p, "manifest.json")):
            out.append(Profile(p))
    if not out:
        raise SdeckError("No .sdProfile folders in %s" % root)
    return out


def pick_profile(profiles, name):
    if name is None:
        if len(profiles) == 1:
            return profiles[0]
        raise SdeckError("Several profiles exist; pass --profile. Names: "
                         + ", ".join(p.name for p in profiles))
    for p in profiles:
        if p.name.lower() == name.lower() or os.path.basename(p.dir).lower().startswith(name.lower()):
            return p
    raise SdeckError("No profile named %r" % name)


def check_slot(slot):
    if not SLOT_RE.match(slot):
        raise SdeckError("Slot must look like col,row (e.g. 2,1), got %r" % slot)
    return slot


def describe(action):
    u = action.get("UUID", "?")
    s = action.get("Settings") or {}
    detail = s.get("path") or s.get("commandToRun") or s.get("ProfileUUID") or ""
    return u, detail


# ---------------------------------------------------------------- backup/restore

def do_backup(root, backups):
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(backups, "ProfilesV3-" + stamp)
    n = 1
    while os.path.exists(dest):
        n += 1
        dest = os.path.join(backups, "ProfilesV3-%s-%d" % (stamp, n))
    os.makedirs(backups, exist_ok=True)
    shutil.copytree(root, dest)
    return dest


def do_restore(root, src, backups):
    if not os.path.isdir(src) or not any(n.endswith(".sdProfile") for n in os.listdir(src)):
        raise SdeckError("%s does not look like a ProfilesV3 backup" % src)
    safety = do_backup(root, backups)
    staging = root + ".sdeck-restore"
    if os.path.exists(staging):
        shutil.rmtree(staging)
    shutil.copytree(src, staging)
    old = root + ".sdeck-old"
    if os.path.exists(old):
        shutil.rmtree(old)
    os.rename(root, old)
    os.rename(staging, root)
    shutil.rmtree(old)
    return safety


# ---------------------------------------------------------------- building actions

def base_action(plugin_name, plugin_uuid, action_uuid, name, settings, title, plugin_version="1.0"):
    state = {}
    if title is not None:
        state["Title"] = title
    return {
        "ActionID": str(uuid.uuid4()),
        "LinkedTitle": True,
        "Name": name,
        "Plugin": {"Name": plugin_name, "UUID": plugin_uuid, "Version": plugin_version},
        "Resources": None,
        "Settings": settings,
        "State": 0,
        "States": [state],
        "UUID": action_uuid,
    }


def build_action(args):
    if args.type == "open":
        if not args.path:
            raise SdeckError("--type open needs --path (an app, file, folder or script)")
        target = os.path.abspath(os.path.expanduser(args.path))
        if not os.path.exists(target) and not args.allow_missing:
            raise SdeckError("%s does not exist (use --allow-missing to wire it anyway)" % target)
        name, uid = BUILTIN["open"]
        # Quoted so paths with spaces survive, matching what the app saves.
        return base_action(name, uid, uid, name, {"path": '"%s"' % target}, args.title)
    if args.type == "website":
        if not args.url or not re.match(r"^[a-z][a-z0-9+.-]*://", args.url, re.I):
            raise SdeckError("--type website needs --url with a scheme, e.g. https://...")
        name, uid = BUILTIN["website"]
        return base_action(name, uid, uid, name,
                           {"browser": "", "openInBrowser": True, "path": args.url}, args.title)
    if args.type == "shell":
        if not args.command:
            raise SdeckError("--type shell needs --command")
        a = base_action(SHELL_PLUGIN["Name"], SHELL_PLUGIN["UUID"], SHELL_ACTION, "Runner",
                        {"commandToRun": args.command}, args.title, SHELL_PLUGIN["Version"])
        return a
    raise SdeckError("Unknown --type %r. For anything else, make one button in the app "
                     "and use `copy`." % args.type)


def attach_image(page, action, image):
    if not image:
        return
    src = os.path.expanduser(image)
    if not os.path.isfile(src) or not src.lower().endswith(".png"):
        raise SdeckError("--image must be an existing .png (144x144 works best)")
    images = os.path.join(page.dir, "Images")
    os.makedirs(images, exist_ok=True)
    fname = "sdeck-%s.png" % uuid.uuid4().hex[:12]
    shutil.copyfile(src, os.path.join(images, fname))
    action["States"][0]["Image"] = "Images/" + fname


def parse_sets(pairs):
    out = {}
    for p in pairs or []:
        if "=" not in p:
            raise SdeckError("--set wants key=value, got %r" % p)
        k, v = p.split("=", 1)
        try:
            out[k] = json.loads(v)
        except ValueError:
            out[k] = v
    return out


def place(page, slot, action, replace):
    actions = page.keypad(create=True)
    if slot in actions and not replace:
        u, d = describe(actions[slot])
        raise SdeckError("Slot %s on %r is taken (%s %s). Pick an empty slot or pass --replace."
                         % (slot, page.name, u, d))
    actions[slot] = action
    page.save()


# ---------------------------------------------------------------- commands

def cmd_locate(a):
    for p in load_profiles(a.root):
        dev = (p.manifest.get("Device") or {}).get("Model", "?")
        print("%s  (device model %s)\n  %s" % (p.name, dev, p.dir))


def cmd_list(a):
    if app_running():
        print("note: the app is running, so this is the last SAVED state; "
              "quit it first for the live layout.\n", file=sys.stderr)
    profiles = load_profiles(a.root)
    if a.profile:
        profiles = [pick_profile(profiles, a.profile)]
    for p in profiles:
        print("== %s" % p.name)
        for pg in sorted(p.pages, key=lambda x: (x.kind != "page", x.name)):
            acts = pg.keypad()
            head = "%s [%s]" % (pg.name, pg.kind)
            if a.uuids:
                head += " " + pg.uuid
            print("  %s  %d keys" % (head, len(acts)))
            for slot in sorted(acts, key=lambda s: tuple(int(x) for x in s.split(",")[::-1])):
                u, d = describe(acts[slot])
                t = title_of(acts[slot])
                print("    %-5s %-28s %-45s %s" % (slot, (t or "-")[:28], u[:45], d))


def cmd_show(a):
    prof = pick_profile(load_profiles(a.root), a.profile)
    page = prof.find_page(a.page)
    acts = page.keypad()
    slot = check_slot(a.slot)
    if slot not in acts:
        raise SdeckError("Slot %s on %r is empty" % (slot, page.name))
    print(json.dumps(acts[slot], indent=2))


def edit_prelude(a):
    require_quit()
    if not a.no_backup:
        print("backup: %s" % do_backup(a.root, a.backups))


def cmd_add(a):
    prof = pick_profile(load_profiles(a.root), a.profile)
    page = prof.find_page(a.page)
    slot = check_slot(a.slot)
    action = build_action(a)
    if a.dry_run:
        print(json.dumps({"page": page.name, "slot": slot, "action": action}, indent=2))
        return
    edit_prelude(a)
    attach_image(page, action, a.image)
    place(page, slot, action, a.replace)
    print("added %s at %s on %r. Run `sdeck.py launch`, then press it to test." %
          (action["UUID"], slot, page.name))


def cmd_copy(a):
    prof = pick_profile(load_profiles(a.root), a.profile)
    src_page = prof.find_page(a.from_page)
    dst_page = prof.find_page(a.to_page)
    src_slot, dst_slot = check_slot(a.from_slot), check_slot(a.to_slot)
    src = src_page.keypad().get(src_slot)
    if src is None:
        raise SdeckError("Nothing at %s on %r to copy" % (src_slot, src_page.name))
    if src.get("UUID") in FOLDER_ACTIONS:
        raise SdeckError("Copying a folder key would make two keys open the same folder; "
                         "make new folders in the app.")
    action = copymod.deepcopy(src)
    action["ActionID"] = str(uuid.uuid4())
    action.setdefault("Settings", {}).update(parse_sets(a.set))
    if a.title is not None:
        action.setdefault("States", [{}])
        for s in action["States"]:
            s["Title"] = a.title
    if a.dry_run:
        print(json.dumps({"page": dst_page.name, "slot": dst_slot, "action": action}, indent=2))
        return
    edit_prelude(a)
    # Images are page-relative: carry the file across when the page changes.
    for s in action.get("States") or []:
        img = (s or {}).get("Image")
        if img and dst_page is not src_page:
            srcf = os.path.join(src_page.dir, img)
            if os.path.isfile(srcf):
                os.makedirs(os.path.join(dst_page.dir, "Images"), exist_ok=True)
                newname = "Images/sdeck-%s%s" % (uuid.uuid4().hex[:12], os.path.splitext(img)[1])
                shutil.copyfile(srcf, os.path.join(dst_page.dir, newname))
                s["Image"] = newname
            else:
                s.pop("Image", None)
    attach_image(dst_page, action, a.image)
    place(dst_page, dst_slot, action, a.replace)
    print("copied %s -> %s on %r" % (src_slot, dst_slot, dst_page.name))


def cmd_remove(a):
    prof = pick_profile(load_profiles(a.root), a.profile)
    page = prof.find_page(a.page)
    slot = check_slot(a.slot)
    acts = page.keypad()
    if slot not in acts:
        raise SdeckError("Slot %s on %r is already empty" % (slot, page.name))
    if acts[slot].get("UUID") in FOLDER_ACTIONS:
        raise SdeckError("That key opens a folder; remove folders in the app.")
    edit_prelude(a)
    del acts[slot]
    page.save()
    print("removed %s from %r" % (slot, page.name))


def cmd_backup(a):
    print(do_backup(a.root, a.backups))


def cmd_restore(a):
    require_quit()
    print("current state saved to %s first" % do_restore(a.root, a.backup_dir, a.backups))
    print("restored %s. Run `sdeck.py launch`." % a.backup_dir)


def cmd_quit(a):
    print("quit" if app_quit() else "still running after 15s; quit it by hand")


def cmd_launch(a):
    app_launch()
    print("launched")


def cmd_status(a):
    print("running" if app_running() else "not running")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sdeck.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=os.environ.get("STREAMDECK_PROFILES_DIR", DEFAULT_ROOT))
    ap.add_argument("--backups", default=os.environ.get("SDECK_BACKUP_DIR", DEFAULT_BACKUPS))
    ap.add_argument("--profile")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("locate").set_defaults(fn=cmd_locate)
    p = sub.add_parser("list"); p.add_argument("--uuids", action="store_true"); p.set_defaults(fn=cmd_list)
    p = sub.add_parser("show"); p.add_argument("page"); p.add_argument("slot"); p.set_defaults(fn=cmd_show)
    for n, fn in (("quit", cmd_quit), ("launch", cmd_launch), ("status", cmd_status), ("backup", cmd_backup)):
        sub.add_parser(n).set_defaults(fn=fn)
    p = sub.add_parser("restore"); p.add_argument("backup_dir"); p.set_defaults(fn=cmd_restore)

    def edit_flags(p):
        p.add_argument("--replace", action="store_true", help="overwrite an occupied slot")
        p.add_argument("--no-backup", action="store_true")
        p.add_argument("--dry-run", action="store_true", help="print the button, change nothing")
        p.add_argument("--title")
        p.add_argument("--image", help="a .png for the key face")

    p = sub.add_parser("add"); p.add_argument("page"); p.add_argument("slot")
    p.add_argument("--type", required=True, choices=["open", "website", "shell"])
    p.add_argument("--path"); p.add_argument("--url"); p.add_argument("--command")
    p.add_argument("--allow-missing", action="store_true")
    edit_flags(p); p.set_defaults(fn=cmd_add)

    p = sub.add_parser("copy")
    for n in ("from_page", "from_slot", "to_page", "to_slot"):
        p.add_argument(n)
    p.add_argument("--set", action="append", help="override a Settings key: key=value (JSON ok)")
    edit_flags(p); p.set_defaults(fn=cmd_copy)

    p = sub.add_parser("remove"); p.add_argument("page"); p.add_argument("slot")
    p.add_argument("--no-backup", action="store_true"); p.set_defaults(fn=cmd_remove)

    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except SdeckError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
