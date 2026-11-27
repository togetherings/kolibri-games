"""
Rooms for Smoke Signals: players meeting, starting a game, handing in their
prompts, drawings and guesses, and seeing every chain at the end. The rules
are in smokesignals.py; this module keeps rooms in the store. No Django
imports.

Every request from a game goes through ``SmokeRooms.move``. Games ask for
news every couple of seconds ("poll"); each request also moves the game on
when a step is complete or its time has run out, so no background work is
needed.

Several learners change the same room at once, so a room has a version
number: a change is only saved if nobody else saved the room since it was
read (otherwise it's read again and the change retried). Hand-ins are their
own records, one per chain and step, so two hand-ins never overwrite each
other and the room itself stays small.
"""
import random
import threading
from collections import OrderedDict
from datetime import timedelta

from . import smokesignals as ss
from .smokesignals import SmokeError

#: A waiting room nobody has touched for this long is closed.
LOBBY_IDLE = timedelta(hours=2)
#: A game nobody has touched for this long is closed.
PLAYING_IDLE = timedelta(hours=6)
#: Finished games are shown to their players for this long after the last change.
DONE_SHOWN = timedelta(hours=12)
#: Rooms (with their drawings) are deleted this long after their last change.
KEEP_ROOMS = timedelta(days=7)
RETRIES = 8


