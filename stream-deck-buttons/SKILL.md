---
name: stream-deck-buttons
description: Add, copy, move or remove Elgato Stream Deck buttons on macOS by editing the saved profile, with a backup first and a check afterwards. Use when someone asks an agent to set up, program or rearrange their Stream Deck keys (open an app or file, open a website, run a shell command, OBS controls). Not for Windows, for building Stream Deck plugins, or for changes that are quicker to drag in the app.
license: MIT
compatibility: macOS with the Elgato Stream Deck app 6.x or later (profiles in ProfilesV3). Python 3.8+. The shell-button type needs the free "Shell Commands" plugin.
metadata:
  version: "1.0.0"
---

# Stream Deck buttons

Elgato has no public "add a button" API. The app stores each page as a JSON file, so an agent can
edit those files directly. `scripts/sdeck.py` does that safely. It uses only the standard library.

## The one rule: the app must be closed while you edit

The Stream Deck app keeps the layout in memory and writes it back to disk **when it quits**. If it
is running while you edit, it silently overwrites your change later. So every edit goes:

```
python3 scripts/sdeck.py quit      # app writes its current state to disk and exits
python3 scripts/sdeck.py ...edit... # refuses to run if the app is still open
python3 scripts/sdeck.py launch    # app reads the new layout on start
```

Tell the person before you quit the app. Their deck goes dark for a few seconds.

## Workflow

1. **Look first.** Run `sdeck.py quit`, then `sdeck.py list`. Pages are named `Page 1`, `Page 2`...;
   folders take the title of the key that opens them (e.g. `Showtime`). Slots are `col,row`, with
   `0,0` at the top-left key. A standard deck is 5×3, a Mini is 3×2, an XL is 8×4, a Neo or + is 4×2.
2. **Confirm the plan** with the person: page, slot, what the key does, and its title.
3. **Make the change.** Every edit backs up the whole profile folder to `~/StreamDeckBackups/` first,
   and only the newest 10 backups are kept (`--keep-backups N`, or `0` to keep all; `sdeck.py backups`
   lists them with sizes). Folders you put there yourself are never touched.
   ```
   sdeck.py add "Page 1" 2,0 --type website --url https://example.com --title Docs
   sdeck.py add "Page 1" 3,0 --type open --path "/Applications/OBS.app" --title OBS
   sdeck.py add "Page 1" 4,0 --type shell --command "say hello" --title Hello
   sdeck.py add Showtime 1,2 --type website --url https://... --image ~/icons/live.png
   sdeck.py copy Showtime 0,1 "Page 2" 0,0 --title "Lava" --set 'path="/abs/Other.app"'
   sdeck.py remove "Page 1" 4,0
   ```
   Add `--dry-run` to print the button without saving it. An occupied slot is refused unless you
   pass `--replace`.
4. **Relaunch and check.** Run `sdeck.py launch`, then ask the person to look at the deck and press
   the key. You can't press physical keys yourself, so test what the key runs directly (open the
   URL, run the command, open the app).
5. **Undo** if anything looks wrong: quit the app, run `sdeck.py restore ~/StreamDeckBackups/<folder>`,
   then launch. The current state is backed up before the restore.

## Any other kind of button: copy one the person made

Plugin action formats are undocumented, and plugin manifests are encrypted, so don't guess a
format. Ask the person to make **one** button of that type in the app. Then quit the app and run
`sdeck.py show <page> <slot>` to see how it was saved. Clone it with
`sdeck.py copy ... --set key=value` to change its settings. This works for hotkeys, multi-actions,
OBS actions, Spotify, and anything else.

## Gotchas

- **Use ProfilesV3.** `ProfilesV2` may still exist but is a stale leftover; editing it does nothing.
  Pass `--root` if the profiles live elsewhere.
- **Button images** are PNGs stored in the page's `Images/` folder (144×144 works best). `--image`
  copies the file in for you.
- **Open-action paths must be absolute.** If the target moves, the key breaks; re-add it with `--replace`.
- **Never copy a folder key.** Two keys would open the same folder. Make folders in the app.
- **"Error restoring the last session" after removing keys.** At quit the app saves a key count
  (`last_app_session_report.action_count` in the `com.elgato.StreamDeck` defaults: keys on
  top-level pages only, not folders). On the next launch it compares, and a lower count looks
  like data loss. Adding keys never triggers it. After `remove` and `restore`, the script lowers
  that saved count to match the new layout, so the warning shouldn't appear. It never raises the
  count, and it only lowers it when the app's saved count equals the layout just before the edit
  (otherwise something else changed the layout, and the app's warning is left on to catch it). If the script prints the fallback note ("saved key count wasn't updated"; this happens
  off macOS, on failure, or with `SDECK_SKIP_PREFS=1`), tell the person to click **Cancel**. That
  keeps the new layout, while "Restore" rolls back to the app's own backup. (Verified on app
  7.6.1, 2026-11-22, with one profile.)
- **Re-check after an app update.** Elgato can change the saved format. If an edit doesn't stick
  after a relaunch, re-learn the format from a freshly saved button.
- **OBS "Source Visibility" only toggles,** and it repaints its own icon over custom images. For
  "show this one, hide the others" buttons, see `references/obs-one-tap.md`.

## Shell buttons and remote machines

`--type shell` needs the "Shell Commands" plugin (Ceylon Systems) from the Elgato Marketplace. The
command runs as the logged-in user, with no Terminal window. To control another computer, have
the key run `ssh <host> '<command>'` with a key that is limited to one command
(`command="..."` in that host's `authorized_keys`). Keep secrets out of the button text, because
it is saved as plain JSON.
