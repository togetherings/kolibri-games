"""Scored Games in channels: manifests, reading saved data, merging and ranking scoreboards."""
import json
import os
import zipfile

import pytest

from kolibri_games import channel
from kolibri_games import manifest as mf
from kolibri_games.registry import check
from kolibri_games.service import GameService, MemoryStore, Player
from kolibri_games.sources import FolderSource, ZipSource

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(ROOT, "examples", "channel-games")
FACILITY = "f" * 32
AMINA = Player("a" * 32, "Amina Learner", FACILITY)
BEN = Player("b" * 32, "Ben Learner", FACILITY)
COACH = Player("c" * 32, "Ms Coach", FACILITY, is_coach=True)


def example(name):
    return FolderSource(os.path.join(EXAMPLES, name)).manifest()


def resource(name, content_id, title):
    source = FolderSource(os.path.join(EXAMPLES, name))
    return channel.ChannelResource(source, source.manifest(), {"content_id": content_id, "node_id": "n" + content_id[1:], "title": title})


def scorm(data):
    """Kolibri's saved state for an HTML5 app: SCORM keys nested at the dots."""
    return {"SCORM": {"cmi": {"suspend_data": json.dumps(data), "core": {"lesson_status": "passed"}}}}


def save(store, player, content_id, data):
    store.add_channel_save(player, content_id, scorm(data))


def boards(data):
    """The boards of a scoreboards result, without the total."""
    return [b for b in data["boards"] if not b.get("total")]


# ----------------------------------------------------------------- manifest


def test_example_manifests_are_valid_scored_games():
    for name in ("lit", "singe"):
        m = example(name)
        assert m.type == "scored" and m.scoring["rank_by"] and m.channel_spec is m.scoring
        assert m.scoring["saved_data"]["format"] == "own" and m.scoring["boards"]["total"]
        assert [f["key"] for f in m.platform_settings_schema(in_channel=True)] == ["scoreboard"]
        assert m.platform_settings_schema(in_channel=True)[0]["default"] == "names"


def test_scoreboards_problems_are_reported():
    base = json.load(open(os.path.join(EXAMPLES, "lit", "kolibri-game.json")))
    bad = dict(base, service="wikipedia-race", scoring={"order": "asc"})
    with pytest.raises(mf.ManifestError) as e:
        mf.validate(bad)
    assert any("Only Server Games" in p for p in e.value.problems)
    sc = dict(base["scoring"], rank_by=["nope"], fields=[{"key": "acc", "label": "Accuracy", "total": "mean"}])
    with pytest.raises(mf.ManifestError) as e:
        mf.validate(dict(base, scoring=sc))
    text = " ".join(e.value.problems)
    assert "total must be one of" in text and "'nope' isn't one of the fields" in text
    with pytest.raises(mf.ManifestError):  # a Scored Game needs scoring
        mf.validate(dict(base, scoring=None))
    with pytest.raises(mf.ManifestError) as e:  # the old name
        mf.validate(dict(base, scoreboards={}))
    assert "now part of scoring" in " ".join(e.value.problems)
    with pytest.raises(mf.ManifestError):
        mf.validate(dict(base, type="arcade"))


def test_only_scored_games_read_saved_data_and_saved_games_have_no_scores():
    data = json.load(open(os.path.join(ROOT, "games", "wiki-blaze", "kolibri-game.json")))
    with pytest.raises(mf.ManifestError) as e:  # a Server Game isn't in channels
        mf.validate(dict(data, scoring=dict(data["scoring"], saved_data={"in": "scorm"})))
    assert "only for Scored Games in channels" in " ".join(e.value.problems)
    saved = {k: v for k, v in data.items() if k not in ("service", "data", "wikipedia", "settings")}
    with pytest.raises(mf.ManifestError):
        mf.validate(dict(saved, type="saved"))


KIT = {"format": 1, "type": "scored", "id": "org.example.kit-game", "version": "1.0.0", "title": "Kit game",
       "scoring": {"fields": [{"key": "guesses", "label": "Guesses", "order": "asc"},
                              {"key": "time", "label": "Time", "source": "time", "order": "asc", "total": "sum"},
                              {"key": "plays", "label": "Times played", "source": "plays"}],
                   "rank_by": ["guesses", "time"]}}


def test_kit_games_scores_are_read_and_their_saves_skipped():
    # A Scored Game made with EduGame Kit keeps each board as a list of its fields' values,
    # and its own save under keys starting with "_".
    m = mf.validate(KIT)
    found = channel.read_boards(m.channel_spec, scorm({"_v": 1, "_save": {"level": 3, "stars": [1, 2]}, "main": [7, 41.5, 3]}))
    assert found == {"main": {"guesses": 7, "time": 41.5, "plays": 3}}


