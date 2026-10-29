# Changelog

## 0.2.0

- **Wiki BLAZE** (Browsing Links A-to-Z Exploration): race from one Wikipedia article to another
  by following links, using a Wikipedia `.zim` file on the device. The server checks every link
  and keeps each learner's chain. Going back to an earlier article is free, and the score is the
  number of links in the final chain. Coaches see every step; after a challenge closes, everyone
  sees all routes and the shortest route. Comes with the SolarSpell Wikipedia for Schools list
  (about 10,500 articles), and coaches can make their own article lists.
- **Challenges:** coaches set a game up for a class with its own settings, open and close dates,
  time limit and scoreboard. Learners see their classes' challenges on the game card.
- **Installing Free-play Games:** device administrators install, update, roll back and remove
  games on the Setup page. Games are zips (made with `kolibri-games-pack` or any zip tool).
- The Wikipedia file for Wiki BLAZE is chosen on the Setup page.
- Free-play Games are no longer ZIM files, and rule checkers are gone: games report their own
  scores, and impossible scores are refused. The "unchecked" label is gone too.
- Game SDK version 2: `KolibriGames.move()` replaces `event()`, and `call()` is removed.
- libzim is only needed for Wiki BLAZE; the installer installs it and carries on without it if it
  can't.
- Number Hunt now picks its secret number in the browser.

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
