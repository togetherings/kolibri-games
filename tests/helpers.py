import os
from datetime import datetime, timedelta, timezone

from kolibri_games.registry import GameEntry, check
from kolibri_games.sources import FolderSource

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAMES = os.path.join(ROOT, "games")  # the games this repository ships (Server Games)
#: Games used only by the tests: Number Hunt and Memory Match (Scored Games that use the
#: plugin's SDK directly; the real ones live in edugame-kit) and a Saved Game.
TEST_GAMES = os.path.join(ROOT, "tests", "fixtures", "games")
ALL_GAME_DIRS = (GAMES, TEST_GAMES)


def game_dir(name):
    for base in ALL_GAME_DIRS:
        if os.path.isdir(os.path.join(base, name)):
            return os.path.join(base, name)
    raise KeyError(name)


def all_games():
    return [os.path.join(base, n) for base in ALL_GAME_DIRS for n in sorted(os.listdir(base))]


def folder_game(name):
    source = FolderSource(game_dir(name))
    manifest = source.manifest()
    return GameEntry("g-" + manifest.id, source, "folder", manifest, check(manifest, source))


class Clock(object):
    def __init__(self):
        self.t = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += timedelta(seconds=seconds)


class Attempt(object):
    """Minimal attempt record for ranking tests."""

    _ids = 0

    def __init__(self, user_id, number, score=None, seconds=10, status="finished", voided=False, name=None, minute=0,
                 values=None, board=""):
        Attempt._ids += 1
        self.values = values or {}
        self.board = board
        self.id = Attempt._ids
        self.user_id = user_id
        self.user_name = name or user_id.title()
        self.number = number
        self.score = score
        self.seconds = seconds
        self.status = status
        self.voided = voided
        self.finished_at = datetime(2026, 1, 1, 9, minute, tzinfo=timezone.utc)
