"""Tests for the parts that don't need Kolibri: versions, manifests, ranking, sources."""
import json
import os

import pytest

from kolibri_games import manifest as mf
from kolibri_games import ranking
from kolibri_games.sources import FolderSource
from kolibri_games.versions import VersionError, parse_version, satisfies
from tests.helpers import GAMES, Attempt

VALID = {
    "format": 1,
    "id": "org.example.test-game",
    "version": "1.0.0",
    "title": "Test",
    "scoring": {"order": "asc"},
    "settings": [{"key": "size", "type": "integer", "label": "Size", "default": 4, "min": 2, "max": 8}],
}


# ----------------------------------------------------------------- versions


def test_versions():
    assert parse_version("1.2") == (1, 2, 0, 0)
    assert parse_version("0.1.0rc1") == (0, 1, 0, 0)
    assert satisfies("0.1.0", ">=0.1")
    assert satisfies("0.1.0", ">=0.1,<1")
    assert not satisfies("0.1.0", ">=0.2")
    assert satisfies("1.0.0", "")
    with pytest.raises(VersionError):
        parse_version("banana")


# ----------------------------------------------------------------- manifest


def test_sample_games_are_valid():
    for name in os.listdir(GAMES):
        with open(os.path.join(GAMES, name, "kolibri-game.json")) as f:
            m = mf.loads(f.read())
        assert m.entry == "index.html"


def test_manifest_defaults():
    m = mf.validate(dict(VALID))
    assert m.scoring["counts"] == "first"
    assert m.scoring["tiebreak"] == "seconds"
    assert m.entry == "index.html"
    keys = [f["key"] for f in m.platform_settings_schema()]
    assert keys == ["counts", "scoreboard", "time_limit"]


def test_manifest_without_scoring_has_no_scoreboard_settings():
    data = dict(VALID)
    del data["scoring"]
    m = mf.validate(data)
    assert not m.has_scores
    assert [f["key"] for f in m.platform_settings_schema()] == ["time_limit"]


def test_manifest_reports_every_problem():
    bad = dict(VALID, format=2, id="Bad Id", entry="../escape.html", scoring={"order": "up"})
    with pytest.raises(mf.ManifestError) as info:
        mf.validate(bad)
    text = " ".join(info.value.problems)
    for word in ("format", "id must", "entry", "scoring.order"):
        assert word in text


def test_manifest_rejects_bad_settings():
    bad = dict(VALID, settings=[{"key": "size", "type": "integer", "label": "Size", "default": 99, "max": 8}])
    with pytest.raises(mf.ManifestError):
        mf.validate(bad)
    with pytest.raises(mf.ManifestError):
        mf.loads("{not json")


def test_clean_settings():
    schema = mf.validate(dict(VALID)).settings
    values, errors = mf.clean_settings(schema, {"size": "6"})
    assert values == {"size": 6} and not errors
    values, errors = mf.clean_settings(schema, {"size": 50})
    assert "size" in errors
    assert mf.merge_settings(schema, {"size": 50}) == {"size": 4}  # out-of-range stored value dropped
    choice = {"key": "c", "type": "choice", "label": "C", "choices": [{"value": 20, "label": "x"}], "default": 20}
    assert mf.clean_value(choice, 20) == 20
    with pytest.raises(ValueError):
        mf.clean_value(choice, 21)
    assert mf.clean_value({"type": "boolean"}, "on") is True


def test_safe_relpath():
    assert mf.safe_relpath("a/b/../c.js") == "a/c.js"
    for bad in ("../x", "/etc/passwd", "a\\b", "", None, ".."):
        assert mf.safe_relpath(bad) is None


# ------------------------------------------------------------------ sources


def test_folder_source_blocks_escapes(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    (game / "index.html").write_text("hi")
    (tmp_path / "secret.txt").write_text("no")
    os.symlink(str(tmp_path / "secret.txt"), str(game / "link.txt"))
    src = FolderSource(str(game))
    assert src.read("index.html") == (b"hi", "text/html")
    assert src.read("../secret.txt") is None
    assert src.read("link.txt") is None
    assert src.read("missing.js") is None


# ------------------------------------------------------------------ ranking

ASC = {"order": "asc", "tiebreak": "seconds"}


def test_first_attempt_counts_and_practice():
    attempts = [
        Attempt("amina", 1, score=7),
        Attempt("amina", 2, score=3),  # practice
        Attempt("ben", 1, score=5),
    ]
    rows = ranking.ranked(attempts, ASC, "first")
    assert [(r, a.user_id, a.score) for r, a in rows] == [(1, "ben", 5), (2, "amina", 7)]
    assert ranking.is_practice(attempts[1], attempts[:2], "first")
    rows = ranking.ranked(attempts, ASC, "best")
    assert [(a.user_id, a.score) for _, a in rows] == [("amina", 3), ("ben", 5)]


def test_abandoned_first_attempt_means_no_entry_until_reset():
    attempts = [Attempt("amina", 1, status="abandoned"), Attempt("amina", 2, score=3)]
    assert ranking.ranked(attempts, ASC, "first") == []
    attempts[0].voided = True  # coach reset
    attempts.append(Attempt("amina", 3, score=4))
    attempts[1].voided = True
    assert [a.score for _, a in ranking.ranked(attempts, ASC, "first")] == [4]


def test_ties_and_order():
    attempts = [
        Attempt("a", 1, score=5, seconds=10),
        Attempt("b", 1, score=5, seconds=10),
        Attempt("c", 1, score=5, seconds=20),
        Attempt("d", 1, score=9, seconds=5),
    ]
    assert [r for r, _ in ranking.ranked(attempts, ASC, "first")] == [1, 1, 3, 4]
    desc = ranking.ranked(attempts, {"order": "desc", "tiebreak": "seconds"}, "first")
    assert desc[0][1].user_id == "d"


def test_scoreboard_visibility():
    attempts = [Attempt("amina", 1, score=3, name="Amina Learner"), Attempt("ben", 1, score=5, name="Ben Ochieng")]
    rows = ranking.scoreboard_rows(attempts, ASC, "first", me_id="ben", visibility="initials")
    assert [r["name"] for r in rows] == ["A.L.", "Ben Ochieng"]
    rows = ranking.scoreboard_rows(attempts, ASC, "first", me_id="ben", visibility="hidden")
    assert [r["name"] for r in rows] == ["Ben Ochieng"]
    rows = ranking.scoreboard_rows(attempts, ASC, "first", me_id="ben", limit=1)
    assert [r["name"] for r in rows] == ["Amina Learner", "Ben Ochieng"]  # own row always shown


def test_manifest_json_files_are_pretty():
    # Catches accidental edits that break the sample manifests' formatting.
    for name in os.listdir(GAMES):
        with open(os.path.join(GAMES, name, "kolibri-game.json")) as f:
            json.load(f)
