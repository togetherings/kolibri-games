# Changelog

## 0.2.0

- **Three kinds of game,** set by `type` in `kolibri-game.json` (now required): **Saved Games**
  (`"saved"`) keep each learner's progress; **Scored Games** (`"scored"`) also keep a score, for
  scoreboards and challenges; **Server Games** (`"server"`) use one of the plugin's services, like
  Wiki BLAZE. Any kind can be installed on the games page. Saved and Scored Games can also be put
  in Kolibri channels, and work outside Kolibri too: make them with
  [EduGame Kit](https://github.com/togetherings/edugame-kit). This replaces Free-play Games and
  Classroom Games (`"free-play"` and `"classroom"` are gone).
- **Saved and Scored Games are added through Kolibri Studio**, in channels; Server Games are
  installed on the games page. Saved Games in channels are left alone, and Server Games in
  channels are shown as a problem.
- **Scores with several values**, each ranked its own way: `scoring.fields` and `rank_by` (the
  first field ranks, the next ones break ties, each higher or lower is better). The short form
  with one score still works. One `scoring` section now describes scores on the games page and
  in channels alike; the old `scoreboards` section is part of it (`saved_data`, and `from` on
  each field). See docs/SCORING.md.
- **Levels with their own scoreboards** (`scoring.boards`), and a **total scoreboard** that adds
  up each learner's results on every level. Games on the games page name the level with
  `KG.start({board})`; games in channels save one entry per level.
- **Which attempt counts** can also be the **latest**, or **every attempt added up** (for points
  that build up), as well as the first or the best.
- Games report several values with `KG.finish({values})`. Scoreboards, the coaches' results page
  and the CSV files show every value. Attempts keep the values and their level (a new migration).
- Scored Games in channels made with EduGame Kit: each board is a list of the fields' values,
  save data under keys starting with `_` is skipped, and each resource of a kit game without
  levels has its own scoreboard.
- The games page shows a game's kind next to its title. Saved Games have a **Play** button and
  no scoreboard or challenges. Games from channels are listed under **Scored Games in Learn**.
- Manifests can list the `languages` a game can be played in.
- Game keys on the games page start with `g-` (they were `f-`).
- Number Hunt and Memory Match have moved to EduGame Kit as its examples, so they're no longer
  attached to releases here (copies stay in `tests/fixtures/games` for the tests). The README
  links every game: Wiki BLAZE, BeaconHunt, Lessons In Typing, Studies In Geography, Sparkle and
  BoBo Na Mi.
- **Wiki BLAZE** (Browsing Links A-to-Z Exploration): race from one Wikipedia article to another
  by following links, using a Wikipedia `.zim` file on the device. The server checks every link
  and keeps each learner's chain. Going back to an earlier article is free, and the score is the
  number of links in the final chain. Coaches see every step; after a challenge closes, everyone
  sees all routes and the shortest route. Comes with the SolarSpell Wikipedia for Schools list
  (about 10,500 articles), and coaches can make their own article lists.
- **Photo guessing, for BeaconHunt:** a `photo-guess` service and photo packs (one per region of
  the world, copied into the photo-packs folder and listed on the Setup page). The server picks
  the photos, keeps where they were taken hidden until the learner guesses, removes GPS data from
  the photos, and scores each guess. Country mode: the right country, a neighbouring one, the same
  region or the same continent. Location mode: by distance. Games play on the whole world or on
  one continent's map. In a challenge, everyone gets the same photos. See `docs/PHOTO_PACKS.md`.
- **Challenges:** coaches set a game up for a class with its own settings, time limit and
  scoreboard. Coaches open and close a challenge with buttons, or at set times. Learners see their
  classes' challenges on the game card.
- **Wrong clocks:** a Raspberry Pi without a clock battery can have the wrong time. The Open and
  Close buttons always work, "open now" uses the server's own time, coaches see a warning when the
  server's clock and their device disagree by more than 10 minutes, and game times aren't thrown
  off when the clock jumps (for example when the Pi reaches the internet).
- **Installing games:** device administrators install, update, roll back and remove
  games on the Setup page. Games are zips (made with `kolibri-games-pack` or any zip tool).
  `kolibri-games-pack` checks a game without needing the data it uses on a device (photo packs,
  Wikipedia), so it works on any computer.
- The Wikipedia file for Wiki BLAZE is chosen on the Setup page.
- Games are no longer ZIM files, and rule checkers are gone: games report their own
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
  saved by more than one resource keeps each learner's best result. See `docs/CHANNEL_GAMES.md`.
- Example Classroom Game manifests for Lessons In Typing and Studies In Geography.
- Coaches choose per game what learners see on scoreboards (full names by default), show one
  class at a time and download scoreboards as CSV.
- The games page shows Free-play Games first, then Classroom Games.
- "Leaderboard" is now called "scoreboard" everywhere, inside the plugin too. Games built for
  0.1.0 need one change: call `KolibriGames.scoreboard()` instead of `KolibriGames.leaderboard()`.
- A **Games** link in Kolibri's side menu.
- Signing in from the games page now brings you back to the game you opened.
- The preview server can pretend Classroom Games were played (`--channel`).

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