def test_each_resource_of_a_kit_game_without_levels_has_its_own_board():
    source = FolderSource(os.path.join(EXAMPLES, "lit"))
    m = mf.validate(KIT)
    game = channel.group_resources([channel.ChannelResource(source, m, {"content_id": c * 32, "node_id": "n", "title": t})
                                    for c, t in (("1", "Easy hunt"), ("2", "Hard hunt"))])[0]
    store = MemoryStore()
    save(store, AMINA, "1" * 32, {"main": [7, 40, 1]})
    save(store, AMINA, "2" * 32, {"main": [9, 60, 2]})
    data = GameService(store).channel_scoreboards(game, AMINA)
    assert sorted(b["name"] for b in data["boards"]) == ["Easy hunt", "Hard hunt"]  # no total: none was asked for


def test_total_board_adds_up_every_board():
    game = channel.group_resources([resource("lit", "1" * 32, "Lesson 1"), resource("lit", "2" * 32, "Lesson 2")])[0]
    store = MemoryStore()
    save(store, AMINA, "1" * 32, {"en-01": {"done": 1, "acc": 96, "wpm": 14}})
    save(store, AMINA, "2" * 32, {"en-02": {"done": 1, "acc": 90, "wpm": 20}})
    save(store, BEN, "1" * 32, {"en-01": {"done": 1, "acc": 100, "wpm": 30}})
    data = GameService(store).channel_scoreboards(game, AMINA)
    total = data["boards"][0]
    assert total["total"] and total["name"] == "All lessons" and total["id"] == "_total"
    assert [f["key"] for f in total["spec"]["fields"]] == ["boards", "acc", "wpm"]
    assert [(r["name"], r["values"]) for r in total["rows"]] == [
        ("Amina Learner", {"boards": 2, "acc": 93, "wpm": 17}), ("Ben Learner", {"boards": 1, "acc": 100, "wpm": 30})]


# ----------------------------------------------------------- reading data


def test_suspend_data_is_read_from_nested_or_flat_scorm_keys():
    assert channel.suspend_data(scorm({"a": 1})) == {"a": 1}
    assert channel.suspend_data({"SCORM": {"cmi.suspend_data": '{"b": 2}'}}) == {"b": 2}
    for broken in (None, {}, {"SCORM": {}}, {"SCORM": {"cmi": {"suspend_data": "not json"}}},
                   {"SCORM": {"cmi": {"suspend_data": "[1, 2]"}}}, {"SCORM": {"cmi": {"suspend_data": "x" * 70000}}}):
        assert channel.suspend_data(broken) is None


def test_reading_lit_skips_unfinished_lessons():
    spec = example("lit").scoring
    found = channel.read_boards(spec, scorm({"en-01": {"done": 1, "acc": 96, "wpm": 14}, "en-02": {"done": 0, "acc": 0, "wpm": 0}}))
    assert found == {"en-01": {"acc": 96, "wpm": 14}}


def test_reading_singe_lists_by_position_and_ignores_junk():
    spec = example("singe").scoring
    found = channel.read_boards(spec, scorm({"us": [92, 140, 5], "us_flags": ["70", 99.5, 1], "bad": "x", "": [1, 2, 3]}))
    assert found == {"us": {"acc": 92, "time": 140, "plays": 5}, "us_flags": {"acc": 70, "time": 99.5, "plays": 1}}


def test_board_names_from_rules_and_names():
    spec = example("singe").scoring
    assert channel.board_name(spec, "us") == "United States: regions"
    assert channel.board_name(spec, "us_capitals") == "United States: capitals"
    assert channel.board_name(spec, "world_all_flags") == "World (all countries): flags"
    assert channel.board_name(spec, "mars_flags") == "mars: flags"
    assert channel.board_name(example("lit").scoring, "en-01") is None


# ---------------------------------------------------------- scoreboards


def singe_game():
    return channel.group_resources([resource("singe", "4" * 32, "Maps of Sierra Leone"), resource("singe", "5" * 32, "Maps of the world")])[0]


def test_reused_boards_merge_best_result_and_add_up_plays():
    game = singe_game()
    store = MemoryStore()
    save(store, AMINA, "4" * 32, {"sierra_leone": [92, 140, 5]})
    save(store, AMINA, "5" * 32, {"sierra_leone": [100, 300, 1]})
    save(store, BEN, "4" * 32, {"sierra_leone": [100, 200, 2]})
    data = GameService(store).channel_scoreboards(game, AMINA)
    board = boards(data)[0]
    assert board["name"] == "Sierra Leone: regions" and board["players"] == 2
    assert [r["name"] for r in board["rows"]] == ["Ben Learner", "Amina Learner"]  # same accuracy, Ben was faster
    assert board["rows"][1]["values"] == {"acc": 100, "time": 300, "plays": 6}
    assert board["mine"]["rank"] == 2
    assert {r["title"] for r in board["resources"]} == {"Maps of Sierra Leone", "Maps of the world"}


