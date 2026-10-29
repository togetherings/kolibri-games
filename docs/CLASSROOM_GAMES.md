# Classroom Games

Kolibri Games has two kinds of game:

- **Free-play Games** are installed into Kolibri Games and played on the games page (see
  [GAME_FORMAT.md](GAME_FORMAT.md)).
- **Classroom Games** are ordinary Kolibri HTML5 apps (`.zip`) in a channel. Learners open them from
  Learn, and coaches can put them in lessons and assign them to classes, like any other resource.
  The games page shows **scoreboards** made from the scores the game saves.

This page is about Classroom Games.

## How it works

While a learner plays an HTML5 app, Kolibri gives it a SCORM 1.2 connection and keeps what the
app saves in `cmi.suspend_data` on the server, in the learner's record for that resource. Kolibri
Games reads that saved data. It doesn't change it, and the game doesn't need to know about Kolibri
Games at all.

To make an HTML5 app a Classroom Game, add a `kolibri-game.json` file next to its `index.html`,
before you upload the zip to Kolibri Studio. The file says which game the app belongs to and how
to read scores out of its saved data. HTML5 apps without this file are left alone.

Words used on this page:

- **Game**: the umbrella, for example "Lessons In Typing". Every resource whose manifest has the
  same `id` belongs to the same game, even across lessons and channels.
- **Resource**: one HTML5 app (one zip) in a channel.
- **Board**: one scored thing in the saved data, for example one typing lesson, or one map played
  in one mode. If two resources save the same board (a map used in two lessons), they share one
  scoreboard, and each learner's best result counts.

## What the saved data must look like

`cmi.suspend_data` must be text holding a JSON object, with one entry per board, keyed by the
board's id. Each entry is either an object or a list:

```json
{ "en-01": { "done": 1, "acc": 96, "wpm": 14 } }
```

```json
{ "us": [92, 140, 5], "us_capitals": [80, 210, 2] }
```

Keep board ids stable: changing one hides the scores saved under the old id. SCORM 1.2 allows
4096 characters in `cmi.suspend_data`, so keep it short.

## The manifest

Example for Lessons In Typing (one lesson per resource, the board is named after the resource):

```json
{
  "format": 1,
  "type": "classroom",
  "id": "org.togetherings.lit",
  "version": "0.21.0",
  "title": "Lessons In Typing",
  "description": "Typing lessons. Each lesson teaches a few new keys.",
  "color": "#2f6f5e",
  "scoreboards": {
    "saved_in": "scorm",
    "board_label": "Lesson",
    "name_boards_after_resource": true,
    "only_if": { "from": "done", "equals": 1 },
    "fields": [
      { "key": "acc", "from": "acc", "label": "Accuracy", "unit": "%", "order": "desc" },
      { "key": "wpm", "from": "wpm", "label": "Speed", "unit": "wpm", "order": "desc" }
    ],
    "rank_by": ["acc", "wpm"]
  }
}
```

Example for Studies In Geography (several maps and modes per resource, values in a list):

```json
{
  "format": 1,
  "type": "classroom",
  "id": "org.togetherings.singe",
  "version": "0.24.0",
  "title": "Studies In Geography",
  "scoreboards": {
    "board_label": "Map",
    "fields": [
      { "key": "acc", "from": 0, "label": "Accuracy", "unit": "%", "order": "desc" },
      { "key": "time", "from": 1, "label": "Time", "seconds": true, "order": "asc" },
      { "key": "plays", "from": 2, "label": "Times played", "combine": "sum" }
    ],
    "rank_by": ["acc", "time"],
    "board_names": { "us": "United States", "world_all": "World (all countries)" },
    "board_name_rules": [
      { "suffix": "_capitals", "name": "{name}: capitals" },
      { "suffix": "_flags", "name": "{name}: flags" },
      { "name": "{name}: regions" }
    ]
  }
}
```

Both files are in [examples/classroom-games](../examples/classroom-games).

### Fields

| Field | Meaning |
|---|---|
| `format` | Always `1`. |
| `type` | `"classroom"`. |
| `id` | The game's id, shared by every resource of the game. Never change it. |
| `version` | Like `1.2.0`. When resources have different versions, the newest manifest is used for the title, description and scoreboard layout. Board names from every version are kept. |
| `title`, `description`, `color`, `icon` | Shown on the games page. `icon` is a path inside the zip. |
| `requires_platform` | Optional, like `">=0.2"`. |
| `scoreboards` | How to read the saved data, below. |

Classroom Games can't use `scoring`, `settings`, `data` or `service`: those are for Free-play
Games.

### `scoreboards`

| Field | Meaning |
|---|---|
| `saved_in` | Where the data is. Only `"scorm"` (`cmi.suspend_data`) for now. |
| `fields` | Up to 8 values to show for each learner. See below. |
| `rank_by` | Field keys used to rank learners, most important first. Each needs an `order`. |
| `only_if` | Optional. Skip entries unless the value at `from` equals `equals`, for example only passed lessons. |
| `board_label` | What one board is called on the page, like `"Lesson"` or `"Map"`. |
| `board_names` | Optional names for board ids. |
| `board_name_rules` | Optional rules that build a name from part of the id. The first rule whose `prefix` and `suffix` match is used. `{name}` is the `board_names` entry for the rest of the id (or the rest of the id itself), and `{id}` is the rest of the id. |
| `name_boards_after_resource` | If `true`, a board without a name takes the title of the resource that saved it. Use this when each resource has one board. |

Each entry in `fields`:

| Field | Meaning |
|---|---|
| `key` | A short name for the value, like `acc`. |
| `from` | Where the value is in a board's entry: a name for objects (`"acc"`), or a position for lists (`0` is the first). Defaults to `key`. |
| `label` | Column heading, like `"Accuracy"`. |
| `unit` | Optional, like `"%"` or `"wpm"`. |
| `seconds` | `true` if the value is a number of seconds; it's shown as minutes and seconds. |
| `decimals` | Digits after the point. Default 0. |
| `order` | `"desc"` if higher is better, `"asc"` if lower is better. Needed for fields in `rank_by`. |
| `combine` | How results from different resources are joined: `"best"` (default, taken from the learner's best result), `"sum"` (added up, for counts like times played) or `"max"`. |

Values that are missing from the saved data are shown as blank, so you can add a field to a game
later (for example "times played") and older saves still work.

## Settings and privacy

Coaches and administrators can choose, per game, what learners see on the scoreboards: full names
(the default), initials, or only their own result. Coaches always see full names, and can show
one class at a time and download a CSV.

Scores come from the game running in the learner's browser, so they aren't checked by the server.
The scoreboards say so.

Kolibri syncs learners' saved data between servers, so scoreboards also include results saved on
another Kolibri server that syncs with this one.

## Trying it without Kolibri

The preview server can pretend that learners played Classroom Games in Learn:

```
kolibri-games-preview games --classroom examples/classroom-games/preview.json
```

`preview.json` lists resources (a folder or zip with a `kolibri-game.json`, plus a pretend
content id and title) and pretend saved data for the preview users `amina` and `ben`. Copy it and
change it to test your own game's manifest.
