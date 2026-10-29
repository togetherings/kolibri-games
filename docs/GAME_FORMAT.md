# Making a game for Kolibri Games

This page is about **Free-play Games**, which are played on the games page. For games that
learners open from Learn (HTML5 apps with scoreboards), see [CLASSROOM_GAMES.md](CLASSROOM_GAMES.md).

A game is a folder of ordinary web files plus a manifest:

```
my-game/
  kolibri-game.json   the manifest (required)
  index.html          the start page (or whatever "entry" says)
  game.js, style.css, images, sounds ...
  icon.svg            optional icon shown on the games page
```

Package it with `kolibri-games-pack my-game` to get a `.zim` file that you can upload to a
Kolibri Studio channel or copy into a device's games folder.

## The rules your game runs under

- **It runs in a sandbox.** The game is shown in an iframe with its own private origin. It
  can't see the Kolibri page, the learner's session, cookies or `localStorage` belonging to
  Kolibri. Use the SDK's `getState`/`setState` to save progress.
- **Everything must be inside the game.** Files are served from your ZIM, and the security
  policy blocks loading anything from other servers. Bundle your libraries, fonts and images.
- **Relative paths only.** Refer to files as `game.js` or `img/cat.png`, never `/game.js`.
- **Forms are fine**, but a form can't navigate anywhere; handle `submit` in JavaScript.

## Manifest: `kolibri-game.json`

```json
{
  "format": 1,
  "id": "org.example.my-game",
  "version": "1.0.0",
  "title": "My Game",
  "description": "One sentence about the game.",
  "entry": "index.html",
  "language": "en",
  "requires_platform": ">=0.1",
  "icon": "icon.svg",
  "color": "#2f6f8f",
  "validator": "my-game",
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
  "data": [],
  "authors": ["Your name"],
  "license": "CC-BY-4.0"
}
```

| Field | Required | Meaning |
|---|---|---|
| `format` | yes | Always `1` for now. |
| `id` | yes | Unique, lower-case, stays the same across versions (e.g. `org.example.my-game`). |
| `version` | yes | Your game's version, like `1.0.0`. |
| `title` | yes | Name shown to learners. Keep it short (30 characters fits everywhere). |
| `description` | no | One sentence for the games page. |
| `type` | no | `"free-play"` (the default). Classroom Games use `"classroom"`; see [CLASSROOM_GAMES.md](CLASSROOM_GAMES.md). |
| `entry` | no | Start page, default `index.html`. |
| `language` | no | Two- or three-letter code, default `en`. |
| `requires_platform` | no | Plugin versions the game works with, e.g. `>=0.1` or `>=0.2,<1`. Devices with an older plugin show "ask your administrator to update" instead of a broken game. |
| `icon`, `color` | no | Icon file and accent colour for the games page. Without an icon, a coloured tile with the first letter is used. |
| `validator` | no | Name of a server-side rule checker (see below). Without one, the game reports its own score and coaches see it as *unchecked*. |
| `scoring` | no | Leave it out for games without scores (no scoreboard). `order` is `asc` when lower is better, `desc` when higher is better. `counts` is the default for which attempt counts on the scoreboard: `first` (later attempts are practice) or `best`; coaches can change it. `tiebreak` is `seconds` (faster wins ties) or `none`. `min`/`max` reject impossible scores. |
| `settings` | no | Options coaches can change. Types: `integer`, `number` (with optional `min`, `max`), `boolean`, `choice` (with `choices`), `text`. Each needs `key`, `label` and `default`. |
| `data` | no | Large data the game needs from the device, by name, e.g. `[{"name": "wikipedia"}]`. Administrators map names to files in `data_sources.json`. Games that need missing data are shown as unavailable. |

Every game also gets these coach settings from the platform: which attempt counts, what learners
see on the scoreboard (names, initials only, or only their own result), and a time limit.

## The SDK

Load it from this exact relative path (the platform always serves its current version there):

```html
<script src="__kolibri_games__/sdk.js"></script>
```

Every call returns a Promise. Errors have a `code` and a `message` you can show to the player.

