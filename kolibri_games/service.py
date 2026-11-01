"""
The rules of play: free play and challenges, attempts, scores, scoreboards,
coach results, article lists, and the Wikipedia race.

This module doesn't touch Django. It talks to a *store* (see ``Store``
below), so the same rules run inside Kolibri (``store_django.py``) and in
tests or the preview server (``MemoryStore``).

Words used here:

* free play: playing a Free-play Game whenever you like, with the settings a
  coach chose for the whole facility. Attempts have no challenge.
* challenge: a coach sets up a game for one class, with its own settings and
  open and close dates. Each challenge has its own scoreboard.
* attempt: one play of one game by one learner, in free play or in a challenge.
"""
import json
import threading
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

from . import classroom, photoguess, photos, ranking, wiki, wikirace
from .manifest import clean_settings, merge_settings

MAX_EVENTS = 2000
MAX_EVENT_BYTES = 4096
MAX_DETAIL_BYTES = 16384
MAX_STATE_BYTES = 65536
MAX_LIST_TITLES = 50000
TIME_GRACE_SECONDS = 5
RESUME_HOURS = 12
#: Closed challenges stay on learners' game cards this long.
RECENT_DAYS = 14

FREE_PLAY = None  # the challenge id of free-play attempts


def utcnow():
    return datetime.now(timezone.utc)


class PlatformError(Exception):
    """An error to show the player. ``status`` is the HTTP status to use."""

    def __init__(self, message, code="error", status=400, fields=None):
        super(PlatformError, self).__init__(message)
        self.code = code
        self.status = status
        self.fields = fields


class Player(object):
    """Who is asking.

    ``class_ids``: the classes the person is a learner in.
    ``coach_class_ids``: the classes they can set challenges for, or None for
    every class in the facility (facility coaches and administrators).
    """

    def __init__(self, id, name, facility_id, is_coach=False, is_admin=False, class_ids=(), coach_class_ids=()):
        self.id = id
        self.name = name
        self.facility_id = facility_id
        self.is_coach = is_coach or is_admin
        self.is_admin = is_admin
        self.class_ids = set(class_ids or ())
        self.coach_class_ids = None if coach_class_ids is None else set(coach_class_ids)

    @property
    def role(self):
        return "admin" if self.is_admin else ("coach" if self.is_coach else "learner")

    def can_manage(self, class_id):
        return self.is_coach and (self.coach_class_ids is None or class_id in self.coach_class_ids)


def _size(obj):
    return len(json.dumps(obj, separators=(",", ":")))


def _iso(dt):
    return dt.isoformat() if dt else None


class Store(object):
    """Persistence used by GameService. Records are objects with attributes.

    Attempt: id, game_key, game_id, game_version, facility_id, user_id,
    user_name, challenge_id, number, status, voided, started_at, finished_at,
    seconds, score, and dict/list properties public, state, events, detail.

    Challenge: id, game_key, facility_id, class_id, class_name, title,
    settings (dict), counts, time_limit, status ("auto", "open" or "closed":
    see challenge_state), opens_at, closes_at, created_by_id, best (dict).

    ArticleList: id, facility_id, name, titles (text), updated_at, created_by_id.
    """

    # facility-wide settings of a game (used for free play)
    def settings_get(self, game_key, facility_id):
        raise NotImplementedError

    def settings_set(self, game_key, facility_id, platform, game, by_user_id):
        raise NotImplementedError

    # attempts; challenge_id None means free play
    def attempts(self, game_key, facility_id, challenge_id, user_id=None):
        raise NotImplementedError

    def attempt_get(self, attempt_id):
        raise NotImplementedError

    def attempt_create(self, **fields):
        raise NotImplementedError

    def attempt_save(self, attempt):
        raise NotImplementedError

    def attempts_void(self, game_key, facility_id, challenge_id, user_id):
        raise NotImplementedError

    # saved data for a game
    def state_get(self, game_key, user_id):
        raise NotImplementedError

    def state_set(self, game_key, user_id, data):
        raise NotImplementedError

    # challenges
    def challenges(self, facility_id, game_key=None):
        raise NotImplementedError

    def challenge_get(self, challenge_id):
        raise NotImplementedError

    def challenge_create(self, **fields):
        raise NotImplementedError

    def challenge_save(self, challenge):
        raise NotImplementedError

    def challenge_delete(self, challenge):
        raise NotImplementedError

    def challenge_set_best(self, challenge_id, best):
        """Save a challenge's shortest route (called from a background thread)."""
        raise NotImplementedError

    # article lists
    def article_lists(self, facility_id):
        raise NotImplementedError

    def article_list_get(self, list_id):
        raise NotImplementedError

    def article_list_create(self, **fields):
        raise NotImplementedError

    def article_list_save(self, article_list):
        raise NotImplementedError

    def article_list_delete(self, article_list):
        raise NotImplementedError

    # Classroom Games
    def classroom_saves(self, content_ids, facility_id, user_id=None):
        """Saved data of Classroom Game resources: a list of dicts with
        user_id, user_name, content_id and content_state (Kolibri's saved state)."""
        raise NotImplementedError


def run_in_background(fn):
    """Run slow work (the shortest-route search) without making anyone wait."""
    threading.Thread(target=fn, daemon=True, name="kolibri-games-background").start()


class Context(object):
    """The rules that apply to one attempt: free play, or one challenge."""

    def __init__(self, challenge, counts, time_limit, settings, visibility):
        self.challenge = challenge
        self.challenge_id = challenge.id if challenge is not None else FREE_PLAY
        self.counts = counts
        self.time_limit = time_limit  # seconds, 0 for none
        self.settings = settings
        self.visibility = visibility


