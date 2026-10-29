"""Classroom Games: manifests, reading saved data, merging and ranking scoreboards."""
import json
import os
import zipfile

import pytest

from kolibri_games import classroom
from kolibri_games import manifest as mf
from kolibri_games.registry import check
from kolibri_games.service import GameService, MemoryStore, Player
from kolibri_games.sources import FolderSource, ZipSource

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(ROOT, "examples", "classroom-games")
FACILITY = "f" * 32
AMINA = Player("a" * 32, "Amina Learner", FACILITY)
BEN = Player("b" * 32, "Ben Learner", FACILITY)
COACH = Player("c" * 32, "Ms Coach", FACILITY, is_coach=True)


def example(name):
    return FolderSource(os.path.join(EXAMPLES, name)).manifest()


def resource(name, content_id, title):
    source = FolderSource(os.path.join(EXAMPLES, name))
    return classroom.ClassroomResource(source, source.manifest(), {"content_id": content_id, "node_id": "n" + content_id[1:], "title": title})


def scorm(data):
    """Kolibri's saved state for an HTML5 app: SCORM keys nested at the dots."""
    return {"SCORM": {"cmi": {"suspend_data": json.dumps(data), "core": {"lesson_status": "passed"}}}}


def save(store, player, content_id, data):
    store.add_classroom_save(player, content_id, scorm(data))


# ----------------------------------------------------------------- manifest


def test_example_manifests_are_valid_classroom_games():
    for name in ("lit", "singe"):
        m = example(name)
        assert m.is_classroom and m.scoreboards["rank_by"]
        assert [f["key"] for f in m.platform_settings_schema()] == ["leaderboard"]
        assert m.platform_settings_schema()[0]["default"] == "names"


def test_classroom_manifest_problems_are_reported():
    base = json.load(open(os.path.join(EXAMPLES, "lit", "kolibri-game.json")))
    bad = dict(base, validator="number-hunt", scoring={"order": "asc"})
    with pytest.raises(mf.ManifestError) as e:
        mf.validate(bad)
    assert any("can't use 'validator'" in p for p in e.value.problems)
    sb = dict(base["scoreboards"], rank_by=["nope"], fields=[{"key": "acc", "label": "Accuracy", "combine": "average"}])
    with pytest.raises(mf.ManifestError) as e:
        mf.validate(dict(base, scoreboards=sb))
    text = " ".join(e.value.problems)
    assert "combine" in text and "'nope' isn't one of the fields" in text
    with pytest.raises(mf.ManifestError):
        mf.validate(dict(base, scoreboards=None))
    with pytest.raises(mf.ManifestError):
        mf.validate(dict(base, type="arcade"))


def test_free_play_games_cant_have_scoreboards_and_classroom_games_arent_playable_locally():
    data = json.load(open(os.path.join(ROOT, "games", "number-hunt", "kolibri-game.json")))
    with pytest.raises(mf.ManifestError):
        mf.validate(dict(data, scoreboards={}))
    m = example("lit")
    assert "Classroom Game" in check(m, FolderSource(os.path.join(EXAMPLES, "lit")))[0]


# ----------------------------------------------------------- reading data


def test_suspend_data_is_read_from_nested_or_flat_scorm_keys():
    assert classroom.suspend_data(scorm({"a": 1})) == {"a": 1}
    assert classroom.suspend_data({"SCORM": {"cmi.suspend_data": '{"b": 2}'}}) == {"b": 2}
    for broken in (None, {}, {"SCORM": {}}, {"SCORM": {"cmi": {"suspend_data": "not json"}}},
                   {"SCORM": {"cmi": {"suspend_data": "[1, 2]"}}}, {"SCORM": {"cmi": {"suspend_data": "x" * 70000}}}):
        assert classroom.suspend_data(broken) is None


def test_reading_lit_skips_unfinished_lessons():
    spec = example("lit").scoreboards
    found = classroom.read_boards(spec, scorm({"en-01": {"done": 1, "acc": 96, "wpm": 14}, "en-02": {"done": 0, "acc": 0, "wpm": 0}}))
    assert found == {"en-01": {"acc": 96, "wpm": 14}}


