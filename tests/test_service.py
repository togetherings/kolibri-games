"""Game rules end to end, using the in-memory store and the sample games."""
import os

import pytest

from kolibri_games import registry
from kolibri_games.service import GameService, MemoryStore, PlatformError, Player
from tests.helpers import GAMES, Clock, folder_game

FAC = "f" * 32
CLASS_A, CLASS_B = "e" * 32, "9" * 32


@pytest.fixture
def setup():
    clock = Clock()
    service = GameService(MemoryStore(), now=clock, background=lambda fn: fn())
    amina = Player("a" * 32, "Amina Learner", FAC, class_ids={CLASS_A})
    ben = Player("b" * 32, "Ben Learner", FAC, class_ids={CLASS_A})
    cara = Player("1" * 32, "Cara Learner", FAC, class_ids={CLASS_B})
    coach = Player("c" * 32, "Ms Coach", FAC, is_coach=True, coach_class_ids={CLASS_A})
    return service, clock, amina, ben, cara, coach


def play(service, game, player, clock, score, challenge=None, seconds=30, moves=2):
    started = service.start(game, player, challenge, resume=False)
    aid = started["attempt"]["id"]
    for i in range(moves):
        assert service.move(game, player, aid, "guess", {"value": i}) == {}
    clock.advance(seconds)
    return aid, service.finish(game, player, aid, {"score": score, "detail": {"note": "hi"}})


def test_sample_games_are_valid_and_playable():
    for name in ("number-hunt", "memory-match"):
        game = folder_game(name)
        assert game.playable, game.problems
    # Wiki BLAZE needs a Wikipedia file first.
    blaze = folder_game("wiki-blaze")
    assert not blaze.playable and "'wikipedia' data source" in " ".join(blaze.problems)


def test_games_report_their_own_score_within_bounds(setup):
    service, clock, amina, *_ = setup
    game = folder_game("number-hunt")
    aid, result = play(service, game, amina, clock, 7)
    assert result["attempt"]["score"] == 7 and result["attempt"]["seconds"] == 30
    assert result["standing"]["rank"] == 1
    events = service.store.attempt_get(aid).events
    assert [e["type"] for e in events] == ["guess", "guess"]
    for bad in (0, 5000, "7", True):
        started = service.start(game, amina, resume=False)
        with pytest.raises(PlatformError):
            service.finish(game, amina, started["attempt"]["id"], {"score": bad})


def test_moves_are_limited_and_belong_to_one_player(setup):
    service, clock, amina, ben, *_ = setup
    game = folder_game("memory-match")
    aid = service.start(game, amina)["attempt"]["id"]
    with pytest.raises(PlatformError):
        service.move(game, ben, aid, "flip", {})
    with pytest.raises(PlatformError):
        service.move(game, amina, aid, "flip", {"x": "y" * 5000})
    with pytest.raises(PlatformError):
        service.move(game, amina, aid, "", {})


def test_first_attempt_counts_then_practice(setup):
    service, clock, amina, *_ = setup
    game = folder_game("number-hunt")  # counts the first attempt
    play(service, game, amina, clock, 9)
    _, result = play(service, game, amina, clock, 3)
    assert result["attempt"]["practice"] is True
    summary = service.summary(game, amina)
    assert summary["counted"]["score"] == 9 and summary["attempts"] == 2


def test_resume_and_abandon(setup):
    service, clock, amina, *_ = setup
    game = folder_game("memory-match")
    first = service.start(game, amina)
    again = service.start(game, amina)
    assert again["resumed"] and again["attempt"]["id"] == first["attempt"]["id"]
    clock.advance(13 * 3600)  # too old to resume
    fresh = service.start(game, amina)
    assert not fresh["resumed"]
    assert service.store.attempt_get(first["attempt"]["id"]).status == "abandoned"
    service.abandon(game, amina, fresh["attempt"]["id"])
    with pytest.raises(PlatformError):
        service.finish(game, amina, fresh["attempt"]["id"], {"score": 3})


