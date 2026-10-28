"""
The rules of play: starting, moving, finishing, scoring and leaderboards.

This module doesn't touch Django directly. It talks to a *store* (see
``Store`` below), so the same rules run inside Kolibri (``store_django``)
and in tests or the developer preview server (``MemoryStore``).
"""
import json
from datetime import datetime, timezone

from . import lessons, ranking
from . import validators as validator_registry
from .manifest import clean_settings, merge_settings
from .validators import ValidatorContext, ValidatorError

MAX_EVENTS = 2000
MAX_EVENT_BYTES = 4096
MAX_DETAIL_BYTES = 16384
MAX_STATE_BYTES = 65536
TIME_GRACE_SECONDS = 5
RESUME_HOURS = 12


def utcnow():
    return datetime.now(timezone.utc)


class PlatformError(Exception):
    """An error to show the player. ``status`` is the HTTP status to use."""

    def __init__(self, message, code="error", status=400):
        super(PlatformError, self).__init__(message)
        self.code = code
        self.status = status


class Player(object):
    def __init__(self, id, name, facility_id, is_coach=False, is_admin=False):
        self.id = id
        self.name = name
        self.facility_id = facility_id
        self.is_coach = is_coach or is_admin
        self.is_admin = is_admin

    @property
    def role(self):
        return "admin" if self.is_admin else ("coach" if self.is_coach else "learner")


def _size(obj):
    return len(json.dumps(obj, separators=(",", ":")))


class Store(object):
    """Persistence used by GameService. Records are objects with attributes:

    id, game_key, game_id, game_version, facility_id, user_id, user_name,
    number, status, voided, started_at, finished_at, seconds, score, verified,
    and dict/list properties public, vstate, events, detail.
    """

    def settings_get(self, game_key, facility_id):
        raise NotImplementedError

    def settings_set(self, game_key, facility_id, platform, game, by_user_id):
        raise NotImplementedError

    def attempts(self, game_key, facility_id, user_id=None):
        raise NotImplementedError

    def attempt_get(self, attempt_id):
        raise NotImplementedError

    def attempt_create(self, **fields):
        raise NotImplementedError

    def attempt_save(self, attempt):
        raise NotImplementedError

    def attempts_void(self, game_key, facility_id, user_id):
        raise NotImplementedError

    def state_get(self, game_key, user_id):
        raise NotImplementedError

    def state_set(self, game_key, user_id, data):
        raise NotImplementedError

    def lesson_saves(self, content_ids, facility_id, user_id=None):
        """Saved data of Lesson Game resources: a list of dicts with
        user_id, user_name, content_id and content_state (Kolibri's saved state)."""
        raise NotImplementedError