def test_reading_singe_lists_by_position_and_ignores_junk():
    spec = example("singe").scoreboards
    found = classroom.read_boards(spec, scorm({"us": [92, 140, 5], "us_flags": ["70", 99.5, 1], "bad": "x", "": [1, 2, 3]}))
    assert found == {"us": {"acc": 92, "time": 140, "plays": 5}, "us_flags": {"acc": 70, "time": 99.5, "plays": 1}}


def test_board_names_from_rules_and_names():
    spec = example("singe").scoreboards
    assert classroom.board_name(spec, "us") == "United States: regions"
    assert classroom.board_name(spec, "us_capitals") == "United States: capitals"
    assert classroom.board_name(spec, "world_all_flags") == "World (all countries): flags"
    assert classroom.board_name(spec, "mars_flags") == "mars: flags"
    assert classroom.board_name(example("lit").scoreboards, "en-01") is None


# ---------------------------------------------------------- scoreboards


def singe_game():
    return classroom.group_resources([resource("singe", "4" * 32, "Maps of Sierra Leone"), resource("singe", "5" * 32, "Maps of the world")])[0]


def test_reused_boards_merge_best_result_and_add_up_plays():
    game = singe_game()
    store = MemoryStore()
    save(store, AMINA, "4" * 32, {"sierra_leone": [92, 140, 5]})
    save(store, AMINA, "5" * 32, {"sierra_leone": [100, 300, 1]})
    save(store, BEN, "4" * 32, {"sierra_leone": [100, 200, 2]})
    data = GameService(store).scoreboards(game, AMINA)
    board = data["boards"][0]
    assert board["name"] == "Sierra Leone: regions" and board["players"] == 2
    assert [r["name"] for r in board["rows"]] == ["Ben Learner", "Amina Learner"]  # same accuracy, Ben was faster
    assert board["rows"][1]["values"] == {"acc": 100, "time": 300, "plays": 6}
    assert board["mine"]["rank"] == 2
    assert {r["title"] for r in board["resources"]} == {"Maps of Sierra Leone", "Maps of the world"}


def test_speed_ranks_higher_first_and_time_ranks_lower_first():
    lit = classroom.group_resources([resource("lit", "1" * 32, "Lesson 1")])[0]
    store = MemoryStore()
    save(store, AMINA, "1" * 32, {"en-01": {"done": 1, "acc": 95, "wpm": 12}})
    save(store, BEN, "1" * 32, {"en-01": {"done": 1, "acc": 95, "wpm": 20}})
    rows = GameService(store).scoreboards(lit, COACH)["boards"][0]["rows"]
    assert [r["name"] for r in rows] == ["Ben Learner", "Amina Learner"]  # same accuracy, more wpm wins
    store = MemoryStore()
    save(store, AMINA, "4" * 32, {"us": [95, 90, 1]})
    save(store, BEN, "4" * 32, {"us": [95, 60, 1]})
    rows = GameService(store).scoreboards(singe_game(), COACH)["boards"][0]["rows"]
    assert [r["name"] for r in rows] == ["Ben Learner", "Amina Learner"]  # same accuracy, less time wins


def test_ties_share_a_rank_and_missing_values_rank_last():
    game = singe_game()
    store = MemoryStore()
    save(store, AMINA, "4" * 32, {"us": [90, 100, 1]})
    save(store, BEN, "4" * 32, {"us": [90, 100, 1]})
    save(store, COACH, "4" * 32, {"us": [None, None, 4]})
    rows = GameService(store).scoreboards(game, COACH)["boards"][0]["rows"]
    assert [r["rank"] for r in rows] == [1, 1, 3]


