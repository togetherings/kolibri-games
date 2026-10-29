# Architecture

```
 Kolibri channel / local folder            Kolibri server (this plugin)
 ┌──────────────────────────┐   import   ┌───────────────────────────────────────────┐
 │ number-hunt.zim          │ ─────────▶ │ registry.py   finds game ZIMs and folders  │
 │   kolibri-game.json      │            │ service.py    attempts, scores, rules      │
 │   index.html, game.js    │            │ validators/   trusted rule checkers        │
 └──────────────────────────┘            │ views.py      page, JSON API, game files   │
                                         │ models.py     results in Kolibri's DB      │
                                         └───────────────────────────────────────────┘
 Browser
 ┌───────────────────────────────────────────────────────────────┐
 │ Games page (app.js): signed in to Kolibri, calls the JSON API │
 │  ┌──────────────────────────────────────────────┐              │
 │  │ Game iframe, sandboxed (sdk.js + game files) │ postMessage  │
 │  │ no Kolibri session, no network beyond server │ ◀──────────▶ │
 │  └──────────────────────────────────────────────┘              │
 └───────────────────────────────────────────────────────────────┘
```

## Trust boundaries

- **Game files are untrusted.** They can come from any channel. They're served under
  `play/<token>/` with `Content-Security-Policy: sandbox allow-scripts allow-forms ...` and
  shown in an iframe without `allow-same-origin`, so a game gets an opaque origin: it can't read
  the Kolibri page, its cookies or the session, and can't call Kolibri's API as the learner. The
  policy also stops games loading anything from other servers. The token in the URL is signed by
  the server, names the game and the player, and expires after 12 hours.
- **The games page is trusted.** It's part of the plugin. It receives requests from the game
  through `postMessage`, accepts them only from its own iframe, and makes the API calls itself.
  Games can only do what the message API offers.
- **Rule checkers are trusted code**, installed by the administrator as Python packages. A game
  only names one. This is how scores that matter are protected: the server keeps the state,
  checks every move and calculates the score. Games without one have their claimed scores
  stored as unchecked, within the manifest's `min`/`max`.
- **Server-side timing.** Attempt times always come from the server clock.

## Data

All tables live in Kolibri's own database, so `kolibri manage dbbackup` includes them. Users and
facilities are referenced by their Kolibri ids, not foreign keys, so plugin migrations don't depend
on Kolibri's internal migration history.

| Table | What it holds |
|---|---|
| `Attempt` | One play: game, learner, attempt number, status (started, finished, abandoned, expired), server times, score, verified flag, the rule checker's hidden state, the public start data, the event log and the result details. Coach resets mark attempts *voided* rather than deleting them. |
| `GameSettings` | Coach settings per game per facility: platform rules and the game's own options. |
| `PlayerState` | Up to 64 KB of saved data per game per learner. |

Classroom Games add no tables. Their scores are read when needed from Kolibri's own
`ContentSummaryLog.extra_fields["contentState"]["SCORM"]`, where Kolibri keeps what an HTML5 app
saves. Those logs sync between Kolibri servers, unlike the plugin's tables. Scoreboard settings
use `GameSettings` under the key `g-<manifest id>`.

Which attempt counts is worked out when results are read, not stored: in *first* mode it's the
learner's earliest attempt that hasn't been reset, so leaving an attempt unfinished doesn't give
a second chance. Scoreboards use standard competition ranking.

## Finding games

`registry.discover()` looks in three places and caches the result for a few seconds:

1. **Kolibri channels:** every available `.zim` resource that contains `kolibri-game.json`
   (other ZIMs, like Wikipedia, are skipped). Key: `c-<content_id>`, stable across channel
   updates.
2. **Local folders:** `<KOLIBRI_HOME>/kolibri_games/games/` and anything in
   `KOLIBRI_GAMES_PATH`, as `.zim` files or plain folders. Key: `l-<manifest id>`.
3. **Classroom Games:** every available HTML5 app (`html5_zip`) in a channel whose zip contains a
   `kolibri-game.json` with `"type": "classroom"`. Each zip is opened once and the answer is kept
   by file checksum, so ordinary HTML5 apps cost one look. Resources with the same manifest id
   form one game. Key: `g-<manifest id>`. See [CLASSROOM_GAMES.md](CLASSROOM_GAMES.md).

Each game is checked against this device: plugin version (`requires_platform`), rule checker
installed, data sources configured, start page present. Problems are shown instead of a broken game.

## Shared code

`service.py`, `ranking.py`, `lessons.py`, `manifest.py`, `registry.py`, `sources.py` and
`views_common.py` don't import Django, so the same rules run in Kolibri (`store_django.py` + `views.py`), in the
unit tests and in the preview server (`devserver.py`, memory store).

## Not done yet (next steps)

- **Showing Free-play Games inside Kolibri's Learn page.** Today they're played on the games
  page (linked from Kolibri's side menu). Showing game ZIMs as resources in Learn and reporting
  completion to Kolibri's coach reports needs a content renderer built with Kolibri's front-end
  tooling. (Classroom Games already live in Learn.) When that's
  added, the plugin will claim the `zim` file type, show games in a sandbox inside Learn, and
  fall back to a simple viewer for ordinary ZIMs (so it shouldn't be enabled together with
  kolibri-zim-plugin).
- **Testing Studio uploads.** Confirm that Kolibri Studio accepts game ZIMs as resources and
  that Kolibri imports them. The sample game ZIMs in each release are meant for that test.
- **Challenges for Free-play Games**: coaches set up a challenge for a class (open and close
  dates, game options, routes revealed after it closes), next to free play.
- **Wiki Race** as a game with a rule checker that reads the device's Wikipedia ZIM through a
  data source.
