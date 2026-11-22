# stream-deck-buttons

An agent skill that lets an AI assistant (Claude Code, Codex, or any tool that loads `SKILL.md`
skills) add, copy and remove Elgato Stream Deck buttons on a Mac. It backs up the profile before
every edit and refuses to edit while the Stream Deck app is open, because the app would overwrite
the change.

Install: copy the `stream-deck-buttons/` folder into your agent's skills folder
(for Claude Code, `~/.claude/skills/`). Then ask: "add a button to my Stream Deck that opens X".

Run the tests with `python3 -m unittest tests/test_sdeck.py`.