class GameService(object):
    def __init__(self, store, now=utcnow, background=run_in_background, monotonic=None):
        self.store = store
        self.now = now
        self.background = background
        # A clock that never jumps (time.monotonic in Kolibri). A Raspberry Pi
        # without a clock battery can jump days ahead when it reaches the
        # internet; game times are measured with this clock so a jump during
        # play doesn't count. Defaults to the normal clock (for tests).
        self.monotonic = monotonic or (lambda: self.now().timestamp())
        self._started = OrderedDict()  # attempt id -> monotonic time it started (this process only)

    # ======================================================== settings

    def settings(self, game, facility_id):
        """(platform values, game values) for free play in this facility, defaults filled in."""
        stored = self.store.settings_get(game.key, facility_id) or {}
        m = game.manifest
        return (
            merge_settings(m.platform_settings_schema(), stored.get("platform")),
            merge_settings(m.settings, stored.get("game")),
        )

    def schema(self, game, facility_id):
        """The settings form. Article list choices are filled in from this facility's lists."""
        fields = []
        for f in game.manifest.settings:
            f = dict(f)
            if f["type"] == "article_list":
                f["choices"] = self.list_choices(game, facility_id)
            elif f["type"] == "photo_map":
                f["choices"] = self.map_choices(game)
            fields.append(f)
        return {"platform": game.manifest.platform_settings_schema(), "game": fields}

    def save_settings(self, game, facility_id, platform, values, by_user_id):
        m = game.manifest
        p_vals, p_err = clean_settings(m.platform_settings_schema(), platform or {})
        g_vals, g_err = clean_settings(m.settings, values or {})
        errors = dict(p_err, **g_err)
        if not errors and m.service == "wikipedia-race":
            # Free play: a blank start and goal means a new random pair each time.
            g_vals, errors = self._check_race_settings(game, facility_id, g_vals, pick_random=False)
        if not errors and m.service == "photo-guess":
            errors = self._check_photo_settings(game, g_vals)
        if errors:
            raise PlatformError(" ".join(errors.values()), "invalid_settings", fields=errors)
        self.store.settings_set(game.key, facility_id, p_vals, g_vals, by_user_id)
        return p_vals, g_vals

    # ======================================================== contexts

    def challenge_state(self, challenge):
        """"upcoming", "open" or "closed".

        A coach's Open and Close buttons always win (``status`` "open" or
        "closed"), because a Raspberry Pi without a clock battery can have the
        wrong time. Set times are only used when no button has been pressed,
        except that a set closing time still closes an opened challenge.
        """
        status = getattr(challenge, "status", "auto") or "auto"
        if status == "closed":
            return "closed"
        now = self.now()
        if challenge.closes_at and now >= challenge.closes_at:
            return "closed"
        if status == "open":
            return "open"
        if challenge.opens_at and now >= challenge.opens_at:
            return "open"
        return "upcoming"

    def _challenge_for(self, game, player, challenge_id):
        c = self.store.challenge_get(challenge_id)
        if c is None or c.game_key != game.key or c.facility_id != player.facility_id:
            raise PlatformError("That challenge doesn't exist.", "not_found", 404)
        if c.class_id not in player.class_ids and not player.can_manage(c.class_id):
            raise PlatformError("That challenge is for another class.", "forbidden", 403)
        return c

    def context(self, game, player, challenge_id=FREE_PLAY):
        platform, values = self.settings(game, player.facility_id)
        visibility = platform.get("scoreboard", "names")
        if challenge_id is FREE_PLAY:
            return Context(None, platform.get("counts", "first"), int(platform.get("time_limit") or 0) * 60, values, visibility)
        c = self._challenge_for(game, player, challenge_id)
        settings = merge_settings(game.manifest.settings, c.settings)
        return Context(c, c.counts, int(c.time_limit or 0) * 60, settings, visibility)

    # ======================================================== Wikipedia race

    def wiki_source(self, game):
        path = game.data_paths().get("wikipedia")
        if not path:
            raise PlatformError(
                "This game needs a Wikipedia file. An administrator can choose one on the Setup page.", "no_data", 409
            )
        try:
            return wiki.open_wiki(path)
        except wiki.WikiError as e:
            raise PlatformError(str(e), "no_data", 409)

    def list_choices(self, game, facility_id):
        name = game.manifest.wikipedia.get("default_list_name") or "The game's own list"
        choices = [{"value": "default", "label": name}, {"value": "all", "label": "Every article in the Wikipedia file"}]
        for row in self.store.article_lists(facility_id):
            choices.append({"value": "list-%d" % row.id, "label": row.name})
        return choices

    def resolved_list(self, game, facility_id, list_value, source):
        """The chosen article list matched against the Wikipedia file (see wiki.resolve_list),
        and its cache key. None instead of a list means every article is allowed."""
        if list_value == "all":
            return None, "all"
        if list_value == "default":
            path = game.manifest.wikipedia.get("default_list")
            if not path:
                return None, "all"
            found = game.source.read(path)
            if found is None:
                raise PlatformError("The game's article list (%s) is missing." % path, "no_list", 409)
            key = ("default", game.key, game.manifest.version)
            titles = wiki.parse_list(found[0].decode("utf-8", "replace"))
        else:
            row = self._article_list(facility_id, list_value)
            key = ("list", row.id, _iso(row.updated_at))
            titles = wiki.parse_list(row.titles)
        return wiki.resolve_list(source, titles, key), key

    def _article_list(self, facility_id, list_value):
        try:
            row = self.store.article_list_get(int(str(list_value).split("-", 1)[1]))
        except (IndexError, ValueError):
            row = None
        if row is None or row.facility_id != facility_id:
            raise PlatformError("That article list doesn't exist any more. Choose another one.", "no_list", 409)
        return row

    def race(self, game, facility_id, settings):
        source = self.wiki_source(game)
        resolved, key = self.resolved_list(game, facility_id, settings.get("list", "default"), source)
        return wikirace.Race(source, resolved["paths"] if resolved else None, key)

    def _check_race_settings(self, game, facility_id, values, pick_random):
        """Turn typed start and goal titles into article paths. Returns (values, errors)."""
        values = dict(values)
        try:
            race = self.race(game, facility_id, values)
        except PlatformError as e:
            return values, {"list": str(e)}
        start, goal, errors = wikirace.check_pair(race.wiki, race.allowed, values.get("start"), values.get("goal"))
        if errors:
            return values, errors
        if start is None and pick_random:
            try:
                start, goal = wiki.random_pair(race.wiki, race.allowed)
            except wiki.WikiError as e:
                return values, {"list": str(e)}
        values["start"], values["goal"] = start or "", goal or ""
        return values, {}

    # ======================================================== photo guessing

    def photo_packs(self, game):
        """{pack id: PhotoPack} from the photo-packs folder."""
        return photos.find_packs(game.data_paths().get("photo-packs"))

    def map_choices(self, game):
        """The game's maps that have photos on this device, with how many."""
        counts = {}
        countries = self.countries(game)
        for _pack, place in photoguess.places_on_map(self.photo_packs(game).values(), countries, photoguess.WORLD):
            counts[place.get("continent")] = counts.get(place.get("continent"), 0) + 1
        choices = []
        for m in game.manifest.photos.get("maps") or []:
            n = sum(counts.values()) if m["id"] == photoguess.WORLD else counts.get(m["id"], 0)
            if n or m["id"] == photoguess.WORLD:
                choices.append({"value": m["id"], "label": "%s (%d photos)" % (m["title"], n)})
        return choices

    _countries = {}

    def countries(self, game):
        """The game's countries file: code -> {name, lat, lon, ...}, read once per game version."""
        key = (game.key, game.manifest.version)
        if key not in self._countries:
            path = game.manifest.photos.get("countries")
            found = game.source.read(path) if path else None
            if found is None:
                raise PlatformError("The game's countries file (%s) is missing." % path, "no_countries", 409)
            try:
                data = json.loads(found[0].decode("utf-8"))
            except ValueError:
                raise PlatformError("The game's countries file isn't valid JSON.", "no_countries", 409)
            self._countries[key] = {
                code: c for code, c in data.items()
                if isinstance(c, dict) and isinstance(c.get("lat"), (int, float)) and isinstance(c.get("lon"), (int, float))
            }
        return self._countries[key]

    def hunt(self, game, settings):
        """The rules for a game with these settings: its map ("map") and mode ("mode")."""
        settings = settings or {}
        packs = list(self.photo_packs(game).values())
        if not packs:
            raise PlatformError("There are no photo packs on this device.", "no_photos", 409)
        game_map = photoguess.map_info(game.manifest.photos.get("maps"), settings.get("map"))
        if game_map is None:
            raise PlatformError("This game has no map called %s." % settings.get("map"), "no_photos", 409)
        return photoguess.Hunt(packs, self.countries(game), game_map, settings.get("mode") or "country")

    def _rounds(self, settings):
        try:
            return max(1, min(photoguess.MAX_ROUNDS, int(settings.get("rounds") or 5)))
        except (TypeError, ValueError):
            return 5

    def _check_photo_settings(self, game, values):
        map_id = values.get("map", photoguess.WORLD)
        if photoguess.map_info(game.manifest.photos.get("maps"), map_id) is None:
            return {"map": "This game has no map called %s." % map_id}
        if map_id != photoguess.WORLD and map_id not in [c["value"] for c in self.map_choices(game)]:
            return {"map": "There are no photos for that map on this device."}
        return {}

    def _photo_refs(self, game, ctx):
        """The places for a new attempt: a challenge's fixed places, or a fresh pick."""
        if ctx.challenge is not None and (ctx.challenge.settings or {}).get("_places"):
            return ctx.challenge.settings["_places"]
        hunt = self.hunt(game, ctx.settings)
        try:
            return photoguess.pick_places(hunt.places(), self._rounds(ctx.settings), countries=hunt.countries)
        except photoguess.GuessError as e:
            raise PlatformError(str(e), e.code, 409)

    def attempt_photo(self, game, user_id, attempt_id, index):
        """(bytes, mimetype) of one round's photo, for the player whose attempt it is.

        Only rounds the player has reached can be fetched, so a learner can't
        look ahead. The photo's hidden GPS data is removed (see photos.py).
        """
        attempt = self.store.attempt_get(attempt_id)
        if attempt is None or attempt.user_id != user_id or attempt.game_key != game.key:
            return None
        state = attempt.state or {}
        refs = state.get("places") or []
        if not 0 <= index < len(refs) or index > len(state.get("results") or []):
            return None
        pack_id, _, place_id = refs[index].partition("/")
        pack = self.photo_packs(game).get(pack_id)
        place = pack.places.get(place_id) if pack else None
        return pack.photo(place) if place else None

    def suggest_articles(self, game, facility_id, text, list_value):
        source = self.wiki_source(game)
        resolved, _key = self.resolved_list(game, facility_id, list_value or "default", source)
        return wiki.suggest(source, text, resolved)

    # ======================================================== playing

    def _attempt_info(self, attempt, all_attempts, counts):
        return {
            "id": attempt.id,
            "number": attempt.number,
            "status": attempt.status,
            "practice": ranking.is_practice(attempt, all_attempts, counts),
            "started_at": _iso(attempt.started_at),
            "score": ranking.num(attempt.score),
            "seconds": round(attempt.seconds, 1) if attempt.seconds is not None else None,
        }

    def _elapsed(self, attempt):
        """Seconds since the attempt started, without counting clock jumps when possible.

        The jump-free clock is used for attempts started since the server last
        started (nearly all of them). Older ones fall back to the normal clock,
        never counting less than 0 or more than RESUME_HOURS.
        """
        start = self._started.get(attempt.id)
        if start is not None:
            return max(0.0, self.monotonic() - start)
        wall = (self.now() - attempt.started_at).total_seconds()
        return min(max(0.0, wall), RESUME_HOURS * 3600.0)

    def _close(self, attempt, status):
        attempt.status = status
        attempt.seconds = self._elapsed(attempt)
        attempt.finished_at = self.now()
        self._started.pop(attempt.id, None)
        self.store.attempt_save(attempt)

    def _over_time(self, attempt, limit):
        return limit and self._elapsed(attempt) > limit + TIME_GRACE_SECONDS

    def _open_attempt(self, game, player, attempt_id):
        attempt = self.store.attempt_get(attempt_id)
        if attempt is None or attempt.user_id != player.id or attempt.game_key != game.key:
            raise PlatformError("That attempt doesn't exist.", "not_found", 404)
        if attempt.voided:
            raise PlatformError("A coach reset this game. Start again.", "reset", 409)
        if attempt.status != "started":
            raise PlatformError("This attempt is already over.", "attempt_over", 409)
        ctx = self.context(game, player, attempt.challenge_id)
        if ctx.challenge is not None and self.challenge_state(ctx.challenge) == "closed":
            self._close(attempt, "expired")
            raise PlatformError("This challenge has closed.", "closed", 409)
        if self._over_time(attempt, ctx.time_limit):
            self._close(attempt, "expired")
            raise PlatformError("Time's up.", "time_up", 409)
        return attempt, ctx

    def start(self, game, player, challenge_id=FREE_PLAY, resume=True):
        ctx = self.context(game, player, challenge_id)
        if ctx.challenge is not None:
            state = self.challenge_state(ctx.challenge)
            if state != "open" and not player.can_manage(ctx.challenge.class_id):
                raise PlatformError(
                    "This challenge hasn't opened yet." if state == "upcoming" else "This challenge has closed.",
                    state, 409,
                )
        mine = self.store.attempts(game.key, player.facility_id, ctx.challenge_id, player.id)
        is_race = game.manifest.service == "wikipedia-race"
        is_hunt = game.manifest.service == "photo-guess"

        # Pick up an unfinished attempt where the player left it, and close older ones.
        open_attempts = sorted([a for a in mine if a.status == "started" and not a.voided], key=lambda a: a.number)
        for a in open_attempts:
            age = self._elapsed(a)
            if resume and a is open_attempts[-1] and not self._over_time(a, ctx.time_limit) and age < RESUME_HOURS * 3600:
                public = a.public
                if is_race:
                    public = self.race(game, player.facility_id, ctx.settings).resume(a.state)
                elif is_hunt:
                    public = self.hunt(game, ctx.settings).public(a.state, a.id)
                return {
                    "attempt": self._attempt_info(a, mine, ctx.counts),
                    "public": public,
                    "resumed": True,
                    "time_limit": ctx.time_limit or None,
                    "elapsed": round(age, 1),
                }
            self._close(a, "expired" if self._over_time(a, ctx.time_limit) else "abandoned")

        state, public = {}, {}
        if is_race:
            race = self.race(game, player.facility_id, ctx.settings)
            start, goal = ctx.settings.get("start"), ctx.settings.get("goal")
            if not start or not goal:
                try:
                    start, goal = wiki.random_pair(race.wiki, race.allowed)
                except wiki.WikiError as e:
                    raise PlatformError(str(e), "no_pair", 409)
            try:
                state, public = race.start(start, goal)
            except wiki.WikiError as e:
                raise PlatformError(str(e), "no_article", 409)
        elif is_hunt:
            hunt = self.hunt(game, ctx.settings)
            state = hunt.start(self._photo_refs(game, ctx))
        number = max([a.number for a in mine] or [0]) + 1
        attempt = self.store.attempt_create(
            game_key=game.key,
            game_id=game.manifest.id,
            game_version=game.manifest.version,
            facility_id=player.facility_id,
            user_id=player.id,
            user_name=player.name,
            challenge_id=ctx.challenge_id,
            number=number,
            status="started",
            voided=False,
            started_at=self.now(),
            public={} if is_race or is_hunt else public,  # rebuilt from the state when resuming
            state=state,
            events=[],
            detail={},
        )
        self._started[attempt.id] = self.monotonic()
        while len(self._started) > 10000:  # keep memory small: forget the oldest
            self._started.popitem(last=False)
        if is_hunt:
            public = hunt.public(state, attempt.id)  # photo addresses include the attempt id
        return {
            "attempt": self._attempt_info(attempt, mine + [attempt], ctx.counts),
            "public": public,
            "resumed": False,
            "time_limit": ctx.time_limit or None,
            "elapsed": 0,
        }

    def move(self, game, player, attempt_id, kind, data):
        """Record one move. For the Wikipedia race, the server checks it and replies with the next page."""
        if not isinstance(kind, str) or not 0 < len(kind) <= 40:
            raise PlatformError("Moves need a short name.", "bad_move")
        if _size(data) > MAX_EVENT_BYTES:
            raise PlatformError("That move is too large.", "bad_move")
        attempt, ctx = self._open_attempt(game, player, attempt_id)
        events = attempt.events
        if len(events) >= MAX_EVENTS:
            raise PlatformError("Too many moves in one attempt.", "too_many_moves")
        reply, logged = {}, data
        if game.manifest.service == "wikipedia-race":
            race = self.race(game, player.facility_id, ctx.settings)
            try:
                attempt.state, reply, logged = race.move(attempt.state, kind, data)
            except wikirace.RaceError as e:
                raise PlatformError(str(e), e.code)
            except wiki.WikiError as e:
                raise PlatformError(str(e), "no_article", 409)
        elif game.manifest.service == "photo-guess":
            hunt = self.hunt(game, ctx.settings)
            try:
                attempt.state, reply, logged = hunt.move(attempt.state, kind, data, attempt.id)
            except photoguess.GuessError as e:
                raise PlatformError(str(e), e.code)
        elapsed = self._elapsed(attempt)
        attempt.events = events + [{"t": round(elapsed, 1), "type": kind, "data": logged}]
        self.store.attempt_save(attempt)
        return reply

    def finish(self, game, player, attempt_id, claimed):
        claimed = claimed if isinstance(claimed, dict) else {}
        attempt, ctx = self._open_attempt(game, player, attempt_id)
        scoring = game.manifest.scoring
        if game.manifest.service == "wikipedia-race":
            # The server works out the score from the chain it kept.
            try:
                score, detail = self.race(game, player.facility_id, ctx.settings).finish(attempt.state)
            except wikirace.RaceError as e:
                raise PlatformError(str(e), e.code)
        elif game.manifest.service == "photo-guess":
            # The server adds up the points it gave for each guess.
            try:
                score, detail = self.hunt(game, ctx.settings).finish(attempt.state)
            except photoguess.GuessError as e:
                raise PlatformError(str(e), e.code)
        else:
            # The game reports its own score; impossible ones are refused.
            score, detail = claimed.get("score"), claimed.get("detail") or {}
            if _size(detail) > MAX_DETAIL_BYTES:
                raise PlatformError("The result details are too large.", "bad_result")
            if scoring is None:
                score = None
            elif score is not None:
                if isinstance(score, bool) or not isinstance(score, (int, float)):
                    raise PlatformError("The score must be a number.", "bad_result")
                if scoring.get("min") is not None and score < scoring["min"]:
                    raise PlatformError("That score is too low to be possible.", "bad_result")
                if scoring.get("max") is not None and score > scoring["max"]:
                    raise PlatformError("That score is too high to be possible.", "bad_result")
        attempt.score = score
        attempt.detail = detail
        self._close(attempt, "finished")
        return self._finish_payload(game, player, attempt, ctx)

    def _finish_payload(self, game, player, attempt, ctx):
        mine = self.store.attempts(game.key, player.facility_id, ctx.challenge_id, player.id)
        payload = {"attempt": self._attempt_info(attempt, mine, ctx.counts), "counts": ctx.counts, "standing": None}
        payload["attempt"]["detail"] = attempt.detail
        scoring = game.manifest.scoring
        if scoring is None or (ctx.challenge is None and not game.manifest.free_play_scoreboard):
            return payload
        everyone = self.store.attempts(game.key, player.facility_id, ctx.challenge_id)
        ranked = ranking.ranked(everyone, scoring, ctx.counts)
        for rank, a in ranked:
            if a.user_id == player.id:
                payload["standing"] = {
                    "rank": rank,
                    "of": len(ranked),
                    "score": ranking.num(a.score),
                    "seconds": round(a.seconds or 0, 1),
                    "attempt": a.number,
                }
        return payload

    def abandon(self, game, player, attempt_id):
        attempt = self.store.attempt_get(attempt_id)
        if attempt is None or attempt.user_id != player.id or attempt.game_key != game.key:
            raise PlatformError("That attempt doesn't exist.", "not_found", 404)
        if attempt.status == "started":
            self._close(attempt, "abandoned")
        return {"ok": True}

    # ======================================================== results

    def scoreboard(self, game, viewer, challenge_id=FREE_PLAY, user_ids=None, limit=20):
        """Ranked rows for free play or one challenge. Routes are shown once a challenge has closed."""
        scoring = game.manifest.scoring
        ctx = self.context(game, viewer, challenge_id)
        result = {"rows": [], "visibility": ctx.visibility, "counts": ctx.counts, "challenge": None}
        if ctx.challenge is not None:
            result["challenge"] = self.challenge_public(game, ctx.challenge, viewer)
        elif not game.manifest.free_play_scoreboard:
            result["no_scoreboard"] = True
            return result
        if scoring is None:
            return result
        visibility = "names" if viewer.is_coach else ctx.visibility
        attempts = self.store.attempts(game.key, viewer.facility_id, ctx.challenge_id)
        if user_ids is not None:
            attempts = [a for a in attempts if a.user_id in user_ids]
        closed = ctx.challenge is not None and self.challenge_state(ctx.challenge) == "closed"
        rows = ranking.scoreboard_rows(attempts, scoring, ctx.counts, viewer.id, visibility, limit if not viewer.is_coach else 200)
        if closed:
            by_id = {a.id: a for a in attempts}
            for row in rows:
                row["route"] = (by_id[row.pop("attempt_id")].detail or {}).get("route")
        else:
            for row in rows:
                row.pop("attempt_id", None)
        result["rows"] = rows
        result["visibility"] = visibility
        return result

    def summary(self, game, player):
        """The player's own results, for game cards and the game's hello message."""
        if game.manifest.is_classroom:
            mine = self.store.classroom_saves(game.content_ids, player.facility_id, player.id)
            return classroom.summary(game, mine)
        platform, _ = self.settings(game, player.facility_id)
        counts = platform.get("counts", "first")
        mine = [a for a in self.store.attempts(game.key, player.facility_id, FREE_PLAY, player.id) if not a.voided]
        result = {"attempts": len(mine), "counted": None, "counts": counts}
        if game.manifest.scoring:
            a = ranking.counted_attempt(mine, game.manifest.scoring, counts)
            if a is not None:
                result["counted"] = {"score": ranking.num(a.score), "seconds": round(a.seconds or 0, 1), "number": a.number}
            result["first_used"] = ranking.first_attempt(mine) is not None
        return result

    def challenge_summary(self, game, player, challenge):
        mine = [a for a in self.store.attempts(game.key, player.facility_id, challenge.id, player.id) if not a.voided]
        info = {"attempts": len(mine), "counted": None, "first_used": ranking.first_attempt(mine) is not None}
        if game.manifest.scoring:
            a = ranking.counted_attempt(mine, game.manifest.scoring, challenge.counts)
            if a is not None:
                info["counted"] = {"score": ranking.num(a.score), "seconds": round(a.seconds or 0, 1)}
        return info

    def my_attempts(self, game, player, challenge_id=FREE_PLAY):
        ctx = self.context(game, player, challenge_id)
        mine = [a for a in self.store.attempts(game.key, player.facility_id, ctx.challenge_id, player.id) if not a.voided]
        return [self._attempt_info(a, mine, ctx.counts) for a in sorted(mine, key=lambda a: a.number)]

    def coach_results(self, game, coach, challenge_id=FREE_PLAY, users=None):
        """Per-learner results. ``users`` is [(id, name)] to include even if they haven't played."""
        ctx = self.context(game, coach, challenge_id)
        counts, scoring = ctx.counts, game.manifest.scoring
        attempts = self.store.attempts(game.key, coach.facility_id, ctx.challenge_id)
        groups = ranking.by_user(attempts)
        rank_of = {}
        if scoring:
            for rank, a in ranking.ranked(attempts, scoring, counts):
                rank_of[a.user_id] = rank
        names = {a.user_id: a.user_name for a in attempts}
        if users is not None:
            wanted = [u for u, _ in users]
            names.update(dict(users))
        else:
            wanted = sorted(groups, key=lambda u: names.get(u, "").lower())
        rows = []
        for user_id in wanted:
            mine = groups.get(user_id, [])
            live = [a for a in mine if not a.voided]
            counted = ranking.counted_attempt(live, scoring, counts) if scoring else None
            best = ranking.counted_attempt(live, scoring, "best") if scoring else None
            rows.append(
                {
                    "user_id": user_id,
                    "name": names.get(user_id, "?"),
                    "rank": rank_of.get(user_id),
                    "attempts": len(live),
                    "reset_attempts": len(mine) - len(live),
                    "counted": self._attempt_info(counted, live, counts) if counted else None,
                    "best": self._attempt_info(best, live, counts) if best else None,
                    "last_played": _iso(max([a.started_at for a in live])) if live else None,
                    "history": [
                        dict(self._attempt_info(a, live, counts), detail=a.detail, events=a.events)
                        for a in sorted(live, key=lambda a: a.number)
                    ],
                }
            )
        if scoring:
            rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, r["name"].lower()))
        challenge = self.challenge_public(game, ctx.challenge, coach) if ctx.challenge else None
        return {"rows": rows, "counts": counts, "scoring": scoring, "challenge": challenge}

    def reset(self, game, facility_id, user_id, challenge_id=FREE_PLAY):
        self.store.attempts_void(game.key, facility_id, challenge_id, user_id)
        return {"ok": True}

    # ======================================================== challenges

    def challenge_public(self, game, c, viewer):
        """A challenge as the games page shows it."""
        info = {
            "id": c.id,
            "title": c.title,
            "class_id": c.class_id,
            "class_name": c.class_name,
            "opens_at": _iso(c.opens_at),
            "closes_at": _iso(c.closes_at),
            "state": self.challenge_state(c),
            "status": getattr(c, "status", "auto") or "auto",
            "counts": c.counts,
            "time_limit": c.time_limit,
            "can_manage": viewer.can_manage(c.class_id),
        }
        if game.manifest.service == "wikipedia-race":
            info.update(self._race_challenge_info(game, c, viewer, info["state"]))
        if info["can_manage"]:
            info["settings"] = {k: v for k, v in (c.settings or {}).items() if not k.startswith("_")}
        return info

    def _race_challenge_info(self, game, c, viewer, state):
        """Start, goal and (for coaches, or after closing) the shortest route."""
        out = {}
        try:
            source = self.wiki_source(game)
            out["start"] = source.title(c.settings.get("start", ""))
            out["goal"] = source.title(c.settings.get("goal", ""))
            best = c.best or {}
            if viewer.can_manage(c.class_id) or state == "closed":
                shown = {"status": best.get("status", "working")}
                if best.get("route"):
                    shown["route"] = [source.title(p) for p in best["route"]]
                    shown["steps"] = len(best["route"]) - 1
                out["best"] = shown
        except PlatformError:
            pass
        return out

    def challenges_for(self, game, viewer, include_old=False):
        """Challenges this person can see for a game: learners see their classes' open and recent ones."""
        out = []
        now = self.now()
        for c in self.store.challenges(viewer.facility_id, game.key):
            mine = c.class_id in viewer.class_ids
            manage = viewer.can_manage(c.class_id)
            if not (mine or manage):
                continue
            state = self.challenge_state(c)
            if state == "upcoming" and not manage:
                continue
            if state == "closed" and not include_old and (c.closes_at or now) < now - timedelta(days=RECENT_DAYS):
                continue
            info = self.challenge_public(game, c, viewer)
            if mine:
                info["mine"] = self.challenge_summary(game, viewer, c)
            out.append(info)
        order = {"open": 0, "upcoming": 1, "closed": 2}
        out.sort(key=lambda i: (order[i["state"]], i["closes_at"] or "9999", i["title"].lower()))
        return out

    def save_challenge(self, game, coach, data, class_names, challenge_id=None):
        """Create or change a challenge. ``class_names`` maps the coach's class ids to names."""
        data = data if isinstance(data, dict) else {}
        errors = {}
        title = (data.get("title") or "").strip()
        if not title or len(title) > 100:
            errors["title"] = "Give the challenge a name (at most 100 characters)."
        class_id = data.get("class_id")
        if class_id not in class_names or not coach.can_manage(class_id):
            errors["class_id"] = "Choose one of your classes."
        counts = data.get("counts") or (game.manifest.scoring or {}).get("counts", "first")
        if counts not in ("first", "best"):
            errors["counts"] = "Choose which attempt counts."
        try:
            time_limit = int(data.get("time_limit") or 0)
            if not 0 <= time_limit <= 240:
                raise ValueError
        except (TypeError, ValueError):
            time_limit = 0
            errors["time_limit"] = "The time limit must be 0 to 240 minutes."
        # When to open: "now", "button" (when the coach presses Open) or "time".
        # When to close: "button" (when the coach presses Close) or "time".
        # "Now" uses this server's clock, so it works even if the coach's device
        # and the server disagree about the time.
        opens, closes = data.get("opens") or "now", data.get("closes") or "button"
        now = self.now()
        status, opens_at, closes_at = "auto", None, None
        if opens == "now":
            status, opens_at = "open", now
        elif opens == "time":
            opens_at = parse_time(data.get("opens_at"))
            if opens_at is None:
                errors["opens_at"] = "Choose the date and time to open."
        elif opens != "button":
            errors["opens"] = "Choose when the challenge opens."
        if closes == "time":
            closes_at = parse_time(data.get("closes_at"))
            if closes_at is None:
                errors["closes_at"] = "Choose the date and time to close."
            elif opens == "time" and opens_at is not None and closes_at <= opens_at:
                errors["closes_at"] = "The challenge must close after it opens."
            elif closes_at <= now:
                errors["closes_at"] = (
                    "That time has already passed by this server's clock (%s UTC). If the server's clock "
                    "is wrong, use the Close button instead." % now.strftime("%Y-%m-%d %H:%M")
                )
        elif closes != "button":
            errors["closes"] = "Choose when the challenge closes."
        values, setting_errors = clean_settings(game.manifest.settings, data.get("settings") or {})
        errors.update(setting_errors)
        existing = None
        if challenge_id is not None:
            existing = self.store.challenge_get(challenge_id)
            if existing is None or existing.game_key != game.key or not coach.can_manage(existing.class_id):
                raise PlatformError("That challenge doesn't exist.", "not_found", 404)
        race = game.manifest.service == "wikipedia-race"
        if race and not errors:
            # Every learner in a challenge gets the same start and goal, so a
            # blank pair is filled in now, once.
            values, race_errors = self._check_race_settings(game, coach.facility_id, values, pick_random=True)
            errors.update(race_errors)
        if game.manifest.service == "photo-guess" and not errors:
            errors.update(self._check_photo_settings(game, values))
            if not errors:
                # Every learner in a challenge gets the same photos, picked now. They're
                # kept under a hidden "_places" key that is never sent to the browser.
                old = (existing.settings or {}) if existing is not None else {}
                same = all(old.get(k) == values.get(k) for k in ("map", "mode", "rounds"))
                if same and old.get("_places"):
                    values["_places"] = old["_places"]
                else:
                    hunt = self.hunt(game, values)
                    try:
                        values["_places"] = photoguess.pick_places(hunt.places(), self._rounds(values),
                                                                    countries=hunt.countries)
                    except photoguess.GuessError as e:
                        errors["map"] = str(e)
        if errors:
            raise PlatformError(" ".join(errors.values()), "invalid_challenge", fields=errors)
        if existing is not None and opens == "now" and self.challenge_state(existing) == "open":
            opens_at = existing.opens_at or opens_at  # already open: keep when it opened
        fields = dict(
            title=title, class_id=class_id, class_name=class_names[class_id], settings=values, counts=counts,
            time_limit=time_limit, opens_at=opens_at, closes_at=closes_at, status=status,
        )
        if existing is None:
            c = self.store.challenge_create(
                game_key=game.key, facility_id=coach.facility_id, created_by_id=coach.id, best={}, **fields
            )
        else:
            pair_changed = race and (
                existing.settings.get("start"), existing.settings.get("goal"), existing.settings.get("list")
            ) != (values.get("start"), values.get("goal"), values.get("list"))
            for k, v in fields.items():
                setattr(existing, k, v)
            if pair_changed:
                existing.best = {}
            self.store.challenge_save(existing)
            c = existing
        if race and not (c.best or {}).get("status"):
            self._find_best_route(game, c)
        return self.challenge_public(game, c, coach)

    def _find_best_route(self, game, c):
        """Work out the shortest route in the background and save it on the challenge."""
        challenge_id, facility_id, settings = c.id, c.facility_id, dict(c.settings)

        def work():
            try:
                race = self.race(game, facility_id, settings)
                best = wiki.shortest_route(race.wiki, settings["start"], settings["goal"], race.allowed)
            except Exception as e:  # never let a background job crash the server
                best = {"status": "error", "message": str(e)[:200]}
            self.store.challenge_set_best(challenge_id, best)

        self.background(work)

    def open_or_close_challenge(self, game, coach, challenge_id, action):
        """The Open and Close buttons. They use this server's clock only to record when."""
        c = self.store.challenge_get(challenge_id)
        if c is None or c.game_key != game.key or not coach.can_manage(c.class_id) or c.facility_id != coach.facility_id:
            raise PlatformError("That challenge doesn't exist.", "not_found", 404)
        now = self.now()
        if action == "open":
            c.status = "open"
            c.opens_at = c.opens_at if c.opens_at and c.opens_at <= now else now
            if c.closes_at and c.closes_at <= now:
                c.closes_at = None  # reopening: forget a closing time that has passed
        elif action == "close":
            c.status = "closed"
            c.closes_at = now
        else:
            raise PlatformError("Unknown action.", "bad_request")
        self.store.challenge_save(c)
        return self.challenge_public(game, c, coach)

    def delete_challenge(self, game, coach, challenge_id):
        c = self.store.challenge_get(challenge_id)
        if c is None or c.game_key != game.key or not coach.can_manage(c.class_id) or c.facility_id != coach.facility_id:
            raise PlatformError("That challenge doesn't exist.", "not_found", 404)
        self.store.challenge_delete(c)
        return {"ok": True}

    # ======================================================== article lists

    def article_lists(self, facility_id):
        return [
            {"id": row.id, "value": "list-%d" % row.id, "name": row.name, "count": len(wiki.parse_list(row.titles)),
             "updated_at": _iso(row.updated_at)}
            for row in self.store.article_lists(facility_id)
        ]

    def article_list(self, facility_id, list_id, game=None):
        row = self._article_list(facility_id, "list-%s" % list_id)
        info = {"id": row.id, "name": row.name, "titles": row.titles}
        if game is not None:
            # Which titles aren't in the Wikipedia file, so the coach can fix them.
            source = self.wiki_source(game)
            titles = wiki.parse_list(row.titles)
            resolved = wiki.resolve_list(source, titles, ("list", row.id, _iso(row.updated_at)))
            info.update(found=len(resolved["paths"]), missing=resolved["missing"][:200], missing_count=len(resolved["missing"]))
        return info

    def save_article_list(self, coach, data, list_id=None):
        data = data if isinstance(data, dict) else {}
        name = (data.get("name") or "").strip()
        titles = data.get("titles") or ""
        errors = {}
        if not name or len(name) > 100:
            errors["name"] = "Give the list a name (at most 100 characters)."
        if not isinstance(titles, str) or len(titles) > 4 * 1024 * 1024:
            errors["titles"] = "The list is too long."
        elif not wiki.parse_list(titles):
            errors["titles"] = "Add at least one article title, one per line."
        elif len(wiki.parse_list(titles)) > MAX_LIST_TITLES:
            errors["titles"] = "A list can have at most %d articles." % MAX_LIST_TITLES
        if errors:
            raise PlatformError(" ".join(errors.values()), "invalid_list", fields=errors)
        if list_id is None:
            row = self.store.article_list_create(facility_id=coach.facility_id, name=name, titles=titles,
                                                 created_by_id=coach.id, updated_at=self.now())
        else:
            row = self._article_list(coach.facility_id, "list-%s" % list_id)
            row.name, row.titles, row.updated_at = name, titles, self.now()
            self.store.article_list_save(row)
        return {"id": row.id, "value": "list-%d" % row.id, "name": row.name}

    def delete_article_list(self, coach, list_id):
        row = self._article_list(coach.facility_id, "list-%s" % list_id)
        self.store.article_list_delete(row)
        return {"ok": True}

    # ======================================================== Classroom Games

    def classroom_scoreboards(self, game, viewer, user_ids=None):
        """Scoreboards of a Classroom Game, read from Kolibri's saved data."""
        if not game.manifest.is_classroom:
            raise PlatformError("This game has no scoreboards.", "not_classroom", 404)
        platform, _ = self.settings(game, viewer.facility_id)
        visibility = "names" if viewer.is_coach else platform.get("scoreboard", "names")
        saves = self.store.classroom_saves(game.content_ids, viewer.facility_id)
        if user_ids is not None:
            saves = [s for s in saves if s["user_id"] in user_ids]
        return classroom.scoreboards(game, saves, viewer.id, visibility)

    # ======================================================== saved data

    def get_state(self, game, player):
        return self.store.state_get(game.key, player.id)

    def set_state(self, game, player, data):
        if _size(data) > MAX_STATE_BYTES:
            raise PlatformError("Saved data is limited to 64 KB.", "too_large")
        self.store.state_set(game.key, player.id, data)
        return {"ok": True}