class GameService(object):
    def __init__(self, store, now=utcnow):
        self.store = store
        self.now = now

    # ---------------------------------------------------------- settings

    def settings(self, game, facility_id):
        """(platform_values, game_values) for this facility, defaults filled in."""
        stored = self.store.settings_get(game.key, facility_id) or {}
        m = game.manifest
        return (
            merge_settings(m.platform_settings_schema(), stored.get("platform")),
            merge_settings(m.settings, stored.get("game")),
        )

    def save_settings(self, game, facility_id, platform, values, by_user_id):
        m = game.manifest
        p_vals, p_err = clean_settings(m.platform_settings_schema(), platform or {})
        g_vals, g_err = clean_settings(m.settings, values or {})
        errors = dict(p_err, **g_err)
        if errors:
            err = PlatformError(" ".join(errors.values()), "invalid_settings")
            err.fields = errors
            raise err
        self.store.settings_set(game.key, facility_id, p_vals, g_vals, by_user_id)
        return p_vals, g_vals

    def schema(self, game):
        return {"platform": game.manifest.platform_settings_schema(), "game": game.manifest.settings}

    # ---------------------------------------------------------- helpers

    def _validator(self, game):
        name = game.manifest.validator
        return validator_registry.get(name) if name else None

    def _ctx(self, game, attempt, game_settings):
        elapsed = (self.now() - attempt.started_at).total_seconds() if attempt else 0.0
        return ValidatorContext(
            settings=game_settings,
            attempt=attempt.number if attempt else 0,
            data=game.data_paths(),
            elapsed=elapsed,
        )

    @staticmethod
    def _time_limit(platform_settings):
        return int(platform_settings.get("time_limit") or 0) * 60

    def _over_time(self, attempt, limit):
        return limit and (self.now() - attempt.started_at).total_seconds() > limit + TIME_GRACE_SECONDS

    def _close(self, attempt, status):
        attempt.status = status
        attempt.finished_at = self.now()
        attempt.seconds = (attempt.finished_at - attempt.started_at).total_seconds()
        self.store.attempt_save(attempt)

    def _attempt_info(self, attempt, all_attempts, counts):
        return {
            "id": attempt.id,
            "number": attempt.number,
            "status": attempt.status,
            "practice": ranking.is_practice(attempt, all_attempts, counts),
            "started_at": attempt.started_at.isoformat(),
            "score": ranking.num(attempt.score),
            "seconds": round(attempt.seconds, 1) if attempt.seconds is not None else None,
            "verified": bool(attempt.verified),
        }

    def _open_attempt(self, game, player, attempt_id):
        attempt = self.store.attempt_get(attempt_id)
        if attempt is None or attempt.user_id != player.id or attempt.game_key != game.key:
            raise PlatformError("That attempt doesn't exist.", "not_found", 404)
        if attempt.voided:
            raise PlatformError("A coach reset this game. Start again.", "reset", 409)
        if attempt.status != "started":
            raise PlatformError("This attempt is already over.", "attempt_over", 409)
        platform_settings, game_settings = self.settings(game, player.facility_id)
        if self._over_time(attempt, self._time_limit(platform_settings)):
            self._close(attempt, "expired")
            raise PlatformError("Time's up.", "time_up", 409)
        return attempt, platform_settings, game_settings

    # ---------------------------------------------------------- playing

    def start(self, game, player, resume=True):
        platform_settings, game_settings = self.settings(game, player.facility_id)
        counts = platform_settings.get("counts", "first")
        limit = self._time_limit(platform_settings)
        mine = self.store.attempts(game.key, player.facility_id, player.id)
        validator = self._validator(game)

        open_attempts = sorted([a for a in mine if a.status == "started" and not a.voided], key=lambda a: a.number)
        for a in open_attempts:
            age = (self.now() - a.started_at).total_seconds()
            if resume and a is open_attempts[-1] and not self._over_time(a, limit) and age < RESUME_HOURS * 3600:
                public = a.public
                if validator is not None:
                    public = validator.resume(self._ctx(game, a, game_settings), a.vstate, a.public)
                return {
                    "attempt": self._attempt_info(a, mine, counts),
                    "public": public,
                    "resumed": True,
                    "time_limit": limit or None,
                    "elapsed": round(age, 1),
                }
            self._close(a, "expired" if self._over_time(a, limit) else "abandoned")

        state, public = {}, {}
        if validator is not None:
            try:
                started = validator.start(self._ctx(game, None, game_settings))
            except ValidatorError as e:
                raise PlatformError(str(e), e.code)
            state, public = started.get("state", {}), started.get("public", {})
        number = max([a.number for a in mine] or [0]) + 1
        attempt = self.store.attempt_create(
            game_key=game.key,
            game_id=game.manifest.id,
            game_version=game.manifest.version,
            facility_id=player.facility_id,
            user_id=player.id,
            user_name=player.name,
            number=number,
            status="started",
            voided=False,
            started_at=self.now(),
            public=public,
            vstate=state,
            events=[],
            detail={},
        )
        mine = mine + [attempt]
        return {
            "attempt": self._attempt_info(attempt, mine, counts),
            "public": public,
            "resumed": False,
            "time_limit": limit or None,
            "elapsed": 0,
        }

    def event(self, game, player, attempt_id, type, data):
        if not isinstance(type, str) or not 0 < len(type) <= 40:
            raise PlatformError("Events need a short type name.", "bad_event")
        if _size(data) > MAX_EVENT_BYTES:
            raise PlatformError("That event is too large.", "bad_event")
        attempt, _platform, game_settings = self._open_attempt(game, player, attempt_id)
        events = attempt.events
        if len(events) >= MAX_EVENTS:
            raise PlatformError("Too many moves in one attempt.", "too_many_events")
        reply = {}
        validator = self._validator(game)
        if validator is not None:
            try:
                state, reply = validator.event(self._ctx(game, attempt, game_settings), attempt.vstate, type, data)
            except ValidatorError as e:
                raise PlatformError(str(e), e.code)
            attempt.vstate = state
        elapsed = (self.now() - attempt.started_at).total_seconds()
        attempt.events = events + [{"t": round(elapsed, 2), "type": type, "data": data}]
        self.store.attempt_save(attempt)
        return reply or {}

    def finish(self, game, player, attempt_id, claimed):
        claimed = claimed if isinstance(claimed, dict) else {}
        attempt, platform_settings, game_settings = self._open_attempt(game, player, attempt_id)
        scoring = game.manifest.scoring
        validator = self._validator(game)
        if validator is not None:
            try:
                outcome = validator.finish(self._ctx(game, attempt, game_settings), attempt.vstate, claimed)
            except ValidatorError as e:
                raise PlatformError(str(e), e.code)
            score, detail, verified = outcome.get("score"), outcome.get("detail") or {}, True
        else:
            score, detail, verified = claimed.get("score"), claimed.get("detail") or {}, False
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
        attempt.verified = verified
        self._close(attempt, "finished")
        return self._finish_payload(game, player, attempt, platform_settings)

    def _finish_payload(self, game, player, attempt, platform_settings):
        counts = platform_settings.get("counts", "first")
        mine = self.store.attempts(game.key, player.facility_id, player.id)
        payload = {"attempt": self._attempt_info(attempt, mine, counts), "counts": counts, "standing": None}
        scoring = game.manifest.scoring
        if scoring is None:
            return payload
        everyone = self.store.attempts(game.key, player.facility_id)
        ranked = ranking.ranked(everyone, scoring, counts)
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

    def call(self, game, player, method, params):
        validator = self._validator(game)
        if validator is None:
            raise PlatformError("This game has no server functions.", "unknown_method", 404)
        if not isinstance(method, str) or not 0 < len(method) <= 40 or _size(params) > MAX_EVENT_BYTES:
            raise PlatformError("Bad request.", "bad_request")
        _platform, game_settings = self.settings(game, player.facility_id)
        try:
            return validator.call(self._ctx(game, None, game_settings), method, params or {}) or {}
        except ValidatorError as e:
            raise PlatformError(str(e), e.code)

    # ---------------------------------------------------------- results

    def leaderboard(self, game, viewer, limit=20, user_ids=None):
        scoring = game.manifest.scoring
        if scoring is None:
            return {"rows": [], "visibility": "names", "counts": None}
        platform_settings, _ = self.settings(game, viewer.facility_id)
        counts = platform_settings.get("counts", "first")
        visibility = "names" if viewer.is_coach else platform_settings.get("leaderboard", "names")
        attempts = self.store.attempts(game.key, viewer.facility_id)
        if user_ids is not None:
            attempts = [a for a in attempts if a.user_id in user_ids]
        rows = ranking.leaderboard_rows(attempts, scoring, counts, viewer.id, visibility, limit)
        return {"rows": rows, "visibility": visibility, "counts": counts}

    def summary(self, game, player):
        """The player's own standing, for game cards and the hello message."""
        if game.manifest.is_lesson:
            mine = self.store.lesson_saves(game.content_ids, player.facility_id, player.id)
            return lessons.summary(game, mine)
        platform_settings, _ = self.settings(game, player.facility_id)
        counts = platform_settings.get("counts", "first")
        mine = [a for a in self.store.attempts(game.key, player.facility_id, player.id) if not a.voided]
        result = {"attempts": len(mine), "counted": None, "counts": counts}
        if game.manifest.scoring:
            a = ranking.counted_attempt(mine, game.manifest.scoring, counts)
            if a is not None:
                result["counted"] = {"score": ranking.num(a.score), "seconds": round(a.seconds or 0, 1), "number": a.number}
            first = ranking.first_attempt(mine)
            result["first_used"] = first is not None
        return result

    def scoreboards(self, game, viewer, user_ids=None):
        """Scoreboards of a Lesson Game, read from Kolibri's saved data."""
        if not game.manifest.is_lesson:
            raise PlatformError("This game has no scoreboards.", "not_lesson", 404)
        platform_settings, _ = self.settings(game, viewer.facility_id)
        visibility = "names" if viewer.is_coach else platform_settings.get("leaderboard", "names")
        saves = self.store.lesson_saves(game.content_ids, viewer.facility_id)
        if user_ids is not None:
            saves = [s for s in saves if s["user_id"] in user_ids]
        return lessons.scoreboards(game, saves, viewer.id, visibility)

    def my_attempts(self, game, player):
        platform_settings, _ = self.settings(game, player.facility_id)
        counts = platform_settings.get("counts", "first")
        mine = [a for a in self.store.attempts(game.key, player.facility_id, player.id) if not a.voided]
        return [self._attempt_info(a, mine, counts) for a in sorted(mine, key=lambda a: a.number)]

    def coach_results(self, game, facility_id, users=None):
        """Per-learner summaries. ``users`` is [(id, name)] to include even if they haven't played."""
        platform_settings, _ = self.settings(game, facility_id)
        counts = platform_settings.get("counts", "first")
        scoring = game.manifest.scoring
        attempts = self.store.attempts(game.key, facility_id)
        groups = ranking.by_user(attempts)
        rank_of = {}
        if scoring:
            for rank, a in ranking.ranked(attempts, scoring, counts):
                rank_of[a.user_id] = rank
        names = {}
        for a in attempts:
            names[a.user_id] = a.user_name
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
                    "last_played": max([a.started_at for a in live]).isoformat() if live else None,
                    "history": [
                        dict(self._attempt_info(a, live, counts), detail=a.detail, events=a.events)
                        for a in sorted(live, key=lambda a: a.number)
                    ],
                }
            )
        if scoring:
            rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, r["name"].lower()))
        return {"rows": rows, "counts": counts, "scoring": scoring}

    def reset(self, game, facility_id, user_id):
        self.store.attempts_void(game.key, facility_id, user_id)
        return {"ok": True}

    # ------------------------------------------------------------ state

    def get_state(self, game, player):
        return self.store.state_get(game.key, player.id)

    def set_state(self, game, player, data):
        if _size(data) > MAX_STATE_BYTES:
            raise PlatformError("Saved data is limited to 64 KB.", "too_large")
        self.store.state_set(game.key, player.id, data)
        return {"ok": True}


