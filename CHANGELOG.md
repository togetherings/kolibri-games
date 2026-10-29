# Changelog

## 0.1.1

- **Classroom Games.** HTML5 apps in Kolibri channels can now be Classroom Games: learners open them
  from Learn as usual, and the games page shows scoreboards made from the scores the app saves
  in SCORM `cmi.suspend_data`. Add a `kolibri-game.json` with `"type": "classroom"` to the app's zip
  to say how to read the scores. All resources with the same game id form one game, and a board
  saved by more than one resource keeps each learner's best result. See `docs/CLASSROOM_GAMES.md`.
- Example Classroom Game manifests for Lessons In Typing and Studies In Geography.
- Coaches choose per game what learners see on scoreboards (full names by default), show one
  class at a time and download scoreboards as CSV.
- The games page shows Free-play Games first, then Classroom Games.
- "Leaderboard" is now called "scoreboard" everywhere, inside the plugin too. Games built for
  0.1.0 need one change: call `KolibriGames.scoreboard()` instead of `KolibriGames.leaderboard()`.
  Coaches' scoreboard settings carry over.
- A **Games** link in Kolibri's side menu.
- Signing in from the games page now brings you back to the game you opened.
- The preview server can pretend Classroom Games were played (`--classroom`).

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