class SmokeRooms(object):
    def __init__(self, store, now, monotonic, rng=None):
        self.store = store
        self.now = now
        self.monotonic = monotonic
        self.rng = rng or random.Random()
        self._lock = threading.RLock()  # Kolibri serves requests from one process: saves most retries
        self._seen = OrderedDict()  # (room id, user id) -> monotonic time of their last request
        self._words = {}

    # ============================================================ helpers

    def words(self, game, language):
        files = game.manifest.words or {}
        language = language if language in files else game.manifest.language if game.manifest.language in files else None
        if language is None:
            return []
        key = (game.key, game.manifest.version, language)
        if key not in self._words:
            found = game.source.read(files[language])
            self._words[key] = ss.parse_words(found[0].decode("utf-8", "replace")) if found else []
        return self._words[key]

    def _room_words(self, game, room):
        return self.words(game, room.settings.get("language"))

    def _deadline(self, room_settings, step_kind):
        speed = ss.SPEEDS.get(room_settings.get("speed"))
        if not speed:
            return None
        return self.now() + timedelta(seconds=speed[step_kind])

    def _touch(self, room, user_id):
        self._seen[(room.id, user_id)] = self.monotonic()
        self._seen.move_to_end((room.id, user_id))
        while len(self._seen) > 5000:
            self._seen.popitem(last=False)

    def _away(self, room, user_id):
        seen = self._seen.get((room.id, user_id))
        return seen is None or self.monotonic() - seen > ss.AWAY_SECONDS

    @staticmethod
    def _as_dict(room):
        return {
            "status": room.status, "host_id": room.host_id, "players": [dict(p) for p in room.players],
            "settings": dict(room.settings), "step": room.step, "steps": room.steps,
            "deadline": room.deadline,
        }

    def _change(self, room, fn):
        """Apply ``fn(dict) -> dict`` to the room and save it, retrying if someone else saved it first."""
        with self._lock:
            for _ in range(RETRIES):
                d = fn(self._as_dict(room))
                for k in ("status", "host_id", "players", "settings", "step", "steps", "deadline"):
                    setattr(room, k, d[k])
                room.updated_at = self.now()
                if self.store.room_save(room):
                    return room
                room = self.store.room_get(room.id)
                if room is None:
                    raise SmokeError("That game doesn't exist any more.", "no_room", 404)
        raise SmokeError("Lots of players are busy at once. Try again.", "busy", 503)

    def _expire(self, room):
        """Close rooms nobody uses any more. Returns the room's status."""
        idle = self.now() - (room.updated_at or room.created_at)
        if (room.status == ss.LOBBY and idle > LOBBY_IDLE) or (room.status == ss.PLAYING and idle > PLAYING_IDLE):
            self._change(room, lambda d: dict(d, status=ss.CLOSED))
        return room.status

    def rooms(self, game, player, challenge_id, statuses=ss.ACTIVE):
        found = self.store.rooms(game.key, player.facility_id, challenge_id, list(statuses))
        return [r for r in found if r.status in statuses and self._expire(r) in statuses]

    def my_room(self, game, player, challenge_id):
        """The room the player is in: waiting, playing, or a game that finished recently."""
        mine = []
        for r in self.rooms(game, player, challenge_id, ss.ACTIVE + (ss.DONE,)):
            if ss.in_room(self._as_dict(r), player.id):
                if r.status == ss.DONE and self.now() - (r.updated_at or r.created_at) > DONE_SHOWN:
                    continue
                mine.append(r)
        return max(mine, key=lambda r: r.id) if mine else None

    # ============================================================ moving on

    def tick(self, game, room):
        """Move the game on: next step when everyone has handed in; fill in for anyone out of time or gone."""
        for _ in range(4 * ss.MAX_PLAYERS * (1 + 2 * ss.MAX_ROUNDS)):
            if room.status != ss.PLAYING:
                return room
            handed_in = self.store.room_handed_in(room.id, room.step)
            n = len(room.players)
            missing = [c for c in range(n) if c not in handed_in]
            if not missing:
                step = room.step

                def advance(d, step=step):
                    if d["step"] != step:
                        return d  # someone else moved it on
                    d["step"] += 1
                    if d["step"] >= d["steps"]:
                        d["status"], d["deadline"] = ss.DONE, None
                    else:
                        d["deadline"] = self._deadline(d["settings"], ss.kind(d["step"]))
                    return d

                room = self._change(room, advance)
                continue
            out_of_time = room.deadline is not None and self.now() > room.deadline + timedelta(seconds=ss.GRACE_SECONDS)
            fill = [c for c in missing if out_of_time or room.players[ss.holder(c, room.step, n)]["left"]]
            if not fill:
                return room
            self._fill(game, room, fill)
        return room

    def _fill(self, game, room, chains):
        n = len(room.players)
        words = self._room_words(game, room)
        step_kind = ss.kind(room.step)
        for c in chains:
            self.store.room_entry_add(
                room_id=room.id, chain=c, step=room.step, user_id=room.players[ss.holder(c, room.step, n)]["id"],
                kind=step_kind, content=ss.placeholder(step_kind, words, self.rng), auto=True, created_at=self.now(),
            )

    # ============================================================ what players see

    def lobby(self, game, player, challenge_id, settings, notice=None):
        rooms = []
        for r in self.rooms(game, player, challenge_id, (ss.LOBBY,)):
            host = [p["name"] for p in r.players if p["id"] == r.host_id]
            rooms.append({"code": r.code, "host": host[0] if host else "", "players": len(r.players)})
        rooms.sort(key=lambda r: r["code"])
        return {
            "room": None,
            "rooms": rooms,
            "can_host": settings.get("hosts") != "coaches" or player.is_coach,
            "notice": notice,
        }

    def view(self, game, player, room, have=None, notice=None):
        """What one player sees of their room."""
        n = len(room.players)
        seat = ss.seat_of(self._as_dict(room), player.id)
        handed_in = self.store.room_handed_in(room.id, room.step) if room.status == ss.PLAYING else set()
        players = []
        for i, p in enumerate(room.players):
            done = room.status == ss.PLAYING and ss.chain_of(i, room.step, n) in handed_in
            players.append({
                "name": p["name"], "me": i == seat, "host": p["id"] == room.host_id, "left": p["left"],
                "away": not p["left"] and p["id"] != player.id and self._away(room, p["id"]), "done": done,
            })
        out = {
            "room": {
                "code": room.code,
                "status": room.status,
                "host": room.host_id == player.id,
                "players": players,
                "settings": {k: room.settings.get(k) for k in ("speed", "rounds", "prompts")},
                "step": room.step,
                "steps": room.steps,
                "rounds": (room.steps - 1) // 2 if room.steps else ss.rounds_for(n, room.settings.get("rounds")),
                "min_players": ss.MIN_PLAYERS,
                "max_players": ss.MAX_PLAYERS,
            },
            "task": None,
            "notice": notice,
        }
        if room.status == ss.PLAYING and seat is not None:
            chain = ss.chain_of(seat, room.step, n)
            key = "%d-%d" % (room.step, chain)
            step_kind = ss.kind(room.step)
            task = {
                "key": key,
                "kind": step_kind,
                "step": room.step,
                "done": chain in handed_in,
                "seconds_left": None if room.deadline is None else max(0, round((room.deadline - self.now()).total_seconds())),
                "waiting": [room.players[ss.holder(c, room.step, n)]["name"] for c in range(n)
                            if c not in handed_in and not room.players[ss.holder(c, room.step, n)]["left"]],
            }
            if not task["done"] and have != key:
                if step_kind == ss.PROMPT:
                    task["typing"] = room.settings.get("prompts") != "list"
                    task["suggestions"] = ss.suggestions(self._room_words(game, room), 3, self.rng)
                else:
                    entries = self._entries(room.id, chain=chain)
                    task.update(ss.given(entries, chain, room.step))
            out["task"] = task
        return out

    def _entries(self, room_id, chain=None):
        return [{"chain": e.chain, "step": e.step, "user_id": e.user_id, "content": e.content, "auto": e.auto}
                for e in self.store.room_entries(room_id, chain=chain)]

    def chains(self, room, player):
        """The list of chains at the end: whose it is and how it started."""
        seat = ss.seat_of(self._as_dict(room), player.id)
        starts = {e["chain"]: e["content"].get("text", "") for e in self._entries_at(room.id, 0)}
        return {"chains": [
            {"index": i, "owner": p["name"], "mine": i == seat, "prompt": starts.get(i, "")}
            for i, p in enumerate(room.players)
        ]}

    def _entries_at(self, room_id, step):
        return [{"chain": e.chain, "content": e.content} for e in self.store.room_entries(room_id, step=step)]

    def chain(self, room, index):
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(room.players):
            raise SmokeError("There's no chain with that number.")
        names = {p["id"]: p["name"] for p in room.players}
        shown = []
        for e in sorted(self._entries(room.id, chain=index), key=lambda e: e["step"]):
            if e["step"] >= room.steps:
                continue
            item = {"step": e["step"], "kind": ss.kind(e["step"]), "by": names.get(e["user_id"], "?"), "auto": bool(e["auto"])}
            item.update(e["content"])
            shown.append(item)
        return {"index": index, "owner": room.players[index]["name"], "entries": shown}

    # ============================================================ requests

    def move(self, game, player, challenge_id, settings, kind, data):
        """(reply for the game, what to keep in the attempt's move list or None)."""
        data = data if isinstance(data, dict) else {}
        room = self.my_room(game, player, challenge_id)
        if room is not None:
            self._touch(room, player.id)
            room = self.tick(game, room)

        if kind in ("poll", "lobby"):
            if room is None:
                return self.lobby(game, player, challenge_id, settings), None
            return self.view(game, player, room, have=data.get("have")), None

        if kind == "create":
            if room is not None:
                return self.view(game, player, room), None
            if settings.get("hosts") == "coaches" and not player.is_coach:
                raise SmokeError("Only coaches can start a new game here. Join one with its code.", "forbidden", 403)
            room = self._create(game, player, challenge_id, settings, data)
            return self.view(game, player, room), {"code": room.code}

        if kind == "join":
            code = ss.clean_code(data.get("code"))
            if room is not None and room.code == code:
                return self.view(game, player, room), None
            if room is not None and room.status in ss.ACTIVE:
                raise SmokeError("You're already in game %s. Leave it first." % room.code, "in_room", 409)
            found = [r for r in self.rooms(game, player, challenge_id, ss.ACTIVE) if r.code == code]
            if not found:
                raise SmokeError("There's no game with the code %s here." % (code or "you typed"), "no_room", 404)
            me = {"id": player.id, "name": player.name}
            room = self._change(found[0], lambda d: ss.join(d, me))
            self._touch(room, player.id)
            return self.view(game, player, room), {"code": room.code}

        if room is None:
            if kind == "leave":
                return self.lobby(game, player, challenge_id, settings), None
            raise SmokeError("You're not in a game. Start one or join one.", "no_room", 409)

        if kind == "leave":
            self._change(room, lambda d: ss.leave(d, player.id))
            return self.lobby(game, player, challenge_id, settings), {"code": room.code}

        if kind == "remove":
            seat = data.get("seat")
            name = room.players[seat]["name"] if isinstance(seat, int) and 0 <= seat < len(room.players) else None
            room = self._change(room, lambda d: ss.remove(d, player.id, seat))
            return self.view(game, player, self.tick(game, room)), {"removed": name}

        if kind == "begin":
            room = self._change(room, lambda d: ss.begin(d, player.id, self.now(), lambda k: self._deadline(d["settings"], k)))
            return self.view(game, player, room), {"players": len(room.players)}

        if kind == "suggest":
            return {"suggestions": ss.suggestions(self._room_words(game, room), 3, self.rng)}, None

        if kind == "submit":
            logged = self._submit(game, player, room, data)
            room = self.tick(game, self.store.room_get(room.id))
            return self.view(game, player, room), logged

        if kind == "skip":
            self._host_only(room, player, "stop waiting")
            if room.status == ss.PLAYING:
                handed_in = self.store.room_handed_in(room.id, room.step)
                self._fill(game, room, [c for c in range(len(room.players)) if c not in handed_in])
                room = self.tick(game, room)
            return self.view(game, player, room), {"step": room.step}

        if kind == "end":
            self._host_only(room, player, "end the game")

            def end(d):
                if d["status"] == ss.PLAYING and d["step"] > 0:
                    d["status"], d["steps"], d["deadline"] = ss.DONE, d["step"], None  # show the steps already done
                elif d["status"] in ss.ACTIVE:
                    d["status"] = ss.CLOSED
                return d

            room = self._change(room, end)
            if room.status == ss.CLOSED:
                return self.lobby(game, player, challenge_id, settings, notice="The game was ended."), {"ended": True}
            return self.view(game, player, room), {"ended": True}

        if kind in ("chains", "chain"):
            if room.status != ss.DONE:
                raise SmokeError("The chains are shown when the game is over.", "not_finished", 409)
            if kind == "chains":
                return self.chains(room, player), None
            return self.chain(room, data.get("index")), None

        raise SmokeError("Smoke Signals doesn't understand '%s'." % kind)

    def _host_only(self, room, player, what):
        if room.host_id != player.id:
            raise SmokeError("Only the host can %s." % what, "forbidden", 403)

    def _create(self, game, player, challenge_id, settings, data):
        now = self.now()
        self.store.rooms_delete_before(now - KEEP_ROOMS)
        values = dict(settings)
        for key in ("speed", "rounds"):  # the host can choose these for their game
            if data.get(key) is not None:
                values[key] = data[key]
        language = data.get("language")
        values["language"] = language if language in (game.manifest.words or {}) else game.manifest.language
        room_settings = ss.check_settings(values)
        room_settings["prompts"] = "list" if settings.get("prompts") == "list" else "type"  # coaches decide this one
        state = ss.new_room({"id": player.id, "name": player.name}, room_settings)
        code = ss.make_code(self.store.room_codes(player.facility_id), self.rng)
        room = self.store.room_create(
            game_key=game.key, facility_id=player.facility_id, challenge_id=challenge_id, code=code,
            status=state["status"], host_id=state["host_id"], players=state["players"], settings=state["settings"],
            step=0, steps=0, deadline=None, created_at=now, updated_at=now, version=1,
        )
        self._touch(room, player.id)
        return room

    def _submit(self, game, player, room, data):
        if room.status != ss.PLAYING:
            raise SmokeError("The game isn't being played right now.", "not_playing", 409)
        n = len(room.players)
        seat = ss.seat_of(self._as_dict(room), player.id)
        if seat is None or room.players[seat]["left"]:
            raise SmokeError("You're not playing in this game.", "forbidden", 403)
        if data.get("step") != room.step:
            raise SmokeError("That step is over: the game has moved on.", "too_late", 409)
        chain = ss.chain_of(seat, room.step, n)
        step_kind = ss.kind(room.step)
        if step_kind == ss.DRAW:
            content = ss.clean_drawing(data.get("drawing"))
            logged = {"step": room.step, "kind": step_kind, "lines": len(content["strokes"])}
        else:
            content = {"text": ss.clean_text(data.get("text"))}
            if step_kind == ss.PROMPT and room.settings.get("prompts") == "list" \
                    and content["text"] not in self._room_words(game, room):
                raise SmokeError("Choose one of the ideas.")
            logged = {"step": room.step, "kind": step_kind, "text": content["text"]}
        added = self.store.room_entry_add(
            room_id=room.id, chain=chain, step=room.step, user_id=player.id, kind=step_kind,
            content=content, auto=False, created_at=self.now(),
        )
        if not added:
            raise SmokeError("You've already handed this one in (or the time ran out).", "too_late", 409)
        return logged

    def leave_all(self, game, player, challenge_id):
        """When a player finishes or gives up: leave their room, if they're in one. Returns what they made."""
        room = self.my_room(game, player, challenge_id)
        if room is None:
            return {}
        seat = ss.seat_of(self._as_dict(room), player.id)
        detail = {"code": room.code, "players": len(room.players), "status": room.status}
        if room.status == ss.DONE and seat is not None:
            detail["chain"] = [e.get("text") if "text" in e else "(drawing)" for e in self.chain(room, seat)["entries"]]
        self._change(room, lambda d: ss.leave(d, player.id))
        return detail