def test_speed_ranks_higher_first_and_time_ranks_lower_first():
    lit = channel.group_resources([resource("lit", "1" * 32, "Lesson 1")])[0]
    store = MemoryStore()
    save(store, AMINA, "1" * 32, {"en-01": {"done": 1, "acc": 95, "wpm": 12}})
    save(store, BEN, "1" * 32, {"en-01": {"done": 1, "acc": 95, "wpm": 20}})
    rows = boards(GameService(store).channel_scoreboards(lit, COACH))[0]["rows"]
    assert [r["name"] for r in rows] == ["Ben Learner", "Amina Learner"]  # same accuracy, more wpm wins
    store = MemoryStore()
    save(store, AMINA, "4" * 32, {"us": [95, 90, 1]})
    save(store, BEN, "4" * 32, {"us": [95, 60, 1]})
    rows = boards(GameService(store).channel_scoreboards(singe_game(), COACH))[0]["rows"]
    assert [r["name"] for r in rows] == ["Ben Learner", "Amina Learner"]  # same accuracy, less time wins


def test_ties_share_a_rank_and_missing_values_rank_last():
    game = singe_game()
    store = MemoryStore()
    save(store, AMINA, "4" * 32, {"us": [90, 100, 1]})
    save(store, BEN, "4" * 32, {"us": [90, 100, 1]})
    save(store, COACH, "4" * 32, {"us": [None, None, 4]})
    rows = boards(GameService(store).channel_scoreboards(game, COACH))[0]["rows"]
    assert [r["rank"] for r in rows] == [1, 1, 3]


def test_visibility_setting_applies_to_learners_but_not_coaches():
    game = singe_game()
    store = MemoryStore()
    service = GameService(store)
    save(store, AMINA, "4" * 32, {"us": [80, 100, 1]})
    save(store, BEN, "4" * 32, {"us": [90, 100, 1]})
    rows = boards(service.channel_scoreboards(game, AMINA))[0]["rows"]
    assert [r["name"] for r in rows] == ["Ben Learner", "Amina Learner"]  # full names by default
    service.save_settings(game, FACILITY, {"scoreboard": "initials"}, {}, COACH.id)
    assert [r["name"] for r in boards(service.channel_scoreboards(game, AMINA))[0]["rows"]] == ["B.L.", "Amina Learner"]
    service.save_settings(game, FACILITY, {"scoreboard": "hidden"}, {}, COACH.id)
    rows = boards(service.channel_scoreboards(game, AMINA))[0]["rows"]
    assert [(r["rank"], r["name"]) for r in rows] == [(2, "Amina Learner")]
    assert len(boards(service.channel_scoreboards(game, COACH))[0]["rows"]) == 2


def test_class_filter_and_other_facilities():
    game = singe_game()
    store = MemoryStore()
    save(store, AMINA, "4" * 32, {"us": [80, 100, 1]})
    save(store, BEN, "4" * 32, {"us": [90, 100, 1]})
    save(store, Player("e" * 32, "Elsewhere", "9" * 32), "4" * 32, {"us": [99, 1, 1]})
    data = GameService(store).channel_scoreboards(game, COACH, user_ids={AMINA.id})
    assert [r["name"] for r in boards(data)[0]["rows"]] == ["Amina Learner"]


def test_lit_boards_are_named_after_their_resource_and_summary_counts_mine():
    game = channel.group_resources([resource("lit", "1" * 32, "Lesson 1: Left-hand home keys"), resource("lit", "2" * 32, "Lesson 10: Numbers")])[0]
    store = MemoryStore()
    service = GameService(store)
    save(store, AMINA, "1" * 32, {"en-01": {"done": 1, "acc": 96, "wpm": 14}})
    save(store, BEN, "2" * 32, {"en-10": {"done": 1, "acc": 90, "wpm": 20}, "fr-10": {"done": 1, "acc": 80, "wpm": 10}})
    names = [b["name"] for b in boards(service.channel_scoreboards(game, AMINA))]
    assert names == ["Lesson 1: Left-hand home keys", "Lesson 10: Numbers (en-10)", "Lesson 10: Numbers (fr-10)"]
    assert service.summary(game, AMINA) == {"boards": 1, "resources": 2}


def test_resources_group_into_one_game_per_id_using_the_newest_manifest():
    old = json.load(open(os.path.join(EXAMPLES, "singe", "kolibri-game.json")))
    old["version"] = "0.1.0"
    old["title"] = "Old title"
    old["scoring"]["boards"]["names"] = {"mars": "Mars"}
    old_m = mf.validate(old)
    new = resource("singe", "5" * 32, "World")
    older = channel.ChannelResource(new.source, old_m, {"content_id": "6" * 32, "node_id": "x", "title": "Mars maps"})
    copy = resource("singe", "5" * 32, "World (copy in another channel)")
    games = channel.group_resources([older, new, copy, resource("lit", "1" * 32, "Lesson 1")])
    singe = [g for g in games if g.manifest.id == "org.togetherings.singe"][0]
    assert singe.key == "c-org.togetherings.singe" and singe.title == "Studies In Geography"
    assert sorted(singe.content_ids) == ["5" * 32, "6" * 32]
    assert channel.board_name(singe.spec, "mars_flags") == "Mars: flags"
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