# ------------------------------------------------------------ in-memory


class MemoryRecord(object):
    def __init__(self, **fields):
        self.score = None
        self.seconds = None
        self.finished_at = None
        self.verified = False
        self.__dict__.update(fields)


class MemoryStore(Store):
    """Keeps everything in memory. Used by tests and the preview server."""

    def __init__(self):
        self._settings = {}
        self._attempts = []
        self._state = {}
        self._saves = []

    def settings_get(self, game_key, facility_id):
        return self._settings.get((game_key, facility_id))

    def settings_set(self, game_key, facility_id, platform, game, by_user_id):
        self._settings[(game_key, facility_id)] = {"platform": platform, "game": game}

    def attempts(self, game_key, facility_id, user_id=None):
        return [
            a
            for a in self._attempts
            if a.game_key == game_key and a.facility_id == facility_id and (user_id is None or a.user_id == user_id)
        ]

    def attempt_get(self, attempt_id):
        for a in self._attempts:
            if a.id == attempt_id:
                return a
        return None

    def attempt_create(self, **fields):
        record = MemoryRecord(id=len(self._attempts) + 1, **fields)
        self._attempts.append(record)
        return record

    def attempt_save(self, attempt):
        pass

    def attempts_void(self, game_key, facility_id, user_id):
        for a in self.attempts(game_key, facility_id, user_id):
            a.voided = True
            if a.status == "started":
                a.status = "abandoned"

    def state_get(self, game_key, user_id):
        return self._state.get((game_key, user_id))

    def state_set(self, game_key, user_id, data):
        self._state[(game_key, user_id)] = data

    def add_lesson_save(self, player, content_id, content_state):
        """Pretend a learner played a Lesson Game resource in Learn (tests and the preview server)."""
        self._saves = [
            s for s in self._saves if not (s["user_id"] == player.id and s["content_id"] == content_id)
        ]
        self._saves.append(
            {
                "user_id": player.id,
                "user_name": player.name,
                "facility_id": player.facility_id,
                "content_id": content_id,
                "content_state": content_state,
            }
        )

    def lesson_saves(self, content_ids, facility_id, user_id=None):
        wanted = set(content_ids)
        return [
            s
            for s in self._saves
            if s["content_id"] in wanted and s["facility_id"] == facility_id and (user_id is None or s["user_id"] == user_id)
        ]