def test_visibility_setting_applies_to_learners_but_not_coaches():
    game = singe_game()
    store = MemoryStore()
    service = GameService(store)
    save(store, AMINA, "4" * 32, {"us": [80, 100, 1]})
    save(store, BEN, "4" * 32, {"us": [90, 100, 1]})
    rows = service.scoreboards(game, AMINA)["boards"][0]["rows"]
    assert [r["name"] for r in rows] == ["Ben Learner", "Amina Learner"]  # full names by default
    service.save_settings(game, FACILITY, {"leaderboard": "initials"}, {}, COACH.id)
    assert [r["name"] for r in service.scoreboards(game, AMINA)["boards"][0]["rows"]] == ["B.L.", "Amina Learner"]
    service.save_settings(game, FACILITY, {"leaderboard": "hidden"}, {}, COACH.id)
    rows = service.scoreboards(game, AMINA)["boards"][0]["rows"]
    assert [(r["rank"], r["name"]) for r in rows] == [(2, "Amina Learner")]
    assert len(service.scoreboards(game, COACH)["boards"][0]["rows"]) == 2


def test_class_filter_and_other_facilities():
    game = singe_game()
    store = MemoryStore()
    save(store, AMINA, "4" * 32, {"us": [80, 100, 1]})
    save(store, BEN, "4" * 32, {"us": [90, 100, 1]})
    save(store, Player("e" * 32, "Elsewhere", "9" * 32), "4" * 32, {"us": [99, 1, 1]})
    data = GameService(store).scoreboards(game, COACH, user_ids={AMINA.id})
    assert [r["name"] for r in data["boards"][0]["rows"]] == ["Amina Learner"]


def test_lit_boards_are_named_after_their_resource_and_summary_counts_mine():
    game = classroom.group_resources([resource("lit", "1" * 32, "Lesson 1: Left-hand home keys"), resource("lit", "2" * 32, "Lesson 10: Numbers")])[0]
    store = MemoryStore()
    service = GameService(store)
    save(store, AMINA, "1" * 32, {"en-01": {"done": 1, "acc": 96, "wpm": 14}})
    save(store, BEN, "2" * 32, {"en-10": {"done": 1, "acc": 90, "wpm": 20}, "fr-10": {"done": 1, "acc": 80, "wpm": 10}})
    names = [b["name"] for b in service.scoreboards(game, AMINA)["boards"]]
    assert names == ["Lesson 1: Left-hand home keys", "Lesson 10: Numbers (en-10)", "Lesson 10: Numbers (fr-10)"]
    assert service.summary(game, AMINA) == {"boards": 1, "resources": 2}


def test_resources_group_into_one_game_per_id_using_the_newest_manifest():
    old = json.load(open(os.path.join(EXAMPLES, "singe", "kolibri-game.json")))
    old["version"] = "0.1.0"
    old["title"] = "Old title"
    old["scoreboards"]["board_names"] = {"mars": "Mars"}
    old_m = mf.validate(old)
    new = resource("singe", "5" * 32, "World")
    older = classroom.ClassroomResource(new.source, old_m, {"content_id": "6" * 32, "node_id": "x", "title": "Mars maps"})
    copy = resource("singe", "5" * 32, "World (copy in another channel)")
    games = classroom.group_resources([older, new, copy, resource("lit", "1" * 32, "Lesson 1")])
    singe = [g for g in games if g.manifest.id == "org.togetherings.singe"][0]
    assert singe.key == "g-org.togetherings.singe" and singe.title == "Studies In Geography"
    assert sorted(singe.content_ids) == ["5" * 32, "6" * 32]
    assert classroom.board_name(singe.spec, "mars_flags") == "Mars: flags"
    assert len(games) == 2


def test_zip_source_reads_the_manifest(tmp_path):
    path = str(tmp_path / "lit.zip")
    with zipfile.ZipFile(path, "w") as z:
        z.write(os.path.join(EXAMPLES, "lit", "kolibri-game.json"), "kolibri-game.json")
        z.writestr("index.html", "<p>hi</p>")
    source = ZipSource(path)
    assert source.has_manifest() and source.manifest().id == "org.togetherings.lit"
    assert source.read("../etc/passwd") is None and source.read("index.html")[1] == "text/html"
    plain = str(tmp_path / "plain.zip")
    with zipfile.ZipFile(plain, "w") as z:
        z.writestr("index.html", "<p>hi</p>")
    assert not ZipSource(plain).has_manifest()
    assert not ZipSource(str(tmp_path / "missing.zip")).has_manifest()
