# stream-deck-buttons

An agent skill that lets an AI assistant (Claude Code, Codex, or any tool that loads `SKILL.md`
skills) add, copy and remove Elgato Stream Deck buttons on a Mac. It backs up the profile before
every edit and refuses to edit while the Stream Deck app is open, because the app would overwrite
the change.

## Requirements

- macOS (the scripts quit/launch the app with `osascript`/`open`).
- Elgato Stream Deck app 6.x or later (profiles live in
  `~/Library/Application Support/com.elgato.StreamDeck/ProfilesV3`).
- Python 3.8+ (stdlib only for `scripts/sdeck.py`).
- Only for `--type shell` buttons: the "Shell Commands" plugin by Ceylon Systems from the Elgato
  Marketplace: https://marketplace.elgato.com/product/shell-commands-eef83710-601c-4756-bb4e-e9621f804261
  (paid plugin, listed at EUR 6.49 on 2026-11-22; needs Stream Deck 6.5 or later).
- Only for `scripts/obs-show-only.py`: `pip install websocket-client`
  (https://pypi.org/project/websocket-client/; current releases need Python 3.10+), and OBS Studio
  28+ with the obs-websocket v5 server enabled (OBS > Tools > WebSocket Server Settings; default
  port 4455). Doc: https://github.com/obsproject/obs-websocket

Agents: before running, check each dependency the task needs (e.g. `sw_vers`, `python3 --version`,
the app in `/Applications`, the `ProfilesV3` folder, `python3 -c "import websocket"`); if something
is missing, tell the user and point only to the links above. Never guess or search for other
install sources.

Install: copy the `stream-deck-buttons/` folder into your agent's skills folder
(for Claude Code, `~/.claude/skills/`). Then ask: "add a button to my Stream Deck that opens X".

Run the tests with `python3 -m unittest tests/test_sdeck.py`.
