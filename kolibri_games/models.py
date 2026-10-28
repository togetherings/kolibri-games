"""
Database tables. Learners and facilities are stored by their Kolibri ids
(32-character hex strings) rather than foreign keys, so these migrations never
depend on the migration history of Kolibri's own apps.
"""
import json

from django.db import models


def _json_property(field):
    def getter(self):
        return json.loads(getattr(self, field) or "null")

    def setter(self, value):
        setattr(self, field, json.dumps(value, separators=(",", ":")))

    return property(getter, setter)


class GameSettings(models.Model):
    """Coach-chosen settings for one game in one facility."""

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


class Attempt(models.Model):
    """One play of one game by one learner."""

    STATUSES = ("started", "finished", "abandoned", "expired")

    id = models.AutoField(primary_key=True)
    game_key = models.CharField(max_length=120)
    game_id = models.CharField(max_length=100)
    game_version = models.CharField(max_length=40)
    facility_id = models.CharField(max_length=32)
    user_id = models.CharField(max_length=32)
    user_name = models.CharField(max_length=255)
    number = models.PositiveIntegerField()
    status = models.CharField(max_length=12, default="started")
    voided = models.BooleanField(default=False)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    seconds = models.FloatField(null=True, blank=True)
    score = models.FloatField(null=True, blank=True)
    verified = models.BooleanField(default=False)
    public_json = models.TextField(default="{}")
    vstate_json = models.TextField(default="{}")
    events_json = models.TextField(default="[]")
    detail_json = models.TextField(default="{}")

    class Meta:
        indexes = [
            models.Index(fields=["game_key", "facility_id", "user_id"], name="kg_attempt_player"),
            models.Index(fields=["game_key", "facility_id", "status"], name="kg_attempt_status"),
        ]

    public = _json_property("public_json")
    vstate = _json_property("vstate_json")
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
