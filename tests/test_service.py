"""Game rules end to end, using the in-memory store and the sample games."""
import os

import pytest

from kolibri_games import registry
from kolibri_games.service import GameService, MemoryStore, PlatformError, Player
from tests.helpers import GAMES, Clock, folder_game

FAC = "f" * 32


@pytest.fixture
def setup():
    clock = Clock()
    service = GameService(MemoryStore(), now=clock)
    amina = Player("a" * 32, "Amina Learner", FAC)
    ben = Player("b" * 32, "Ben Learner", FAC)
    coach = Player("c" * 32, "Ms Coach", FAC, is_coach=True)
    return service, clock, amina, ben, coach


def secret_of(service, attempt_id):
    return service.store.attempt_get(attempt_id).vstate["secret"]


def play_number_hunt(service, game, player, clock, wrong_guesses=0):
    started = service.start(game, player)
    aid = started["attempt"]["id"]
    secret = secret_of(service, aid)
    for i in range(wrong_guesses):
        wrong = secret + 1 if secret < started["public"]["high"] else secret - 1
        reply = service.event(game, player, aid, "guess", {"value": wrong})
        assert reply["hint"] in ("higher", "lower")
    clock.advance(30)
    assert service.event(game, player, aid, "guess", {"value": secret})["hint"] == "correct"
    return aid, service.finish(game, player, aid, {"score": 1})  # claimed score is ignored


def test_sample_games_are_playable():
    for name in os.listdir(GAMES):
        assert folder_game(name).playable, folder_game(name).problems


def test_number_hunt_is_scored_by_the_server(setup):
    service, clock, amina, ben, coach = setup
    game = folder_game("number-hunt")
    started = service.start(game, amina)
    assert started["public"] == {"low": 1, "high": 100, "guesses": []}
    assert "secret" not in str(started)
    aid, result = play_number_hunt(service, game, amina, clock, wrong_guesses=3)
    assert result["attempt"]["score"] == 4
    assert result["attempt"]["verified"] is True
    assert result["standing"]["rank"] == 1
    with pytest.raises(PlatformError):
        service.event(game, amina, aid, "guess", {"value": 5})  # attempt is over


def test_rejects_bad_moves_and_other_players(setup):
    service, clock, amina, ben, coach = setup
    game = folder_game("number-hunt")
    aid = service.start(game, amina)["attempt"]["id"]
    for bad in ({"value": 0}, {"value": 101}, {"value": "7"}, {"value": True}):
        with pytest.raises(PlatformError):
            service.event(game, amina, aid, "guess", bad)
    with pytest.raises(PlatformError) as info:
        service.event(game, ben, aid, "guess", {"value": 5})
    assert info.value.status == 404
    with pytest.raises(PlatformError):
        service.finish(game, amina, aid, {"score": 1})  # number not found yet


def test_first_attempt_counts_then_practice(setup):
    service, clock, amina, ben, coach = setup
    game = folder_game("number-hunt")
    play_number_hunt(service, game, amina, clock, wrong_guesses=5)
    _, second = play_number_hunt(service, game, amina, clock, wrong_guesses=0)
    assert second["attempt"]["practice"] is True
    assert second["standing"]["score"] == 6  # still the first attempt
    summary = service.summary(game, amina)
    assert summary["counted"]["score"] == 6 and summary["attempts"] == 2


def test_resume_and_abandon(setup):
    service, clock, amina, ben, coach = setup
    game = folder_game("number-hunt")
    first = service.start(game, amina)
    aid = first["attempt"]["id"]
    service.event(game, amina, aid, "guess", {"value": 50})
    again = service.start(game, amina)
    assert again["resumed"] and again["attempt"]["id"] == aid
    assert again["public"]["guesses"][0]["value"] == 50
    fresh = service.start(game, amina, resume=False)
    assert fresh["attempt"]["id"] != aid
    assert service.store.attempt_get(aid).status == "abandoned"
    # The abandoned first attempt counts as unfinished: no scoreboard entry.
    s = secret_of(service, fresh["attempt"]["id"])
    service.event(game, amina, fresh["attempt"]["id"], "guess", {"value": s})
    result = service.finish(game, amina, fresh["attempt"]["id"], {})
    assert result["attempt"]["practice"] and result["standing"] is None


