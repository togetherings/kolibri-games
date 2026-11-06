# Games in Kolibri channels

**Saved Games and Scored Games are added to Kolibri through Kolibri Studio**, as ordinary HTML5
apps (`.zip`) in a channel. Learners open them from Learn (also offline in the Kolibri app), and
coaches can put them in lessons and assign them to classes, like any other resource.

- **Saved Games** need nothing from Kolibri Games: Kolibri keeps each learner's progress. The
  games page doesn't list them.
- **Scored Games** also appear on the games page, under **Scored Games in Learn**, with
  **scoreboards** made from the scores the game saves: one for each level or lesson, and one for
  the whole game if the game asks for it.
- **Server Games** can't be put in a channel. If one is, the Setup page says so.

To add one:

1. In [Kolibri Studio](https://studio.learningequality.org/), open your channel and choose
   **Add > Upload files**, then choose the game's zip.
2. Fill in the title, language and license, and publish the channel.
3. On the Kolibri device, import the channel (or update it).

The easiest way to make these games is [EduGame Kit](https://github.com/togetherings/edugame-kit):
its zips already have a `kolibri-game.json` and save scores the way Kolibri Games reads them.
This page explains how that works, and how to make an existing HTML5 app a Scored Game.

## How it works

While a learner plays an HTML5 app, Kolibri gives it a SCORM 1.2 connection and keeps what the
app saves in `cmi.suspend_data` on the server, in the learner's record for that resource. Kolibri
Games reads that saved data. It doesn't change it, and the game doesn't need to know about Kolibri
Games at all.

To make an HTML5 app a Scored Game, add a `kolibri-game.json` file next to its `index.html`,
before you upload the zip to Kolibri Studio. The file says which game the app belongs to and how
to read scores out of its saved data. HTML5 apps without this file are left alone.

Words used on this page:

- **Game**: the umbrella, for example "Lessons In Typing". Every resource whose manifest has the
  same `id` belongs to the same game, even across lessons and channels.
- **Resource**: one HTML5 app (one zip) in a channel.
- **Board**: one scored thing in the saved data, for example one typing lesson, or one map played
  in one mode. If two resources save the same board (a map used in two lessons), they share one
  scoreboard, and each learner's best result counts.

## Games made with EduGame Kit

A Scored Game made with the kit saves each board (the game, or each level) as a list of its
scores in the order of its `scoring.fields`, and its own save data under keys starting with `_`
(these are never boards):

```json
{ "_v": 1, "_save": { "level": 3 }, "main": [7, 41.5, 3] }
```

Its `kolibri-game.json`, which the kit writes, lists the fields and leaves out `saved_data`:

```json
{
  "format": 1,
  "type": "scored",
  "id": "org.togetherings.number-hunt",
  "version": "1.0.0",
  "title": "Number Hunt",
  "scoring": {
    "fields": [
      { "key": "guesses", "label": "Guesses", "order": "asc" },
      { "key": "time", "label": "Time", "source": "time", "order": "asc", "total": "sum" },
      { "key": "plays", "label": "Times played", "source": "plays" }
    ],
    "rank_by": ["guesses", "time"]
  }
}
```

A kit game without levels saves one board, `main`, and each resource of it gets its own
scoreboard, named after the resource. A kit game with levels saves a board for each, named in
`scoring.boards`. See [SCORING.md](SCORING.md) for every part of `scoring`.

## Games that save their own way

`cmi.suspend_data` must be text holding a JSON object, with one entry per board, keyed by the
board's id (ids starting with `_` are skipped). Each entry is either an object or a list:

```json
{ "en-01": { "done": 1, "acc": 96, "wpm": 14 } }
```

```json
{ "us": [92, 140, 5], "us_capitals": [80, 210, 2] }
```

Keep board ids stable: changing one hides the scores saved under the old id. SCORM 1.2 allows
4096 characters in `cmi.suspend_data`, so keep it short.

Add `"saved_data": {"in": "scorm"}` to `scoring`, and give each field a `from`: a name for
objects (`"acc"`), or a position for lists (`0` is the first). `only_if` skips entries that
don't match.

Lessons In Typing: one lesson per resource, accuracy then speed, and only passed lessons count:

```json
{
  "format": 1,
  "type": "scored",
  "id": "org.togetherings.lit",
  "version": "0.21.0",
  "title": "Lessons In Typing",
  "description": "Typing lessons. Each lesson teaches a few new keys.",
  "color": "#2f6f5e",
  "scoring": {
    "saved_data": {
      "in": "scorm",
      "only_if": {
        "from": "done",
        "equals": 1
      }
    },
    "fields": [
      {
        "key": "acc",
        "label": "Accuracy",
        "unit": "%",
        "order": "desc",
        "total": "average"
      },
      {
        "key": "wpm",
        "label": "Speed",
        "unit": "wpm",
        "order": "desc",
        "total": "average"
      }
    ],
    "rank_by": [
      "acc",
      "wpm"
    ],
    "counts": "best",
    "boards": {
      "label": "Lesson",
      "after_resource": true,
      "total": {
        "label": "All lessons",
        "count_label": "Lessons passed"
      }
    }
  }
}
```

Studies In Geography: several maps and modes per resource, values in a list, accuracy then time:

```json
{
  "format": 1,
  "type": "scored",
  "id": "org.togetherings.singe",
  "version": "0.24.0",
  "title": "Studies In Geography",
  "description": "Find regions, capitals and flags on maps.",
  "color": "#2d5d8a",
  "scoring": {
    "saved_data": {
      "in": "scorm"
    },
    "fields": [
      {
        "key": "acc",
        "from": 0,
        "label": "Accuracy",
        "unit": "%",
        "order": "desc",
        "total": "average"
      },
      {
        "key": "time",
        "from": 1,
        "label": "Time",
        "source": "time",
        "seconds": true,
        "order": "asc",
        "total": "sum"
      },
      {
        "key": "plays",
        "from": 2,
        "label": "Times played",
        "source": "plays",
        "total": "sum"
      }
    ],
    "rank_by": [
      "acc",
      "time"
    ],
    "counts": "best",
    "boards": {
      "label": "Map",
      "names": {
        "us": "United States",
        "world_all": "World (all countries)"
      },
      "name_rules": [
        {
          "suffix": "_capitals",
          "name": "{name}: capitals"
        },
        {
          "suffix": "_flags",
          "name": "{name}: flags"
        },
        {
          "name": "{name}: regions"
        }
      ],
      "total": {
        "label": "All maps",
        "count_label": "Maps played"
      }
    }
  }
}
```

Both files are in [examples/channel-games](../examples/channel-games) (with every map's name).

### The manifest

| Field | Meaning |
|---|---|
| `format` | Always `1`. |
| `type` | `"scored"`. |
| `id` | The game's id, shared by every resource of the game. Never change it. |
| `version` | Like `1.2.0`. When resources have different versions, the newest manifest is used for the title, description and scoreboard layout. Board names from every version are kept. |
| `title`, `description`, `color`, `icon` | Shown on the games page. `icon` is a path inside the zip. |
| `requires_platform` | Optional, like `">=0.2"`. |
| `scoring` | The scores and how to read them: see [SCORING.md](SCORING.md). |

`settings` are only used on the games page. `data` and `service` are only for Server Games.

When resources save the same board (a map used in two lessons), they share one scoreboard: each
learner's best entry counts, and fields with `"source": "plays"` are added up. Values that are
missing from the saved data are shown as blank, so you can add a field to a game later (for
example "times played") and older saves still work.

## Settings and privacy

Coaches and administrators can choose, per game, what learners see on the scoreboards: full names
(the default), initials, or only their own result. Coaches always see full names, and can show
one class at a time and download a CSV.

Scores come from the game running in the learner's browser, so they aren't checked by the server.
The scoreboards say so.

Kolibri syncs learners' saved data between servers, so scoreboards also include results saved on
another Kolibri server that syncs with this one.

## Trying it without Kolibri

The preview server can pretend that learners played Scored Games in Learn:

```
kolibri-games-preview games --channel examples/channel-games/preview.json
```

`preview.json` lists resources (a folder or zip with a `kolibri-game.json`, plus a pretend
content id and title) and pretend saved data for the preview users `amina` and `ben`. Copy it and
change it to test your own game's manifest.
