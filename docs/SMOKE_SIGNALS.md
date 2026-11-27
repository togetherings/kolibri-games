# Smoke Signals

**Sketches Morph Oddly, Kindling Excitement.** A drawing and guessing game for a group, in the
style of Telestrations. Everyone writes something to draw. The next player draws it, the player
after them guesses what the drawing shows, the next draws that guess, and so on. At the end,
everyone sees every chain, from the first words to the last guess, and how far each idea drifted.

It needs three or more players on the same Kolibri server, each on their own device.

## Setting it up (administrators)

On the games page, open **Setup**, choose `org.togetherings.smoke-signals-<version>.zip`
(attached to each [release](https://github.com/togetherings/kolibri-games/releases)) and click
**Install**. It needs no other files.

## Playing

1. **Someone starts a game** with **Start a new game**. They're the *host*. They get a four-letter
   code, like `N7AY`.
2. **Everyone else joins:** waiting games are listed, or players type the code.
3. **The host presses Start the game** when everyone's there (at least 3, at most 12).
4. **Everyone writes a prompt**, or picks one of the game's ideas.
5. **Prompts are passed on.** Each player draws the words they get, then guesses the drawing they
   get, and so on. Each player only sees the step just before theirs.
6. **At the end, everyone sees every chain.** They can step through a chain one entry at a time,
   or show it all, and save it as a picture (with **Save as a picture**).

**Turn order.** With an odd number of players, each chain moves one player along at every step.
With an even number, the owner draws their own prompt first, then it moves on, so every chain
still ends on a guess. Every chain has at least as many *rounds* (a drawing and a guess) as the
setting asks for, and bigger groups get more, so each chain goes all the way round. With a small
group and several rounds, chains go round more than once, so players may see their own chain
again.

**Time.** Each step ends when everyone has handed in, or when its time runs out. When time runs
out, the game hands in what's on the player's paper or in their box. If there's nothing (a tablet
went to sleep, say), the server hands in for them: a random idea for a prompt, or an empty drawing
or guess. The next player then works from the last real words or drawing in the chain, so one
missed turn never stops the game.

| Speed | Prompt | Drawing | Guess |
|---|---|---|---|
| Quick | 30 seconds | 60 seconds | 30 seconds |
| Normal (default) | 45 seconds | 90 seconds | 45 seconds |
| Relaxed | 60 seconds | 2 minutes | 60 seconds |
| No timer | | | |

With no timer, the host sees who the game is waiting for and can press **Stop waiting**.

**The host** can remove players in the waiting room, stop waiting, and end the game for
everyone (the chains so far are then shown). If the host leaves, the next player becomes the host.
Players who leave during a game are skipped.

## Settings (coaches)

On the games page, click **Settings** on the Smoke Signals card:

- **Time for each turn** and **Rounds**: the starting choices for new games. Hosts can change
  them for their own game.
- **First prompts**: players write their own or pick an idea, or **pick from the game's ideas
  only**. Hosts can't change this one.
- **Who can start a game**: anyone, or **coaches only** (learners then join with a code).

There's no chat, and nothing to type except prompts and guesses.

Smoke Signals has no score, so it has no scoreboard or challenges. Coaches can't see results on
the games page yet: each player's attempt keeps their moves (prompts and guesses, not drawings)
and, when they finish, their own chain's words.

## How it stays light on a Raspberry Pi

- Drawings are kept as lines (colour, brush and points), not pictures: a few kilobytes each, at
  most 64 KB. They're drawn again on each screen, so they're sharp everywhere.
- Each device asks for news every two seconds, and only gets the drawing or words it works from
  once per step.
- Rooms are closed when nobody uses them (2 hours for a waiting room, 6 for a game) and deleted,
  with their drawings, 7 days after their last change.

## For game makers: the `smoke-signals` service

The manifest asks for the service and names a word list for each language (ideas for first
prompts, one per line; `#` starts a comment):

```json
"service": "smoke-signals",
"words": {"en": "words/en.txt"},
"settings": [
  {"key": "speed", "type": "choice", "default": "normal", "choices": [...quick, normal, relaxed, none]},
  {"key": "rounds", "type": "integer", "default": 3, "min": 1, "max": 6},
  {"key": "prompts", "type": "choice", "default": "type", "choices": [...type, list]},
  {"key": "hosts", "type": "choice", "default": "anyone", "choices": [...anyone, coaches]}
]
```

`KG.start()` returns the player's room, or the waiting games, in `start.public`. Everything else
is a move, and each reply is the player's new view:

```js
await KG.move("create", { speed: "quick", rounds: 3, language: "en" });  // the player becomes the host
await KG.move("join", { code: "N7AY" });
await KG.move("poll", { have: task.key });   // news; "have" skips what the page already has
await KG.move("submit", { step, text: "a cat on a bike" });                 // a prompt or a guess
await KG.move("submit", { step, drawing: { strokes: [[colour, size, x, y, x, y]] } });
await KG.move("suggest");                    // three more ideas: {suggestions}
await KG.move("begin" | "skip" | "end");     // the host's buttons
await KG.move("remove", { seat: 2 });        // the host removes a player (by their place in the list)
await KG.move("leave");
await KG.move("chains");                     // at the end: {chains: [{index, owner, mine, prompt}]}
await KG.move("chain", { index: 1 });        // {owner, entries: [{kind, by, auto, text | strokes}]}
await KG.finish({});                         // leaves the room; no score
```

A view is `{room, task, notice}`, or `{room: null, rooms, can_host, notice}` outside a room.
`room` has `code`, `status` (`lobby`, `playing` or `done`), `host` (whether this player is the host),
`players` (`name`, `me`, `host`, `away`, `left`, `done`), `step`, `steps` and `rounds`. `task`
is this player's job at the current step: `key`, `kind` (`prompt`, `draw` or `guess`), `step`,
`done`, `seconds_left` (or null with no timer), `waiting` (names), and what they work from:
`suggestions` and `typing` for a prompt, `text` to draw, or `drawing` to guess (null if nobody
drew).

Drawings are 800 × 600 drawing units. A stroke is `[colour, size, x, y, x, y, ...]`, with a colour
from 0 to 8 (the last is the eraser) and a size from 0 to 2, at most 600 strokes and 6000 points.
