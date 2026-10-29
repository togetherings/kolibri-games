# Architecture

```
 Setup page upload / games folder          Kolibri server (this plugin)
 ┌──────────────────────────┐   install  ┌────────────────────────────────────────────┐
 │ wiki-blaze.zip           │ ─────────▶ │ install.py    installs, rolls back, removes │
 │   kolibri-game.json      │            │ registry.py   finds games                   │
 │   index.html, game.js    │            │ service.py    free play, challenges, scores │
 └──────────────────────────┘            │ wiki.py       reads the Wikipedia ZIM       │
 Kolibri channel (HTML5 apps)            │ wikirace.py   Wiki BLAZE rules              │
 ┌──────────────────────────┐   import   │ classroom.py  Classroom Game scoreboards    │
 │ lit-lesson-1.zip         │ ─────────▶ │ views.py      page, JSON API, game files    │
 │   kolibri-game.json      │            │ models.py     results in Kolibri's database │
 └──────────────────────────┘            └────────────────────────────────────────────┘
 Browser
 ┌───────────────────────────────────────────────────────────────┐
 │ Games page (app.js): signed in to Kolibri, calls the JSON API │
 │  ┌──────────────────────────────────────────────┐              │
 │  │ Game iframe, sandboxed (sdk.js + game files) │ postMessage  │
 │  │ no Kolibri session, no network beyond server │ ◀──────────▶ │
 │  └──────────────────────────────────────────────┘              │
 └───────────────────────────────────────────────────────────────┘
```

## Two kinds of game

- **Free-play Games** are zips installed into the plugin by a device administrator (Setup page,
  `install.py`) and played on the games page, in free play or in a coach's challenge.
- **Classroom Games** are HTML5 apps in Kolibri channels, played in Learn. The plugin only reads
  the scores they save, to show scoreboards (`classroom.py`, [CLASSROOM_GAMES.md](CLASSROOM_GAMES.md)).

## Trust boundaries

- **Game files are untrusted.** They're served under `play/<token>/` with
  `Content-Security-Policy: sandbox allow-scripts allow-forms ...` and shown in an iframe without
  `allow-same-origin`, so a game gets an opaque origin: it can't read the Kolibri page, its
  cookies or the session, and can't call Kolibri's API as the learner. The policy also stops games
  loading anything from other servers. The token in the URL is signed by the server, names the
  game and the player, and expires after 12 hours.
- **The games page is trusted.** It's part of the plugin. It receives requests from the game
  through `postMessage`, accepts them only from its own iframe, and makes the API calls itself.
  Games can only do what the message API offers.
- **Scores come from the game**, except in Wiki BLAZE. The server refuses scores outside the
  manifest's `min` and `max`, measures time itself and keeps every move for coaches. A learner
  with developer tools could still report a made-up score; these are learning games, not tests.
- **Wiki BLAZE is checked by the server.** Every article comes from the server, which checks each
  link, keeps the chain and works out the score (`wikirace.py`).
- **Only device administrators install games.** Uploads are written to a temporary file in
  pieces, checked (manifest, start page, size limit) and only then moved into the games folder.
  No code from a game ever runs on the server.

## Data

All tables live in Kolibri's own database, so `kolibri manage dbbackup` includes them. Users,
classes and facilities are referenced by their Kolibri ids, not foreign keys, so plugin migrations
don't depend on Kolibri's internal migration history.

| Table | What it holds |
|---|---|
| `Attempt` | One play: game, learner, challenge (empty for free play), attempt number, status (started, finished, abandoned, expired), server times, score, the server's state (a Wiki BLAZE chain), every move, and the result details. Coach resets mark attempts *voided* rather than deleting them. |
| `Challenge` | A game set up for one class: name, settings, which attempt counts, time limit, open and close times, and (Wiki BLAZE) the shortest route. |
| `GameSettings` | Free-play settings per game per facility: platform rules and the game's own options. |
| `ArticleList` | A coach's list of Wikipedia articles for Wiki BLAZE, per facility. |
| `PlayerState` | Up to 64 KB of saved data per game per learner. |

Classroom Games add no tables. Their scores are read when needed from Kolibri's own
`ContentSummaryLog.extra_fields["contentState"]["SCORM"]`, where Kolibri keeps what an HTML5 app
saves. Those logs sync between Kolibri servers, unlike the plugin's tables.

Which attempt counts is worked out when results are read, not stored: in *first* mode it's the
learner's earliest attempt that hasn't been reset, so leaving an attempt unfinished doesn't give
a second chance. Scoreboards use standard competition ranking.

Files on disk, under `<KOLIBRI_HOME>/kolibri_games/`: `games/` (installed zips, `.previous/` for
the version before the last update), and `data_sources.json` (the Wikipedia file's path).

## Finding games

`registry.discover()` looks in two places and caches the result for 15 seconds:

1. **The games folder** (`<KOLIBRI_HOME>/kolibri_games/games/`), plus any folders in
   `KOLIBRI_GAMES_PATH` for game makers (which can hold unzipped game folders). Key:
   `f-<manifest id>`.
2. **Kolibri channels:** every available HTML5 app (`html5_zip`) whose zip contains a
   `kolibri-game.json` with `"type": "classroom"`. Each zip is opened once and the answer is kept
   by file checksum, so ordinary HTML5 apps cost one look. Resources with the same manifest id
   form one game. Key: `c-<manifest id>`.

Each game is checked against this device: plugin version (`requires_platform`), data sources
(the Wikipedia file), start page present. Problems are shown instead of a broken game. Files that
look like games but can't be used get an `x-` key and show on the Setup page.

## Wiki BLAZE

`wiki.py` reads a Wikipedia ZIM with libzim (or, for tests, a folder like `examples/tiny-wiki`):
it follows redirects, cleans articles (removes scripts, styles and forms; turns links to allowed
articles into `<a data-to="...">`; serves pictures under the game's `__wiki__/` address), suggests
titles, matches article lists against the file, makes random pairs with a short random walk, and
works out shortest routes with a limited breadth-first search in a background thread.
`wikirace.py` holds the rules. See [WIKI_BLAZE.md](WIKI_BLAZE.md).

## Shared code

`service.py`, `ranking.py`, `classroom.py`, `wiki.py`, `wikirace.py`, `install.py`, `manifest.py`,
`registry.py`, `sources.py` and `views_common.py` don't import Django, so the same rules run in
Kolibri (`store_django.py` + `views.py`), in the unit tests and in the preview server
(`devserver.py`, memory store).

## Not done yet (next steps)

- **GeoGuessr-style game** using offline maps and photos as a data source.
- **An online list of games** for devices with internet, to install from without downloading
  zips by hand.
- **Translations** of the games page and Kolibri menu label.