```js
const KG = window.KolibriGames;

const info = await KG.ready();
// info.player   {name, role: "learner" | "coach" | "admin"}
// info.settings the coach's settings for your game (defaults filled in)
// info.rules    {counts: "first"|"best", scoreboard, time_limit: seconds or null}
// info.summary  {attempts, counted, first_used, counts}
// info.preview  true when opened outside Kolibri Games

const start = await KG.start({ resume: true });
// start.attempt  {id, number, practice}
// start.public   data from your rule checker (e.g. the range to guess in)
// start.resumed  true if this continues an attempt the player left (after a reload)

const reply = await KG.event("guess", { value: 42 });   // log a move; the rule checker may answer
const done = await KG.finish({ score: 12, detail: {} }); // end the attempt
// done.attempt   {score, seconds, verified, practice}
// done.standing  {rank, of, score} or null

await KG.scoreboard();          // {rows: [{rank, name, score, seconds, me}], counts, visibility}
await KG.myResults();           // {attempts: [...]}
await KG.getState();            // saved data for this player, or null
await KG.setState({ level: 3 }); // up to 64 KB of JSON
await KG.call("search", {q: "x"}); // ask your rule checker something outside an attempt
KG.on("timeup", () => { ... });  // the coach's time limit ran out
KG.exit();                       // back to the games list
```

Notes:

- Time is measured by the server from `start` to `finish`; you don't report it.
- Call `start({resume: false})` if your game can't restore a half-finished attempt (the old one is
  recorded as left unfinished).
- Each attempt can log up to 2000 events of up to 4 KB each. Coaches see them under *History*.
- With `counts: "first"`, an attempt the player leaves unfinished still uses up their counted
  attempt. Coaches can reset a learner if that happens by accident.

### Preview mode

Opened outside Kolibri Games (from a folder, or a ZIM opened in Kiwix), the SDK runs in preview
mode: `info.preview` is `true`, results stay in that browser, and games with a rule checker can't
start. To try the full experience without Kolibri, use the preview server:

```bash
kolibri-games-preview path/to/folder-with-games
```

It runs the real games page with pretend learners and a coach (switch with the bar at the bottom).

## Rule checkers (validators)

A rule checker is Python code that runs on the server, so the browser can't fake the result. It
can keep secrets (like the answer), check every move, and calculate the final score. They're
installed by the device administrator, never delivered through channels.

```python
from kolibri_games.validators import Validator, ValidatorError

class MyGameValidator(Validator):
    name = "my-game"

    def start(self, ctx):
        # ctx.settings, ctx.rng, ctx.attempt, ctx.data (data source paths)
        secret = ctx.rng.randint(1, 100)
        return {"state": {"secret": secret, "moves": 0}, "public": {"low": 1, "high": 100}}

    def event(self, ctx, state, type, data):
        if type != "guess":
            raise ValidatorError("Unknown move.")
        state = dict(state, moves=state["moves"] + 1)
        return state, {"hint": "higher" if data["value"] < state["secret"] else "lower"}

    def finish(self, ctx, state, claimed):
        return {"score": state["moves"], "detail": {"secret": state["secret"]}}
```

`state` stays on the server. Only what you return as `public` or as a reply reaches the browser.
Also available: `resume(ctx, state, public)` to rebuild what the game needs after a reload, and
`call(ctx, method, params)` for requests outside an attempt.

Ship validators in a Python package that declares an entry point:

```toml
[project.entry-points."kolibri_games.validators"]
my-game = "my_package.validators:MyGameValidator"
```

The built-in example is [`kolibri_games/validators/number_hunt.py`](../kolibri_games/validators/number_hunt.py).

## Packaging and publishing

```bash
kolibri-games-pack my-game                 # dist/org.example.my-game_1.0.0.zim
kolibri-games-pack --check dist/*.zim      # verify a packed game
```

The ZIM contains your files, the manifest, a 48×48 illustration (your `icon` if it's a 48×48 PNG,
otherwise a tile in your colour) and a copy of the SDK for preview mode.