def test_coach_reset_gives_a_fresh_counted_attempt(setup):
    service, clock, amina, ben, coach = setup
    game = folder_game("number-hunt")
    service.start(game, amina)  # started then left
    service.reset(game, FAC, amina.id)
    _, result = play_number_hunt(service, game, amina, clock, wrong_guesses=1)
    assert result["attempt"]["practice"] is False
    assert result["standing"]["score"] == 2
    rows = service.coach_results(game, FAC)["rows"]
    assert rows[0]["attempts"] == 1 and rows[0]["reset_attempts"] == 1


def test_time_limit(setup):
    service, clock, amina, ben, coach = setup
    game = folder_game("number-hunt")
    service.save_settings(game, FAC, {"time_limit": 1}, {}, coach.id)
    started = service.start(game, amina)
    assert started["time_limit"] == 60
    clock.advance(120)
    with pytest.raises(PlatformError) as info:
        service.event(game, amina, started["attempt"]["id"], "guess", {"value": 3})
    assert info.value.code == "time_up"
    assert service.store.attempt_get(started["attempt"]["id"]).status == "expired"


def test_settings_change_the_game(setup):
    service, clock, amina, ben, coach = setup
    game = folder_game("number-hunt")
    service.save_settings(game, FAC, {}, {"max": 20}, coach.id)
    assert service.start(game, amina)["public"]["high"] == 20
    with pytest.raises(PlatformError) as info:
        service.save_settings(game, FAC, {"time_limit": -5}, {"max": 7}, coach.id)
    assert set(info.value.fields) == {"time_limit", "max"}


def test_client_scored_game_is_unverified_and_bounded(setup):
    service, clock, amina, ben, coach = setup
    game = folder_game("memory-match")
    aid = service.start(game, amina)["attempt"]["id"]
    service.event(game, amina, aid, "flip", {"cards": [0, 5]})
    with pytest.raises(PlatformError):
        service.finish(game, amina, aid, {"score": 5000})  # above scoring.max
    result = service.finish(game, amina, aid, {"score": 12, "detail": {"pairs": 8}})
    assert result["attempt"]["verified"] is False and result["attempt"]["score"] == 12
    events = service.coach_results(game, FAC)["rows"][0]["history"][0]["events"]
    assert events[0]["type"] == "flip"


def test_scoreboard_visibility_for_learners_and_coaches(setup):
    service, clock, amina, ben, coach = setup
    game = folder_game("number-hunt")
    play_number_hunt(service, game, amina, clock, wrong_guesses=2)
    play_number_hunt(service, game, ben, clock, wrong_guesses=4)
    service.save_settings(game, FAC, {"scoreboard": "hidden"}, {}, coach.id)
    assert [r["name"] for r in service.scoreboard(game, ben)["rows"]] == ["Ben Learner"]
    assert len(service.scoreboard(game, coach)["rows"]) == 2


def test_state_size_limit(setup):
    service, clock, amina, ben, coach = setup
    game = folder_game("memory-match")
    service.set_state(game, amina, {"level": 3})
    assert service.get_state(game, amina) == {"level": 3}
    with pytest.raises(PlatformError):
        service.set_state(game, amina, {"x": "y" * 70000})


def test_registry_finds_local_games_and_reports_problems(tmp_path):
    os.environ["KOLIBRI_HOME"] = str(tmp_path)
    os.environ["KOLIBRI_GAMES_PATH"] = GAMES
    try:
        games = registry.discover(refresh=True)
        keys = [g.key for g in games]
        assert "l-org.togetherings.number-hunt" in keys
        assert registry.get("l-org.togetherings.memory-match").playable
        broken = tmp_path / "kolibri_games" / "games" / "broken"
        broken.mkdir(parents=True)
        (broken / "kolibri-game.json").write_text(
            '{"format": 1, "id": "org.example.future", "version": "1.0", "title": "Future", '
            '"requires_platform": ">=9", "validator": "nope"}'
        )
        entry = registry.get("l-org.example.future", refresh=True)
        assert not entry.playable
        text = " ".join(entry.problems)
        assert "Kolibri Games >=9" in text and "'nope' rule checker" in text and "start page" in text
        assert registry.get("../etc") is None
    finally:
        del os.environ["KOLIBRI_GAMES_PATH"]
        del os.environ["KOLIBRI_HOME"]
        registry.discover(refresh=True)
