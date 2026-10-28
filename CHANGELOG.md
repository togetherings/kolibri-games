# Changelog

## 0.1.0

First version of the Kolibri Games platform.

- Games are ZIM files (or folders) with a `kolibri-game.json` manifest, found in Kolibri channels
  and in local game folders.
- Games run in a sandboxed iframe and talk to the platform through a small JavaScript SDK.
- Server-side rule checkers ("validators") for scores that can't be faked; client-scored games
  are marked as unchecked.
- Results, leaderboards (names, initials or hidden), first-or-best attempt counting, time limits,
  saved player data, coach results with move history, CSV export and resets.
- Coach settings per facility, including each game's own options.
- Setup page and `kolibri manage kolibri_games_check` for administrators.
- `kolibri-games-pack` to package games, `kolibri-games-preview` to try them without Kolibri.
- `install.sh` for installing and updating, online or from an offline bundle.
- Sample games: Number Hunt (server-checked) and Memory Match (client-scored).
