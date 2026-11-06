# Making a game

Kolibri Games has three kinds of game. The `type` field in the manifest says which:

| Kind | `type` | What it keeps | How it reaches learners |
|---|---|---|---|
| **Saved Games** | `"saved"` | Each learner's progress, like unlocked levels | Through Kolibri Studio, in a channel |
| **Scored Games** | `"scored"` | Progress and scores, for scoreboards | Through Kolibri Studio, in a channel |
| **Server Games** | `"server"` | Progress and scores worked out by the server | Installed on the games page |

**Saved and Scored Games are made with [EduGame Kit](https://github.com/togetherings/edugame-kit)**
and added to Kolibri through Kolibri Studio. The kit builds one zip that works in Kolibri channels,
on the Kolibri Games scoreboards, in Moodle and other learning systems, RACHEL, Sugarizer and
Kiwix, and adds the right `kolibri-game.json` for you. See [CHANNEL_GAMES.md](CHANNEL_GAMES.md).

**This page is about Server Games:** games that need the plugin's server, so they can't go through
Studio. Wiki BLAZE uses the `wikipedia-race` service ([WIKI_BLAZE.md](WIKI_BLAZE.md)) and
BeaconHunt uses `photo-guess` ([PHOTO_PACKS.md](PHOTO_PACKS.md)). The server keeps what the learner
mustn't see, like the answers, and works out the score. A device administrator installs them on
the games page. (The games page can install the other kinds too, which is handy for trying a game,
but Studio is how they're meant to reach learners.)

How scores are described and ranked, for every kind, is in [SCORING.md](SCORING.md).

A game is a zip of ordinary web files plus a manifest:

```
my-game/
  kolibri-game.json   the manifest (required)
  index.html          the start page (or whatever "entry" says)
  game.js, style.css, images, sounds ...
  icon.svg            optional icon shown on the games page
```

Zip it with `kolibri-games-pack my-game` (or any zip tool, as long as `kolibri-game.json` is at the
top of the zip, not inside a folder). A device administrator then installs the zip on the games
page's **Setup** page.

## The rules your game runs under

- **It runs in a sandbox.** The game is shown in an iframe with its own private origin. It
  can't see the Kolibri page, the learner's session, cookies or `localStorage` belonging to
  Kolibri. Use the SDK's `getState`/`setState` to save progress.
- **Everything must be inside the game.** Files are served from your zip, and the security
  policy blocks loading anything from other servers. Bundle your libraries, fonts and images.
- **Relative paths only.** Refer to files as `game.js` or `img/cat.png`, never `/game.js`.
- **Forms are fine**, but a form can't navigate anywhere; handle `submit` in JavaScript.
- **Scores come from your game.** The server checks them against your `min` and `max`, records
  every move you report, and measures the time itself. Coaches can see the moves of every attempt.

## Manifest: `kolibri-game.json`

```json
{
  "format": 1,
  "type": "scored",
  "id": "org.example.my-game",
  "version": "1.0.0",
  "title": "My Game",
  "description": "One sentence about the game.",
  "entry": "index.html",
  "language": "en",
  "requires_platform": ">=0.2",
  "icon": "icon.svg",
  "color": "#2f6f8f",
  "scoring": {
    "label": "Moves",
    "unit": "moves",
    "order": "asc",
    "counts": "first",
    "tiebreak": "seconds",
    "min": 1,
    "max": 1000,
    "decimals": 0
  },
  "settings": [
    {"key": "level", "type": "choice", "label": "Difficulty",
     "choices": [{"value": 1, "label": "Easy"}, {"value": 2, "label": "Hard"}], "default": 1}
  ],
  "authors": ["Your name"],
  "license": "CC-BY-4.0"
}
```

| Field | Required | Meaning |
|---|---|---|
| `format` | yes | Always `1` for now. |
| `type` | yes | `"saved"`, `"scored"` or `"server"` (see the table at the top). |
| `id` | yes | Unique, lower-case, stays the same across versions (e.g. `org.example.my-game`). Installing a zip with the same id updates the game. |
| `version` | yes | Your game's version, like `1.0.0`. |
| `title` | yes | Name shown to learners. Keep it short (30 characters fits everywhere). |
| `description` | no | One sentence for the games page. |
| `entry` | no | Start page, default `index.html`. |
| `language` | no | The language the game starts in: a code like `en` or `pt-BR`. Default `en`. |
| `languages` | no | Every language the game can be played in, like `["en", "fr", "sw"]`. Default: just `language`. |
| `requires_platform` | no | Plugin versions the game works with, e.g. `>=0.2` or `>=0.2,<1`. Devices with an older plugin show "ask your administrator to update" instead of a broken game. |
| `icon`, `color` | no | Icon file and accent colour for the games page. Without an icon, a coloured tile with the first letter is used. |
| `scoring` | Scored and Server Games | What the scores are called and how they're ranked: one score (`label`, `order`, `tiebreak`, `min`, `max`), or several `fields` with `rank_by`, and levels with their own scoreboards (`boards`). `counts` is the default for which attempt counts: `first` (later attempts are practice), `best`, `latest` or `total` (every attempt added up); coaches can change it. `free_play_scoreboard: false` hides the free-play scoreboard, for games whose free-play rounds can't be compared (scores are then only ranked in challenges). See [SCORING.md](SCORING.md). Saved Games have none. |
| `settings` | no | Options coaches can change on the games page, for free play and for each challenge (games in channels don't have them). Types: `integer`, `number` (with optional `min`, `max`), `boolean`, `choice` (with `choices`), `text`. Each needs `key`, `label` and `default`, and can have a `help` line. |
| `data` | Server Games | Large data the game needs from the device, by name: `wikipedia` (a Wikipedia .zim file) or `photo-packs` (a folder of photo packs), chosen by an administrator on the Setup page. |
| `service` | Server Games | A server feature built into Kolibri Games: `"wikipedia-race"` (see [WIKI_BLAZE.md](WIKI_BLAZE.md)) or `"photo-guess"` (see [PHOTO_PACKS.md](PHOTO_PACKS.md)). |

Every game also gets these coach settings from the platform: a time limit and, for games with a
score, which attempt counts and what learners see on the scoreboard (names, initials only, or
only their own result).

A Saved Game's manifest is short:

```json
{
  "format": 1,
  "type": "saved",
  "id": "org.example.story-path",
  "version": "1.0.0",
  "title": "Story Path",
  "languages": ["en", "fr"]
}
```

It has no score, so it has no scoreboard and can't be used in a challenge. Save the learner's
progress with `KG.setState()` and read it back with `KG.getState()`: it's kept in their Kolibri
account, so they can carry on from any device.

## Free play and challenges

Learners can play any game whenever they like (**free play**), with the settings a coach chose for
the whole facility. A coach can also set up a **challenge** for one class: its own name, when it
opens and closes (with Open and Close buttons, or at set times), which attempt counts, time limit
and game settings. Each challenge has its own
scoreboard. Only Scored and Server Games can be challenges. Your game doesn't need to do anything different: `KG.ready()` tells you the settings
and whether it's a challenge.

## The SDK

Load it from this exact relative path (the platform always serves its current version there):

```html
<script src="__kolibri_games__/sdk.js"></script>
```

Every call returns a Promise. Errors have a `code` and a `message` you can show to the player.

```js
const KG = window.KolibriGames;

const info = await KG.ready();
// info.player     {name, role: "learner" | "coach" | "admin"}
// info.settings   the settings for this play (free play, or the challenge's), defaults filled in
// info.rules      {counts: "first"|"best"|"latest"|"total", scoreboard, time_limit: seconds or null}
// info.challenge  {title, class_name, opens_at, closes_at, ...} or null in free play
// info.summary    {attempts, counted, first_used}
// info.preview    true when opened outside Kolibri Games

const start = await KG.start({ resume: true });           // games with levels: { board: "level-3" }
// start.attempt  {id, number, board, practice}
// start.resumed  true if this continues an attempt the player left (after a reload)

await KG.move("guess", { value: 42 });                   // report a move (coaches see every move)
const done = await KG.finish({ score: 12, detail: {} }); // end the attempt with your score
// or, with several scores:  KG.finish({ values: { acc: 97, wpm: 41 }, detail: {} })
// done.attempt   {score, seconds, values, practice}
// done.standing  {rank, of, score, seconds, values, board} or null

await KG.scoreboard();           // {rows: [{rank, name, score, seconds, values, me}], boards, board, spec, counts, visibility}
await KG.scoreboard({ board: "level-3" });  // one level's scoreboard (or "_total")
await KG.myResults();            // {attempts: [...]}
await KG.getState();             // saved data for this player, or null
await KG.setState({ level: 3 }); // up to 64 KB of JSON
KG.on("timeup", () => { ... });  // the time limit ran out, or the challenge closed
KG.exit();                       // back to the games list
```

Notes:

- Time is measured by the server from `start` to `finish`; you don't report it. A field with
  `"source": "time"` shows it (see [SCORING.md](SCORING.md)).
- Call `start({resume: false})` if your game can't restore a half-finished attempt (the old one is
  recorded as left unfinished). Number Hunt does this, because its secret number lives only in
  the page.
- Each attempt can record up to 2000 moves of up to 4 KB each.
- With `counts: "first"`, an attempt the player leaves unfinished still uses up their counted
  attempt. Coaches can reset a learner if that happens by accident.

### Preview mode

Opened outside Kolibri Games (straight from a folder), the SDK runs in preview mode:
`info.preview` is `true` and results stay in that browser. Games that use a server `service` can't
start. To try the full experience without Kolibri, use the preview server:

```bash
kolibri-games-preview path/to/folder-with-games [--wikipedia examples/tiny-wiki]
```

It runs the real games page with pretend learners, a coach and an administrator (switch with the
bar at the bottom).

## Packaging and installing

```bash
kolibri-games-pack my-game                 # dist/org.example.my-game-1.0.0.zip
kolibri-games-pack --check dist/*.zip      # check a zip
```

On the device, an administrator opens **Games** in Kolibri's menu, then **Setup**, chooses the
zip and clicks **Install**. Installing a new version keeps the previous one, so they can go back
with one click. Zips copied into `<KOLIBRI_HOME>/kolibri_games/games/` by hand work too.
