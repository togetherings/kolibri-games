"""
The rules of Smoke Signals (Sketches Morph Oddly, Kindling Excitement): a
drawing and guessing game for several players at once, in the style of
Telestrations. No Django imports.

Players meet in a *room*. One of them, the host, starts the game. Then:

* everyone writes a prompt: the start of their own *chain*;
* each chain is passed on: the next player draws the prompt, the one after
  guesses what the drawing shows, the next draws that guess, and so on;
* at the end everyone sees every chain, from the prompt to the last guess,
  and can save a chain as a picture.

Turn order (``holder``): with an odd number of players, each chain moves one
player along at every step, so it never reaches its owner again in one lap.
With an even number, the owner draws their own prompt first, then it moves
on, so every chain still ends on a guess. A game has at least ``rounds``
rounds (a drawing and a guess); with few players the chains go round more
than once, so players may see their own chain again.

A step ends when every player has handed in, or when its time runs out:
the server then fills in what's missing (a random word for a prompt, an
empty drawing or guess), so a sleeping tablet never stops the game. Players
who leave are skipped the same way. Without a timer, the host can stop
waiting.

The room's state is plain data (a dict per room, a list of entries), kept
by the store; service.py does the reading, saving and retrying.
"""
import random
import re


PROMPT, DRAW, GUESS = "prompt", "draw", "guess"
MIN_PLAYERS = 3
MAX_PLAYERS = 12
MAX_ROUNDS = 6
MAX_TEXT = 60
#: Seconds for each kind of step, by the "speed" setting. None: no timer.
SPEEDS = {
    "quick": {PROMPT: 30, DRAW: 60, GUESS: 30},
    "normal": {PROMPT: 45, DRAW: 90, GUESS: 45},
    "relaxed": {PROMPT: 60, DRAW: 120, GUESS: 60},
    "none": None,
}
#: Extra seconds after a step's time runs out, for the last hand-ins to arrive.
GRACE_SECONDS = 5
#: A player who hasn't asked for news for this long is shown as away.
AWAY_SECONDS = 20

#: The drawing area, in drawing units (4:3, so it looks the same on every screen).
WIDTH, HEIGHT = 800, 600
#: Colours a drawing can use (the last one is the eraser: the paper's white).
PALETTE = ["#1f1b16", "#d62828", "#f77f00", "#fcbf49", "#2a9d8f", "#1d4ed8", "#7b2cbf", "#8d5524", "#ffffff"]
#: Brush widths, in drawing units.
SIZES = [4, 10, 24]
MAX_STROKES = 600
MAX_POINTS = 6000
#: The largest hand-in (a drawing) in JSON characters.
MAX_SUBMIT_BYTES = 65536

#: Room codes: letters and digits that are hard to mix up.
CODE_CHARS = "ACDEFHJKMNPRTWXY3479"
CODE_LENGTH = 4

LOBBY, PLAYING, DONE, CLOSED = "lobby", "playing", "done", "closed"
ACTIVE = (LOBBY, PLAYING)


class SmokeError(Exception):
    def __init__(self, message, code="bad_move", status=400):
        super(SmokeError, self).__init__(message)
        self.code = code
        self.status = status


# --------------------------------------------------------------- turn order


def rounds_for(players, rounds):
    """How many rounds (a drawing and a guess) each chain gets."""
    return max(players // 2, max(1, min(MAX_ROUNDS, int(rounds or 1))))


def total_steps(players, rounds):
    """Steps in a game: the prompt, then a drawing and a guess for each round."""
    return 1 + 2 * rounds_for(players, rounds)


def kind(step):
    if step == 0:
        return PROMPT
    return DRAW if step % 2 else GUESS


def holder(chain, step, players):
    """The player (by seat) who works on ``chain`` at ``step``."""
    if step == 0:
        return chain
    if players % 2 == 0:
        return (chain + step - 1) % players  # even: the owner draws their own prompt first
    return (chain + step) % players


def chain_of(seat, step, players):
    """The chain a player works on at ``step`` (the opposite of holder)."""
    if step == 0:
        return seat
    if players % 2 == 0:
        return (seat - step + 1) % players
    return (seat - step) % players


def make_code(taken, rng=random):
    for _ in range(200):
        code = "".join(rng.choice(CODE_CHARS) for _ in range(CODE_LENGTH))
        if code not in taken:
            return code
    raise SmokeError("Too many games are being played. Try again in a moment.", "busy", 503)


def clean_code(text):
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())[:CODE_LENGTH]


# --------------------------------------------------------------- hand-ins


def clean_text(text):
    """A prompt or guess: one line, spaces tidied, at most MAX_TEXT characters."""
    if not isinstance(text, str):
        raise SmokeError("Write a few words.")
    text = "".join(ch for ch in " ".join(text.split()) if ch.isprintable())
    if not text:
        raise SmokeError("Write a few words.")
    if len(text) > MAX_TEXT:
        raise SmokeError("That's too long: use at most %d characters." % MAX_TEXT)
    return text


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def clean_drawing(drawing):
    """A drawing: {"strokes": [[colour, size, x, y, x, y, ...], ...]} in drawing units."""
    if not isinstance(drawing, dict) or not isinstance(drawing.get("strokes"), list):
        raise SmokeError("That drawing couldn't be read.")
    strokes = drawing["strokes"]
    if len(strokes) > MAX_STROKES:
        raise SmokeError("That drawing has too many lines. Try fewer, longer lines.")
    points = 0
    for s in strokes:
        if not isinstance(s, list) or len(s) < 4 or len(s) % 2:
            raise SmokeError("That drawing couldn't be read.")
        if not all(_int(v) for v in s):
            raise SmokeError("That drawing couldn't be read.")
        if not 0 <= s[0] < len(PALETTE) or not 0 <= s[1] < len(SIZES):
            raise SmokeError("That drawing uses a colour or brush the game doesn't have.")
        xs, ys = s[2::2], s[3::2]
        if min(xs) < 0 or max(xs) > WIDTH or min(ys) < 0 or max(ys) > HEIGHT:
            raise SmokeError("That drawing goes off the paper.")
        points += len(xs)
    if points > MAX_POINTS:
        raise SmokeError("That drawing is too detailed. Try fewer, longer lines.")
    return {"strokes": strokes}


