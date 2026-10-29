"""
Database tables. Learners, classes and facilities are stored by their Kolibri
ids (32-character hex strings) rather than foreign keys, so these migrations
never depend on the migration history of Kolibri's own apps.

Classroom Games add no tables: their scores are read from Kolibri's own
records (see store_django.classroom_saves).
"""
import json

from django.db import models


def _json_property(field):
    """A Python value stored as JSON text in ``field``."""

    def getter(self):
        return json.loads(getattr(self, field) or "null")

    def setter(self, value):
        setattr(self, field, json.dumps(value, separators=(",", ":")))

    return property(getter, setter)


class GameSettings(models.Model):
    """Coach-chosen settings for one game in one facility (used for free play)."""

    id = models.AutoField(primary_key=True)
    game_key = models.CharField(max_length=120)
    facility_id = models.CharField(max_length=32)
    platform_json = models.TextField(default="{}")
    game_json = models.TextField(default="{}")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by_id = models.CharField(max_length=32, blank=True)

    class Meta:
        unique_together = [("game_key", "facility_id")]

    platform = _json_property("platform_json")
    game = _json_property("game_json")


class Challenge(models.Model):
    """A game set up by a coach for one class, with its own settings and dates."""

    id = models.AutoField(primary_key=True)
    game_key = models.CharField(max_length=120)
    facility_id = models.CharField(max_length=32)
    class_id = models.CharField(max_length=32)
    class_name = models.CharField(max_length=255)
    title = models.CharField(max_length=100)
    settings_json = models.TextField(default="{}")
    counts = models.CharField(max_length=8, default="first")
    time_limit = models.PositiveIntegerField(default=0)  # minutes, 0 for none
    opens_at = models.DateTimeField()
    closes_at = models.DateTimeField(null=True, blank=True)
    created_by_id = models.CharField(max_length=32, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    best_json = models.TextField(default="{}")  # Wiki BLAZE: the shortest route, worked out in the background

    class Meta:
        indexes = [models.Index(fields=["facility_id", "game_key"], name="kg_challenge_game")]

    settings = _json_property("settings_json")
    best = _json_property("best_json")


class Attempt(models.Model):
    """One play of one game by one learner, in free play (challenge_id empty) or in a challenge."""

    STATUSES = ("started", "finished", "abandoned", "expired")

    id = models.AutoField(primary_key=True)
    game_key = models.CharField(max_length=120)
    game_id = models.CharField(max_length=100)
    game_version = models.CharField(max_length=40)
    facility_id = models.CharField(max_length=32)
    user_id = models.CharField(max_length=32)
    user_name = models.CharField(max_length=255)
    challenge_id = models.IntegerField(null=True, blank=True)
    number = models.PositiveIntegerField()
    status = models.CharField(max_length=12, default="started")
    voided = models.BooleanField(default=False)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    seconds = models.FloatField(null=True, blank=True)
    score = models.FloatField(null=True, blank=True)
    public_json = models.TextField(default="{}")
    state_json = models.TextField(default="{}")  # kept by the server (e.g. a Wiki BLAZE chain)
    events_json = models.TextField(default="[]")  # every move, for coaches
    detail_json = models.TextField(default="{}")

    class Meta:
        indexes = [
            models.Index(fields=["game_key", "facility_id", "challenge_id", "user_id"], name="kg_attempt_player"),
        ]

    public = _json_property("public_json")
    state = _json_property("state_json")
    events = _json_property("events_json")
    detail = _json_property("detail_json")


class PlayerState(models.Model):
    """Saved data a game keeps for a learner between visits (e.g. unlocked levels)."""

    id = models.AutoField(primary_key=True)
    game_key = models.CharField(max_length=120)
    user_id = models.CharField(max_length=32)
    data_json = models.TextField(default="null")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("game_key", "user_id")]

    data = _json_property("data_json")


class ArticleList(models.Model):
    """A coach's list of Wikipedia articles for Wiki BLAZE challenges (one title per line)."""

    id = models.AutoField(primary_key=True)
    facility_id = models.CharField(max_length=32)
    name = models.CharField(max_length=100)
    titles = models.TextField(default="")
    created_by_id = models.CharField(max_length=32, blank=True)
    updated_at = models.DateTimeField()