def test_coach_reset_gives_a_fresh_counted_attempt(setup):
    service, clock, amina, *_ = setup
    game = folder_game("number-hunt")
    play(service, game, amina, clock, 9)
    service.reset(game, FAC, amina.id)
    _, result = play(service, game, amina, clock, 4)
    assert result["attempt"]["practice"] is False
    assert service.summary(game, amina)["counted"]["score"] == 4


def test_time_limit(setup):
    service, clock, amina, *_ = setup
    game = folder_game("memory-match")
    service.save_settings(game, FAC, {"time_limit": 1}, {}, "c" * 32)
    aid = service.start(game, amina)["attempt"]["id"]
    clock.advance(70)
    with pytest.raises(PlatformError) as e:
        service.finish(game, amina, aid, {"score": 9})
    assert e.value.code == "time_up"


def test_settings_are_checked(setup):
    service, clock, amina, *_ = setup
    game = folder_game("number-hunt")
    with pytest.raises(PlatformError) as e:
        service.save_settings(game, FAC, {"time_limit": -1}, {"max": 7}, "c" * 32)
    assert set(e.value.fields) == {"time_limit", "max"}
    service.save_settings(game, FAC, {}, {"max": 20}, "c" * 32)
    assert service.context(game, amina).settings["max"] == 20


def test_scoreboard_visibility_for_learners_and_coaches(setup):
    service, clock, amina, ben, cara, coach = setup
    game = folder_game("memory-match")
    play(service, game, amina, clock, 9)
    play(service, game, ben, clock, 12)
    service.save_settings(game, FAC, {"scoreboard": "hidden"}, {}, coach.id)
    assert [r["name"] for r in service.scoreboard(game, ben)["rows"]] == ["Ben Learner"]
    assert len(service.scoreboard(game, coach)["rows"]) == 2
    service.save_settings(game, FAC, {"scoreboard": "initials"}, {}, coach.id)
    assert [r["name"] for r in service.scoreboard(game, ben)["rows"]] == ["A.L.", "Ben Learner"]


def test_state_size_limit(setup):
    service, clock, amina, *_ = setup
    game = folder_game("memory-match")
    service.set_state(game, amina, {"level": 3})
    assert service.get_state(game, amina) == {"level": 3}
    with pytest.raises(PlatformError):
        service.set_state(game, amina, {"x": "y" * 70000})


# ----------------------------------------------------------------- challenges


def make_challenge(service, game, coach, clock, **extra):
    data = {"title": "Friday race", "class_id": CLASS_A, "counts": "best",
            "opens_at": clock().isoformat(), "closes_at": (clock.t.replace(hour=17)).isoformat()}
    data.update(extra)
    return service.save_challenge(game, coach, data, {CLASS_A: "Class A"})


def test_challenge_is_checked_when_saved(setup):
    service, clock, amina, ben, cara, coach = setup
    game = folder_game("memory-match")
    with pytest.raises(PlatformError) as e:
        service.save_challenge(game, coach, {"title": "", "class_id": CLASS_B, "opens_at": "2026-01-02T10:00:00Z",
                                             "closes_at": "2026-01-01T10:00:00Z", "time_limit": 999}, {CLASS_A: "Class A"})
    assert set(e.value.fields) >= {"title", "class_id", "closes_at", "time_limit"}
    with pytest.raises(PlatformError):  # a learner can't make challenges
        service.save_challenge(game, amina, {"title": "x", "class_id": CLASS_A}, {CLASS_A: "Class A"})


