# One-tap OBS buttons: show this one, hide the others

The OBS plugin's **Source Visibility** action only toggles. It can't do "show A and hide B, C and D",
and it repaints its own icon, so custom key images don't stick. The Scene action is fine as it is,
because switching to the active scene does nothing.

The fix is a tiny launcher app per key that calls a script over obs-websocket:

1. **Script.** Copy `../scripts/obs-show-only.py`. It needs `pip install websocket-client`, OBS
   running, and obs-websocket v5 enabled (OBS → Tools → WebSocket Server Settings). It reads the
   port and password from OBS's own config, so no password lives in the key. List your scene-item
   ids once:
   ```
   python3 obs-show-only.py --scene "My Scene" --list
   python3 obs-show-only.py --scene "My Scene" --group 31,32,33 --show 32   # show 32, hide 31 and 33
   python3 obs-show-only.py --scene "My Scene" --group 31,32,33 --show off  # hide all three
   ```
2. **Headless launcher app**, one per key. It has no Dock icon and opens no Terminal window:
   ```
   osacompile -o "Show Giveaway.app" -e 'do shell script "/usr/bin/python3 \"/abs/obs-show-only.py\" --scene \"My Scene\" --group 31,32,33 --show 32"'
   plutil -insert LSUIElement -bool true "Show Giveaway.app/Contents/Info.plist"
   ```
3. **Key.** Use an Open action, which keeps a custom image:
   `sdeck.py add Showtime 1,0 --type open --path "/abs/Show Giveaway.app" --image giveaway.png`

Test by running `open "Show Giveaway.app"` and watching OBS. The launcher paths are absolute, so
keep the apps in one folder that won't move.
