import os
from datetime import datetime, timedelta, timezone

from kolibri_games.registry import GameEntry, check
from kolibri_games.sources import FolderSource

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAMES = os.path.join(ROOT, "games")


def folder_game(name):
    source = FolderSource(os.path.join(GAMES, name))
    manifest = source.manifest()
    return GameEntry("l-" + manifest.id, source, "local", manifest, check(manifest, source))


class Clock(object):
    def __init__(self):
        self.t = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += timedelta(seconds=seconds)


class Attempt(object):
    """Minimal attempt record for ranking tests."""

    def __init__(self, user_id, number, score=None, seconds=10, status="finished", voided=False, name=None, minute=0):
        self.user_id = user_id
        self.user_name = name or user_id.title()
        self.number = number
        self.score = score
        self.seconds = seconds
        self.status = status
        self.voided = voided
        self.verified = True
        self.finished_at = datetime(2026, 1, 1, 9, minute, tzinfo=timezone.utc)