def parse_words(text):
    """A word list: one prompt per line; blank lines and lines starting with # are skipped."""
    words = []
    for line in (text or "").splitlines():
        line = " ".join(line.split())
        if line and not line.startswith("#") and len(line) <= MAX_TEXT:
            words.append(line)
    return words


# --------------------------------------------------------------- the room


def new_room(host, settings):
    """The state of a new room (service.py adds ids, the code and times)."""
    return {
        "status": LOBBY,
        "host_id": host["id"],
        "players": [{"id": host["id"], "name": host["name"], "left": False}],
        "settings": settings,
        "step": 0,
        "steps": 0,
    }


def seat_of(room, user_id):
    for i, p in enumerate(room["players"]):
        if p["id"] == user_id:
            return i
    return None


def in_room(room, user_id):
    seat = seat_of(room, user_id)
    return seat is not None and not room["players"][seat]["left"]


def join(room, player):
    if room["status"] != LOBBY:
        raise SmokeError("That game has already started.", "started", 409)
    seat = seat_of(room, player["id"])
    if seat is not None:
        room["players"][seat]["left"] = False
        return room
    if len(room["players"]) >= MAX_PLAYERS:
        raise SmokeError("That game is full (%d players)." % MAX_PLAYERS, "full", 409)
    room["players"].append({"id": player["id"], "name": player["name"], "left": False})
    return room


def _next_host(room):
    for p in room["players"]:
        if not p["left"]:
            return p["id"]
    return None


def leave(room, user_id):
    """A player leaves. In the waiting room they're taken off the list; in a game their turns are skipped."""
    seat = seat_of(room, user_id)
    if seat is None:
        return room
    if room["status"] == LOBBY:
        del room["players"][seat]
    else:
        room["players"][seat]["left"] = True
    if room["host_id"] == user_id:
        room["host_id"] = _next_host(room)
    if room["status"] == LOBBY and not room["players"]:
        room["status"] = CLOSED
    elif room["status"] == PLAYING and room["host_id"] is None:
        room["status"] = CLOSED  # everyone left
    return room


def remove(room, host_id, seat):
    if room["host_id"] != host_id:
        raise SmokeError("Only the host can remove players.", "forbidden", 403)
    if not _int(seat) or not 0 <= seat < len(room["players"]) or room["players"][seat]["id"] == host_id:
        raise SmokeError("Choose someone else in the game.")
    return leave(room, room["players"][seat]["id"])


def begin(room, host_id, now, seconds_for):
    if room["host_id"] != host_id:
        raise SmokeError("Only the host can start the game.", "forbidden", 403)
    if room["status"] != LOBBY:
        raise SmokeError("The game has already started.", "started", 409)
    n = len(room["players"])
    if n < MIN_PLAYERS:
        raise SmokeError("Smoke Signals needs at least %d players." % MIN_PLAYERS, "too_few", 409)
    room["status"] = PLAYING
    room["step"] = 0
    room["steps"] = total_steps(n, room["settings"].get("rounds"))
    room["deadline"] = seconds_for(PROMPT)
    return room


def missing(room, entries):
    """Chains with nothing handed in yet for the current step."""
    have = {e["chain"] for e in entries if e["step"] == room["step"]}
    return [c for c in range(len(room["players"])) if c not in have]


def placeholder(step_kind, words, rng=random):
    """What the server hands in for someone who didn't."""
    if step_kind == PROMPT:
        return {"text": rng.choice(words) if words else "a smiling sun"}
    if step_kind == DRAW:
        return {"strokes": []}
    return {"text": ""}


def given(entries, chain, step):
    """What the player at ``step`` of ``chain`` works from.

    Drawing: the latest words in the chain (an empty guess is skipped, so the
    chain carries on from the last real words). Guessing: the latest drawing
    with something on it, or nothing.
    """
    earlier = sorted([e for e in entries if e["chain"] == chain and e["step"] < step], key=lambda e: -e["step"])
    if kind(step) == DRAW:
        for e in earlier:
            if kind(e["step"]) != DRAW and e["content"].get("text"):
                return {"text": e["content"]["text"]}
        return {"text": ""}
    if kind(step) == GUESS:
        for e in earlier:
            if kind(e["step"]) == DRAW and e["content"].get("strokes"):
                return {"drawing": e["content"]}
        return {"drawing": None}
    return {}


def suggestions(words, count=3, rng=random):
    return rng.sample(words, min(count, len(words))) if words else []


def check_settings(values):
    """The room's settings from the game's settings (coaches) and the host's choices."""
    speed = values.get("speed") if values.get("speed") in SPEEDS else "normal"
    try:
        rounds = max(1, min(MAX_ROUNDS, int(values.get("rounds") or 3)))
    except (TypeError, ValueError):
        rounds = 3
    return {
        "speed": speed,
        "rounds": rounds,
        "prompts": "list" if values.get("prompts") == "list" else "type",
        "language": values.get("language") or "en",
    }