def test_challenges_have_their_own_rules_and_scoreboards(setup):
    service, clock, amina, ben, cara, coach = setup
    game = folder_game("memory-match")
    c = make_challenge(service, game, coach, clock, settings={"pairs": 6})
    assert c["state"] == "open" and c["settings"]["pairs"] == 6
    # Amina's class sees it; Cara's class doesn't.
    assert [x["title"] for x in service.challenges_for(game, amina)] == ["Friday race"]
    assert service.challenges_for(game, cara) == []
    with pytest.raises(PlatformError):
        service.start(game, cara, c["id"])
    assert service.context(game, amina, c["id"]).settings["pairs"] == 6
    play(service, game, amina, clock, 20, challenge=c["id"])
    play(service, game, amina, clock, 10, challenge=c["id"])  # best counts in this challenge
    play(service, game, ben, clock, 15)  # free play
    board = service.scoreboard(game, ben, c["id"])
    assert [(r["name"], r["score"]) for r in board["rows"]] == [("Amina Learner", 10)]
    assert [r["name"] for r in service.scoreboard(game, ben)["rows"]] == ["Ben Learner"]
    mine = service.challenges_for(game, amina)[0]["mine"]
    assert mine["attempts"] == 2 and mine["counted"]["score"] == 10


def test_challenges_open_and_close(setup):
    service, clock, amina, ben, cara, coach = setup
    game = folder_game("memory-match")
    later = clock.t.replace(hour=12).isoformat()
    c = make_challenge(service, game, coach, clock, opens_at=later)
    assert c["state"] == "upcoming"
    assert service.challenges_for(game, amina) == []  # learners don't see it yet
    with pytest.raises(PlatformError) as e:
        service.start(game, amina, c["id"])
    assert e.value.code == "upcoming"
    clock.advance(3 * 3600 + 60)  # 12:01
    aid = service.start(game, amina, c["id"])["attempt"]["id"]
    clock.advance(5 * 3600)  # 17:01, closed
    with pytest.raises(PlatformError) as e:
        service.finish(game, amina, aid, {"score": 9})
    assert e.value.code == "closed"
    assert service.challenges_for(game, amina)[0]["state"] == "closed"
    clock.advance(15 * 24 * 3600)  # old challenges drop off learners' cards
    assert service.challenges_for(game, amina) == []
    assert len(service.challenges_for(game, coach, include_old=True)) == 1


def test_coach_can_edit_and_delete_only_their_classes_challenges(setup):
    service, clock, amina, ben, cara, coach = setup
    game = folder_game("memory-match")
    c = make_challenge(service, game, coach, clock)
    changed = service.save_challenge(game, coach, {"title": "Renamed", "class_id": CLASS_A, "counts": "first",
                                                   "opens_at": c["opens_at"], "closes_at": c["closes_at"]},
                                     {CLASS_A: "Class A"}, c["id"])
    assert changed["title"] == "Renamed" and changed["counts"] == "first"
    other_coach = Player("2" * 32, "Mr Other", FAC, is_coach=True, coach_class_ids={CLASS_B})
    with pytest.raises(PlatformError):
        service.delete_challenge(game, other_coach, c["id"])
    service.delete_challenge(game, coach, c["id"])
    assert service.challenges_for(game, coach, include_old=True) == []


def test_registry_finds_games_and_reports_problems(tmp_path):
    os.environ["KOLIBRI_HOME"] = str(tmp_path)
    os.environ["KOLIBRI_GAMES_PATH"] = GAMES
    try:
        keys = [g.key for g in registry.discover(refresh=True)]
        assert "f-org.togetherings.number-hunt" in keys
        assert registry.get("f-org.togetherings.memory-match").playable
        broken = tmp_path / "kolibri_games" / "games" / "future"
        broken.mkdir(parents=True)
        (broken / "kolibri-game.json").write_text(
            '{"format": 1, "id": "org.example.future", "version": "1.0", "title": "Future", '
            '"requires_platform": ">=9"}'
        )
        entry = registry.get("f-org.example.future", refresh=True)
        assert not entry.playable and entry.origin == "installed"
        text = " ".join(entry.problems)
        assert "Kolibri Games >=9" in text and "start page" in text
        (tmp_path / "kolibri_games" / "games" / "junk.zip").write_bytes(b"not a zip")
        junk = [g for g in registry.discover(refresh=True) if g.source.location.endswith("junk.zip")]
        assert junk and junk[0].key.startswith("x-") and junk[0].problems
        assert registry.get("../etc") is None
    finally:
        del os.environ["KOLIBRI_GAMES_PATH"]
        del os.environ["KOLIBRI_HOME"]
        registry.discover(refresh=True)
