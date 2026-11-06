# Scores and scoreboards

Every Scored Game and Server Game has a `scoring` section in its `kolibri-game.json`. It says what
the scores are, how they're ranked, and which scoreboards there are. The same section is used on
the games page (free play and challenges) and for Scored Games in Kolibri channels. Games made
with [EduGame Kit](https://github.com/togetherings/edugame-kit) get it from their `edugame.json`.

## One score

Most games have one score, and maybe the time as a tiebreak:

```json
"scoring": {
  "label": "Guesses",
  "unit": "guesses",
  "order": "asc",
  "tiebreak": "seconds",
  "counts": "first",
  "min": 1,
  "max": 1000
}
```

| Field | Meaning |
|---|---|
| `label`, `unit`, `decimals` | What the score is called, its unit, and how many decimal places to show. |
| `order` | `"asc"` if a lower score is better (guesses, moves), `"desc"` if higher is better (points). |
| `tiebreak` | `"seconds"` (the default): a faster round wins a tie. `"none"`: equal scores share a place. |
| `counts` | Which attempt counts (coaches can change it): see below. |
| `min`, `max` | Scores outside these are refused. |
| `free_play_scoreboard` | `false` hides the free-play scoreboard, for games whose free-play rounds can't be compared. |

This is the same as the full form below with the fields `score` and, with `tiebreak: "seconds"`,
`time`.

## Several scores

When a game has more than one score, list them as `fields`, and say in `rank_by` which ones rank
players. The first field in `rank_by` decides; the next ones break ties. **Each field has its own
order**, so a game can rank by a higher accuracy first and then by a lower time, or by fewer misses
and then more points.

```json
"scoring": {
  "fields": [
    { "key": "acc",   "label": "Accuracy", "unit": "%",   "order": "desc", "min": 0, "max": 100, "total": "average" },
    { "key": "wpm",   "label": "Speed",    "unit": "wpm", "order": "desc", "total": "average" },
    { "key": "time",  "label": "Time",     "source": "time", "total": "sum" },
    { "key": "plays", "label": "Times played", "source": "plays" }
  ],
  "rank_by": ["acc", "wpm"],
  "counts": "best"
}
```

Each field:

| Field | Meaning |
|---|---|
| `key` | Its name: lower-case letters, digits or `_`. |
| `label`, `unit`, `decimals` | How it's shown. A `unit` of `%` is shown as `97%`. |
| `seconds` | `true` shows the value as a time, like `1:05`. |
| `order` | `"asc"` (lower is better) or `"desc"` (higher is better). Fields in `rank_by` need one. |
| `min`, `max` | Values outside these are refused. |
| `source` | Where the value comes from: `"game"` (the game reports it; the default), `"time"` (how long the round took: measured by the server on the games page) or `"plays"` (how many rounds the learner has finished). |
| `total` | How values add up, for `counts: "total"` and for the total scoreboard: `"sum"` (the default), `"average"`, `"min"`, `"max"`, `"best"` (the value from the best result) or `"latest"`. |

`rank_by` lists one to four fields. The first must be one the game reports.

A game reports its values when it finishes: `KG.finish({ values: { acc: 97, wpm: 41 } })`. Every
field in `rank_by` that the game reports is needed; the others are optional.

## Which attempt counts

`counts` is the default; coaches can change it for free play and for each challenge.

| `counts` | The learner's result is |
|---|---|
| `"first"` | their first attempt. Later attempts are practice. |
| `"best"` | their best attempt, by `rank_by`. All its values come from that one attempt. |
| `"latest"` | their latest finished attempt. |
| `"total"` | every attempt added up, each field by its `total` rule. For points that build up, like a daily word game. |

## Levels and lessons: one scoreboard each

A game with levels (or lessons, or maps) can give each its own scoreboard, and one more for the
whole game:

```json
"scoring": {
  "fields": [ ... ],
  "rank_by": ["acc", "wpm"],
  "boards": {
    "label": "Lesson",
    "names": { "en-01": "Lesson 1", "en-02": "Lesson 2" },
    "name_rules": [ { "suffix": "_flags", "name": "{name}: flags" } ],
    "total": { "label": "All lessons", "count_label": "Lessons passed" }
  }
}
```

- Each level is a **board**, named by its id. On the games page, the game names the board when it
  starts an attempt: `KG.start({ board: "en-02" })`. In a channel, the boards are the keys in the
  game's saved data.
- `names` and `name_rules` give boards their names. A rule matches ids with a `prefix` and/or
  `suffix`, and `{name}` is the `names` entry for the rest of the id (or the rest itself).
- `after_resource: true` (channels) names boards after the Kolibri resource they were played in.
- `total` adds a **total scoreboard**. Each learner's result on every board is added up, field by
  field, with each field's `total` rule, and a count of boards comes first (named by
  `count_label`). It's ranked by that count, then by `rank_by`, unless `total.rank_by` says
  otherwise (for example `["acc", "boards"]`).

## Scores in Kolibri channels

A Scored Game in a channel saves its scores in SCORM `cmi.suspend_data`, and the games page reads
them from there. `saved_data` says how:

- **Left out**, for games made with EduGame Kit: each board is a key holding a list of the fields'
  values in `fields` order. An EduGame Kit game without levels saves one board, `main`, and each
  Kolibri resource of it gets its own scoreboard, named after the resource. Keys starting with `_`
  are the game's own save, never boards.
- **`{"in": "scorm"}`**, for games that save their own way: each field says where its value is,
  with `from`: a name in an object (`"acc"`), or a position in a list (`0`). `only_if` skips
  entries that don't match, for example `{"from": "done", "equals": 1}` for lessons not passed yet.

See [CHANNEL_GAMES.md](CHANNEL_GAMES.md) for the rest, and
[examples/channel-games](../examples/channel-games) for Lessons In Typing (accuracy then speed,
a board for each lesson) and Studies In Geography (accuracy then time, a board for each map and
mode).

Don't send scores to Kolibri itself (`cmi.core.score.raw`): Kolibri reads a SCORM score as how
much of a resource is done, so a resource would only count as done at 100. Set only the status:
`incomplete`, then `passed` (Kolibri ignores `completed`). EduGame Kit does this for you.