def parse_time(value):
    """A timezone-aware datetime from an ISO 8601 string like 2026-11-02T14:00:00Z, or None."""
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ------------------------------------------------------------ in-memory


class MemoryRecord(object):
    def __init__(self, **fields):
        self.score = None
        self.seconds = None
        self.finished_at = None
        self.__dict__.update(fields)


class MemoryStore(Store):
    """Keeps everything in memory. Used by tests and the preview server."""

    def __init__(self):
        self._settings = {}
        self._attempts = []
        self._state = {}
        self._saves = []
        self._challenges = []
        self._lists = []
        self._lock = threading.Lock()

    def settings_get(self, game_key, facility_id):
        return self._settings.get((game_key, facility_id))

    def settings_set(self, game_key, facility_id, platform, game, by_user_id):
        self._settings[(game_key, facility_id)] = {"platform": platform, "game": game}

    def attempts(self, game_key, facility_id, challenge_id, user_id=None):
        return [
            a for a in self._attempts
            if a.game_key == game_key and a.facility_id == facility_id and a.challenge_id == challenge_id
            and (user_id is None or a.user_id == user_id)
        ]

    def attempt_get(self, attempt_id):
        for a in self._attempts:
            if a.id == attempt_id:
                return a
        return None

    def attempt_create(self, **fields):
        with self._lock:
            record = MemoryRecord(id=len(self._attempts) + 1, **fields)
            self._attempts.append(record)
        return record

    def attempt_save(self, attempt):
        pass

    def attempts_void(self, game_key, facility_id, challenge_id, user_id):
        for a in self.attempts(game_key, facility_id, challenge_id, user_id):
            a.voided = True
            if a.status == "started":
                a.status = "abandoned"

    def state_get(self, game_key, user_id):
        return self._state.get((game_key, user_id))

    def state_set(self, game_key, user_id, data):
        self._state[(game_key, user_id)] = data

    def challenges(self, facility_id, game_key=None):
        return [c for c in self._challenges if c.facility_id == facility_id and (game_key is None or c.game_key == game_key)]

    def challenge_get(self, challenge_id):
        for c in self._challenges:
            if c.id == challenge_id:
                return c
        return None

    def challenge_create(self, **fields):
        with self._lock:
            c = MemoryRecord(id=max([x.id for x in self._challenges] or [0]) + 1, **fields)
            self._challenges.append(c)
        return c

    def challenge_save(self, challenge):
        pass

    def challenge_delete(self, challenge):
        self._challenges = [c for c in self._challenges if c.id != challenge.id]

    def challenge_set_best(self, challenge_id, best):
        c = self.challenge_get(challenge_id)
        if c is not None:
            c.best = best

    def article_lists(self, facility_id):
        return sorted([x for x in self._lists if x.facility_id == facility_id], key=lambda x: x.name.lower())

    def article_list_get(self, list_id):
        for x in self._lists:
            if x.id == list_id:
                return x
        return None

    def article_list_create(self, **fields):
        with self._lock:
            row = MemoryRecord(id=max([x.id for x in self._lists] or [0]) + 1, **fields)
            self._lists.append(row)
        return row

    def article_list_save(self, article_list):
        pass

    def article_list_delete(self, article_list):
        self._lists = [x for x in self._lists if x.id != article_list.id]

    def add_classroom_save(self, player, content_id, content_state):
        """Pretend a learner played a Classroom Game resource in Learn (tests and the preview server)."""
        self._saves = [s for s in self._saves if not (s["user_id"] == player.id and s["content_id"] == content_id)]
        self._saves.append({
            "user_id": player.id, "user_name": player.name, "facility_id": player.facility_id,
            "content_id": content_id, "content_state": content_state,
        })

    def classroom_saves(self, content_ids, facility_id, user_id=None):
        wanted = set(content_ids)
        return [
            s for s in self._saves
            if s["content_id"] in wanted and s["facility_id"] == facility_id and (user_id is None or s["user_id"] == user_id)
        ]
