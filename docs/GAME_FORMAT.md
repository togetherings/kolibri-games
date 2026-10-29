# Making a Free-play Game

This page is about **Free-play Games**, which are installed into Kolibri Games and played on the
games page. For games that learners open from Learn (HTML5 apps with scoreboards), see
[CLASSROOM_GAMES.md](CLASSROOM_GAMES.md).

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
  "type": "free-play",
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
| `type` | no | `"free-play"` (the default). Classroom Games use `"classroom"`. |
| `id` | yes | Unique, lower-case, stays the same across versions (e.g. `org.example.my-game`). Installing a zip with the same id updates the game. |
| `version` | yes | Your game's version, like `1.0.0`. |
| `title` | yes | Name shown to learners. Keep it short (30 characters fits everywhere). |
| `description` | no | One sentence for the games page. |
| `entry` | no | Start page, default `index.html`. |
| `language` | no | Two- or three-letter code, default `en`. |
| `requires_platform` | no | Plugin versions the game works with, e.g. `>=0.2` or `>=0.2,<1`. Devices with an older plugin show "ask your administrator to update" instead of a broken game. |
| `icon`, `color` | no | Icon file and accent colour for the games page. Without an icon, a coloured tile with the first letter is used. |
| `scoring` | no | Leave it out for games without scores (no scoreboard). `order` is `asc` when lower is better, `desc` when higher is better. `counts` is the default for which attempt counts: `first` (later attempts are practice) or `best`; coaches can change it. `tiebreak` is `seconds` (faster wins ties) or `none`. `min`/`max` refuse impossible scores. `free_play_scoreboard: false` hides the free-play scoreboard, for games whose free-play rounds can't be compared (scores are then only ranked in challenges). |
| `settings` | no | Options coaches can change, for free play and for each challenge. Types: `integer`, `number` (with optional `min`, `max`), `boolean`, `choice` (with `choices`), `text`. Each needs `key`, `label` and `default`, and can have a `help` line. |
| `data` | no | Large data the game needs from the device, by name. For now only `[{"name": "wikipedia"}]`, chosen by an administrator on the Setup page. |
| `service` | no | A server feature built into Kolibri Games. For now only `"wikipedia-race"`: see [WIKI_BLAZE.md](WIKI_BLAZE.md). |

Every game also gets these coach settings from the platform: which attempt counts, what learners
see on the scoreboard (names, initials only, or only their own result), and a time limit.

## Free play and challenges

Learners can play any game whenever they like (**free play**), with the settings a coach chose for
the whole facility. A coach can also set up a **challenge** for one class: its own name, open and
close dates, which attempt counts, time limit and game settings. Each challenge has its own
scoreboard. Your game doesn't need to do anything different: `KG.ready()` tells you the settings
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
// info.rules      {counts: "first"|"best", scoreboard, time_limit: seconds or null}
// info.challenge  {title, class_name, opens_at, closes_at, ...} or null in free play
// info.summary    {attempts, counted, first_used}
// info.preview    true when opened outside Kolibri Games

const start = await KG.start({ resume: true });
// start.attempt  {id, number, practice}
// start.resumed  true if this continues an attempt the player left (after a reload)

await KG.move("guess", { value: 42 });                   // report a move (coaches see every move)
const done = await KG.finish({ score: 12, detail: {} }); // end the attempt with your score
// done.attempt   {score, seconds, practice}
// done.standing  {rank, of, score} or null

await KG.scoreboard();           // {rows: [{rank, name, score, seconds, me}], counts, visibility}
await KG.myResults();            // {attempts: [...]}
await KG.getState();             // saved data for this player, or null
await KG.setState({ level: 3 }); // up to 64 KB of JSON
KG.on("timeup", () => { ... });  // the time limit ran out, or the challenge closed
KG.exit();                       // back to the games list
```

Notes:

- Time is measured by the server from `start` to `finish`; you don't report it.
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
