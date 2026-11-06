"""Tests for the parts that don't need Kolibri: versions, manifests, ranking, sources."""
import json
import os

import pytest

from kolibri_games import manifest as mf
from kolibri_games import ranking
from kolibri_games import scoring as sc
from kolibri_games.sources import FolderSource
from kolibri_games.versions import VersionError, parse_version, satisfies
from tests.helpers import GAMES, Attempt, all_games

VALID = {
    "format": 1,
    "type": "scored",
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
    for folder in all_games():
        with open(os.path.join(folder, "kolibri-game.json")) as f:
            m = mf.loads(f.read())
        assert m.entry == "index.html"


def test_manifest_defaults():
    m = mf.validate(dict(VALID))
    assert m.scoring["counts"] == "first"
    assert m.scoring["rank_by"] == ["score", "time"] and m.scoring["fields"][1]["source"] == "time"
    assert m.entry == "index.html"
    keys = [f["key"] for f in m.platform_settings_schema()]
    assert keys == ["counts", "scoreboard", "time_limit"]


def test_manifest_without_scoring_has_no_scoreboard_settings():
    data = dict(VALID, type="saved")
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

def spec(scoring):
    problems = []
    out = sc.check(scoring, problems)
    assert not problems, problems
    return out


ASC = spec({"order": "asc", "tiebreak": "seconds"})


def scores(rows):
    return [(place, r.user_id, r.values.get("score")) for place, r in rows]


def test_first_attempt_counts_and_practice():
    attempts = [
        Attempt("amina", 1, score=7),
        Attempt("amina", 2, score=3),  # practice
        Attempt("ben", 1, score=5),
    ]
    assert scores(ranking.ranked(attempts, ASC, "first")) == [(1, "ben", 5), (2, "amina", 7)]
    assert ranking.is_practice(attempts[1], attempts[:2], "first")
    assert scores(ranking.ranked(attempts, ASC, "best")) == [(1, "amina", 3), (2, "ben", 5)]
    assert scores(ranking.ranked(attempts, ASC, "latest")) == [(1, "amina", 3), (2, "ben", 5)]
    total = ranking.ranked(attempts, spec({"order": "desc", "tiebreak": "none"}), "total")
    assert scores(total) == [(1, "amina", 10), (2, "ben", 5)]  # every attempt added up (like Sparkle's points)


def test_abandoned_first_attempt_means_no_entry_until_reset():
    attempts = [Attempt("amina", 1, status="abandoned"), Attempt("amina", 2, score=3)]
    assert ranking.ranked(attempts, ASC, "first") == []
    attempts[0].voided = True  # coach reset
    attempts.append(Attempt("amina", 3, score=4))
    attempts[1].voided = True
    assert [r.values["score"] for _, r in ranking.ranked(attempts, ASC, "first")] == [4]


def test_ties_and_order():
    attempts = [
        Attempt("a", 1, score=5, seconds=10),
        Attempt("b", 1, score=5, seconds=10),
        Attempt("c", 1, score=5, seconds=20),
        Attempt("d", 1, score=9, seconds=5),
    ]
    assert [r for r, _ in ranking.ranked(attempts, ASC, "first")] == [1, 1, 3, 4]
    desc = ranking.ranked(attempts, spec({"order": "desc", "tiebreak": "seconds"}), "first")
    assert desc[0][1].user_id == "d"
    # Without a time tiebreak, equal scores share a place.
    assert [r for r, _ in ranking.ranked(attempts, spec({"order": "asc", "tiebreak": "none"}), "first")] == [1, 1, 1, 4]


def test_scoreboard_visibility():
    attempts = [Attempt("amina", 1, score=3, name="Amina Learner"), Attempt("ben", 1, score=5, name="Ben Ochieng")]
    ranked = ranking.ranked(attempts, ASC, "first")
    rows = ranking.rows(ASC, ranked, me_id="ben", visibility="initials")
    assert [r["name"] for r in rows] == ["A.L.", "Ben Ochieng"]
    assert rows[0]["score"] == 3 and rows[0]["seconds"] == 10 and rows[0]["values"] == {"score": 3, "time": 10}
    rows = ranking.rows(ASC, ranked, me_id="ben", visibility="hidden")
    assert [r["name"] for r in rows] == ["Ben Ochieng"]
    rows = ranking.rows(ASC, ranked, me_id="ben", limit=1)
    assert [r["name"] for r in rows] == ["Amina Learner", "Ben Ochieng"]  # own row always shown


# Like Lessons In Typing: accuracy first, then speed, both higher is better, no time.
TYPING = spec({
    "fields": [
        {"key": "acc", "label": "Accuracy", "unit": "%", "order": "desc", "total": "average"},
        {"key": "wpm", "label": "Speed", "unit": "wpm", "order": "desc", "total": "average"},
        {"key": "plays", "label": "Times played", "source": "plays"},
    ],
    "rank_by": ["acc", "wpm"],
    "counts": "best",
    "boards": {"label": "Lesson", "total": {"label": "All lessons"}},
})


def test_two_scores_each_ranked_its_own_way():
    attempts = [
        Attempt("amina", 1, values={"acc": 95, "wpm": 30}),
        Attempt("amina", 2, values={"acc": 98, "wpm": 22}),
        Attempt("ben", 1, values={"acc": 98, "wpm": 35}),
        Attempt("cara", 1, values={"acc": 98, "wpm": 35}),
    ]
    rows = ranking.ranked(attempts, TYPING, "best")
    assert [(p, r.user_id, r.values["acc"], r.values["wpm"]) for p, r in rows] == [
        (1, "ben", 98, 35), (1, "cara", 98, 35), (3, "amina", 98, 22)]
    assert rows[2][1].values["plays"] == 2  # the best attempt, from the same round, and how many rounds
    # A lower-is-better first score with a higher-is-better tiebreak.
    mixed = spec({"fields": [{"key": "misses", "label": "Misses", "order": "asc"},
                             {"key": "points", "label": "Points", "order": "desc"}], "rank_by": ["misses", "points"]})
    rows = ranking.ranked([Attempt("a", 1, values={"misses": 1, "points": 5}),
                           Attempt("b", 1, values={"misses": 1, "points": 9}),
                           Attempt("c", 1, values={"misses": 0, "points": 1})], mixed, "first")
    assert [r.user_id for _, r in rows] == ["c", "b", "a"]


def test_levels_have_their_own_boards_and_a_total():
    attempts = [
        Attempt("amina", 1, values={"acc": 90, "wpm": 20}, board="en-01"),
        Attempt("amina", 2, values={"acc": 100, "wpm": 30}, board="en-02"),
        Attempt("ben", 1, values={"acc": 99, "wpm": 40}, board="en-01"),
    ]
    per_board = {}
    for board, mine in ranking.by_board(attempts).items():
        per_board[board] = [r for r in (ranking.counted(m, TYPING, "best") for m in ranking.by_user(mine).values()) if r]
    assert [r.user_id for _, r in ranking.ranked(ranking.by_board(attempts)["en-01"], TYPING, "best")] == ["ben", "amina"]
    total = sc.total_spec(TYPING)
    assert total["rank_by"] == ["boards", "acc", "wpm"] and total["fields"][0]["label"] == "Lessons played"
    rows = ranking.totals(per_board, total)
    assert [(p, r.user_id, r.values["boards"], r.values["acc"], r.values["plays"]) for p, r in rows] == [
        (1, "amina", 2, 95, 2), (2, "ben", 1, 99, 1)]


def test_scoring_problems_are_reported():
    for bad, why in [
        ({"fields": [{"key": "a", "label": "A"}], "rank_by": ["a"]}, "give the field 'a' an order"),
        ({"fields": [{"key": "a", "label": "A", "order": "up"}], "rank_by": ["a"]}, "order must be"),
        ({"fields": [{"key": "a", "label": "A", "order": "asc"}], "rank_by": ["b"]}, "'b' isn't one of the fields"),
        ({"fields": [{"key": "t", "label": "T", "source": "time", "order": "asc"}], "rank_by": ["t"]}, "first field must be one the game reports"),
        ({"fields": [{"key": "a", "label": "A", "order": "asc", "total": "mean"}], "rank_by": ["a"]}, "total must be one of"),
        ({"order": "asc", "counts": "most"}, "counts must be one of"),
        ({"fields": [{"key": "a", "label": "A", "order": "asc"}], "rank_by": ["a"], "order": "asc"}, "give each field its own order"),
        ({"order": "asc", "boards": {"names": "x"}}, "boards.names"),
    ]:
        problems = []
        sc.check(bad, problems)
        assert any(why in p for p in problems), (why, problems)


def test_reported_values_are_checked():
    assert sc.check_values(TYPING, {"values": {"acc": 97, "wpm": 41, "extra": 1}}) == {"acc": 97, "wpm": 41}
    assert sc.check_values(ASC, {"score": 4}) == {"score": 4}
    for bad in ({"values": {"acc": 97}}, {"values": {"acc": "97", "wpm": 1}}, {"score": None}, {}):
        with pytest.raises(ValueError):
            sc.check_values(TYPING if "values" in bad else ASC, bad)
    with pytest.raises(ValueError):
        sc.check_values(spec({"order": "asc", "max": 10}), {"score": 11})


def test_manifest_json_files_are_pretty():
    # Catches accidental edits that break the sample manifests' formatting.
    for folder in all_games():
        with open(os.path.join(folder, "kolibri-game.json")) as f:
            json.load(f)


def test_the_three_kinds_of_game():
    saved = dict(VALID, type="saved")
    del saved["scoring"]
    assert mf.validate(saved).channel_spec is None and mf.validate(saved).in_channels
    for bad, why in [
        (dict(VALID, type="free-play"), "type must be 'saved', 'scored' or 'server'"),
        (dict(VALID, type="saved"), "Saved Games don't keep scores"),
        (dict(VALID, type="scored", scoring=None), "Scored Games need a scoring section"),
        (dict(VALID, type="scored", service="photo-guess"), "Only Server Games"),
        (dict(VALID, type="server"), "Server Games need a service"),
        (dict(VALID, type="scored", data=[{"name": "wikipedia"}]), "'data' is only for Server Games"),
    ]:
        with pytest.raises(mf.ManifestError) as e:
            mf.validate(bad)
        assert any(why in p for p in e.value.problems), (why, e.value.problems)
    server = mf.validate(json.load(open(os.path.join(GAMES, "wiki-blaze", "kolibri-game.json"))))
    assert server.is_server and not server.in_channels


def test_kit_games_get_scoreboards_from_their_scoring():
    m = mf.validate(dict(VALID, scoring={"label": "Guesses", "order": "asc", "tiebreak": "seconds"}))
    spec_ = m.channel_spec
    assert [f["key"] for f in spec_["fields"]] == ["score", "time"] and [f["from"] for f in spec_["fields"]] == [0, 1]
    assert spec_["rank_by"] == ["score", "time"] and spec_["fields"][0]["order"] == "asc"
    assert spec_["fields"][0]["label"] == "Guesses" and spec_["saved_data"]["format"] == "kit"
    assert mf.validate(dict(VALID, languages=["en", "fr", "pt-BR"])).languages == ["en", "fr", "pt-BR"]
    with pytest.raises(mf.ManifestError):
        mf.validate(dict(VALID, languages=["English"]))
