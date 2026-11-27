"""Smoke Signals: the turn order, hand-ins, and whole games through the service with several players."""
import pytest

from kolibri_games import smokesignals as ss
from kolibri_games.manifest import ManifestError, validate
from kolibri_games.service import GameService, MemoryStore, PlatformError, Player
from tests.helpers import Clock, folder_game

FAC = "f" * 32


# ------------------------------------------------------------------ turn order


@pytest.mark.parametrize("n", range(3, 13))
def test_every_chain_reaches_everyone_once_and_ends_on_a_guess(n):
    steps = ss.total_steps(n, 1)
    assert ss.kind(steps - 1) == ss.GUESS
    for step in range(steps):
        holders = [ss.holder(c, step, n) for c in range(n)]
        assert sorted(holders) == list(range(n)), "two chains with one player"
        for seat in range(n):
            assert ss.holder(ss.chain_of(seat, step, n), step, n) == seat
    for c in range(n):
        people = [ss.holder(c, s, n) for s in range(steps)]
        if n % 2:
            assert len(set(people)) == n and people[0] == c  # once each, owner only at the start
        else:
            assert people[:2] == [c, c] and len(set(people[1:])) == n  # the owner draws their own prompt first


def test_small_groups_go_round_again_for_the_rounds_asked():
    assert ss.total_steps(3, 3) == 7 and ss.rounds_for(3, 3) == 3
    assert ss.total_steps(4, 3) == 7
    assert ss.total_steps(9, 3) == 9  # 4 rounds: everyone gets a turn
    assert ss.total_steps(5, 99) == 1 + 2 * ss.MAX_ROUNDS


def test_hand_ins_are_checked():
    assert ss.clean_text("  a  cat\tin a hat ") == "a cat in a hat"
    for bad in ("", "   ", None, 5, "x" * 61):
        with pytest.raises(ss.SmokeError):
            ss.clean_text(bad)
    good = {"strokes": [[0, 1, 10, 10, 20, 20], [8, 2, 0, 0]]}
    assert ss.clean_drawing(good) == good
    assert ss.clean_drawing({"strokes": []}) == {"strokes": []}
    for bad in (None, {"strokes": [[0, 1, 10]]}, {"strokes": [[9, 0, 1, 1]]}, {"strokes": [[0, 3, 1, 1]]},
                {"strokes": [[0, 0, 801, 1]]}, {"strokes": [[0, 0, 1.5, 1]]}, {"strokes": [[0, 0, True, 1]]},
                {"strokes": [[0, 0] + [1, 1] * (ss.MAX_POINTS + 1)]}):
        with pytest.raises(ss.SmokeError):
            ss.clean_drawing(bad)


def test_the_next_drawer_carries_on_from_the_last_real_words():
    entries = [
        {"chain": 0, "step": 0, "content": {"text": "a cat"}},
        {"chain": 0, "step": 1, "content": {"strokes": [[0, 0, 1, 1]]}},
        {"chain": 0, "step": 2, "content": {"text": ""}},  # nobody guessed
        {"chain": 0, "step": 3, "content": {"strokes": []}},  # nobody drew
    ]
    assert ss.given(entries, 0, 3) == {"text": "a cat"}
    assert ss.given(entries, 0, 4) == {"drawing": {"strokes": [[0, 0, 1, 1]]}}
    assert ss.given(entries[:1] + [{"chain": 0, "step": 1, "content": {"strokes": []}}], 0, 2) == {"drawing": None}


def test_the_manifest_needs_words_and_no_scores():
    game = folder_game("smoke-signals")
    assert game.playable, game.problems
    raw = dict(game.manifest.raw)
    with pytest.raises(ManifestError) as e:
        validate(dict(raw, words={}))
    assert "word list" in str(e.value)
    with pytest.raises(ManifestError) as e:
        validate(dict(raw, scoring={"label": "Points", "order": "desc"}))
    assert "no scores" in str(e.value)


# ------------------------------------------------------------------ whole games


@pytest.fixture
def table():
    clock = Clock()
    service = GameService(MemoryStore(), now=clock, background=lambda fn: fn())
    game = folder_game("smoke-signals")
    players = [Player(c * 32, name, FAC) for c, name in zip("ab123", ["Amina", "Ben", "Cara", "Dev", "Esi"])]
    coach = Player("c" * 32, "Ms Coach", FAC, is_coach=True, coach_class_ids=None)
    return service, clock, game, players, coach


class Seat(object):
    """One player at the table: their attempt, and the moves they make."""

    def __init__(self, service, game, player):
        self.service, self.game, self.player = service, game, player
        started = service.start(game, player, resume=False)
        self.attempt = started["attempt"]["id"]
        self.public = started["public"]

    def move(self, kind, data=None):
        return self.service.move(self.game, self.player, self.attempt, kind, data or {})

    def hand_in(self):
        view = self.move("poll")
        task = view["task"]
        if task["kind"] == ss.DRAW:
            return self.move("submit", {"step": task["step"], "drawing": {"strokes": [[1, 1, 10, 10, 200, 150]]}})
        text = "%s %d" % (self.player.name, task["step"])
        return self.move("submit", {"step": task["step"], "text": text})


def sit(service, game, players):
    seats = [Seat(service, game, p) for p in players]
    room = seats[0].move("create", {"speed": "quick", "rounds": 1})["room"]
    for s in seats[1:]:
        s.move("join", {"code": room["code"].lower()})  # codes don't mind case
    return seats, room["code"]


def test_a_whole_game_with_four_players(table):
    service, clock, game, players, _ = table
    seats, code = sit(service, game, players[:4])
    view = seats[1].move("poll")
    assert [p["name"] for p in view["room"]["players"]] == ["Amina", "Ben", "Cara", "Dev"]
    with pytest.raises(PlatformError) as e:
        seats[1].move("begin")
    assert e.value.code == "forbidden"
    view = seats[0].move("begin")
    assert view["room"]["status"] == "playing" and view["room"]["steps"] == 5  # 4 players: 2 rounds
    assert view["task"]["kind"] == ss.PROMPT and len(view["task"]["suggestions"]) == 3
    assert 0 < view["task"]["seconds_left"] <= 30

    for step in range(5):
        for s in seats:
            reply = s.hand_in()
        assert reply["room"]["step"] == step + 1 or reply["room"]["status"] == "done"
    assert seats[2].move("poll")["room"]["status"] == "done"

    chains = seats[1].move("chains")["chains"]
    assert [c["owner"] for c in chains] == ["Amina", "Ben", "Cara", "Dev"]
    assert chains[1]["mine"] and chains[1]["prompt"] == "Ben 0"
    chain = seats[1].move("chain", {"index": 1})
    # Even numbers: Ben draws his own prompt first, then it moves on round the table.
    assert [(e["kind"], e["by"]) for e in chain["entries"]] == [
        ("prompt", "Ben"), ("draw", "Ben"), ("guess", "Cara"), ("draw", "Dev"), ("guess", "Amina")]
    assert chain["entries"][2]["text"] == "Cara 2" and chain["entries"][1]["strokes"]

    # Finishing leaves the room and keeps the player's chain for coaches.
    done = service.finish(game, players[1], seats[1].attempt, {})
    assert done["attempt"]["detail"]["chain"] == ["Ben 0", "(drawing)", "Cara 2", "(drawing)", "Amina 4"]
    again = service.start(game, players[1], resume=False)["public"]
    assert again["room"] is None
    # Polls aren't kept in the move list; hand-ins are, without the drawings.
    events = service.store.attempt_get(seats[1].attempt).events
    assert [e["type"] for e in events] == ["join", "submit", "submit", "submit", "submit", "submit"]
    assert "strokes" not in str(events)


def test_three_players_and_the_rounds_asked_for(table):
    service, clock, game, players, _ = table
    seats = [Seat(service, game, p) for p in players[:3]]
    code = seats[0].move("create", {"rounds": 3})["room"]["code"]
    for s in seats[1:]:
        s.move("join", {"code": code})
    assert seats[0].move("begin")["room"]["steps"] == 7
    for _ in range(7):
        for s in seats:
            s.hand_in()
    chain = seats[0].move("chain", {"index": 0})["entries"]
    assert [e["by"] for e in chain] == ["Amina", "Ben", "Cara", "Amina", "Ben", "Cara", "Amina"]


def test_the_server_fills_in_when_time_runs_out(table):
    service, clock, game, players, _ = table
    seats, code = sit(service, game, players[:3])
    seats[0].move("begin")
    seats[0].hand_in()
    seats[1].hand_in()
    clock.advance(30)
    assert seats[0].move("poll")["room"]["step"] == 0  # a few seconds' grace for the last hand-in
    clock.advance(ss.GRACE_SECONDS + 1)
    view = seats[0].move("poll")
    assert view["room"]["step"] == 1
    # Cara missed her prompt: the server picked an idea from the word list.
    words = service.smoke.words(game, "en")
    entries = service.store.room_entries(service.smoke.my_room(game, players[2], None).id, chain=2)
    assert entries[0].auto and entries[0].content["text"] in words
    # Her late hand-in is refused.
    with pytest.raises(PlatformError) as e:
        seats[2].move("submit", {"step": 0, "text": "too late"})
    assert e.value.code == "too_late"
    # Whoever draws Cara's chain gets the server's idea.
    drawer = [s for s in seats if s.move("poll")["task"]["key"].endswith("-2")][0]
    assert drawer.move("poll")["task"]["text"] == entries[0].content["text"]


def test_players_who_leave_are_skipped_and_the_host_moves_on(table):
    service, clock, game, players, _ = table
    seats, code = sit(service, game, players[:4])
    seats[0].move("begin")
    service.finish(game, players[0], seats[0].attempt, {})  # the host leaves
    view = seats[1].move("poll")
    assert view["room"]["host"] and view["room"]["players"][0]["left"]
    for s in seats[1:]:
        s.hand_in()
    assert seats[1].move("poll")["room"]["step"] == 1  # Amina's prompt was filled in for her


def test_no_timer_the_host_stops_waiting(table):
    service, clock, game, players, _ = table
    seats = [Seat(service, game, p) for p in players[:3]]
    code = seats[0].move("create", {"speed": "none"})["room"]["code"]
    for s in seats[1:]:
        s.move("join", {"code": code})
    assert seats[0].move("begin")["task"]["seconds_left"] is None
    seats[0].hand_in()
    clock.advance(3600)
    view = seats[0].move("poll")
    assert view["room"]["step"] == 0 and view["task"]["waiting"] == ["Ben", "Cara"]
    assert [p["away"] for p in view["room"]["players"]] == [False, True, True]
    with pytest.raises(PlatformError):
        seats[1].move("skip")
    assert seats[0].move("skip")["room"]["step"] == 1


def test_waiting_room_rules(table):
    service, clock, game, players, coach = table
    seats = [Seat(service, game, p) for p in players[:2]]
    lobby = seats[1].public
    assert lobby["room"] is None and lobby["rooms"] == [] and lobby["can_host"]
    code = seats[0].move("create")["room"]["code"]
    assert seats[1].move("lobby")["rooms"] == [{"code": code, "host": "Amina", "players": 1}]
    with pytest.raises(PlatformError) as e:
        seats[1].move("join", {"code": "ZZZZ"})
    assert e.value.code == "no_room"
    seats[1].move("join", {"code": code})
    with pytest.raises(PlatformError) as e:
        seats[0].move("begin")
    assert e.value.code == "too_few"
    view = seats[0].move("remove", {"seat": 1})
    assert len(view["room"]["players"]) == 1
    assert seats[1].move("poll")["room"] is None
    # Coaches can keep starting games to themselves.
    service.save_settings(game, FAC, {}, {"hosts": "coaches"}, coach.id)
    assert seats[1].move("lobby")["can_host"] is False
    with pytest.raises(PlatformError) as e:
        seats[1].move("create")
    assert e.value.code == "forbidden"
    # ...and choose word-list prompts only.
    service.save_settings(game, FAC, {}, {"prompts": "list"}, coach.id)
    host = Seat(service, game, coach)
    code = host.move("create")["room"]["code"]
    joined = [Seat(service, game, p) for p in players[2:4]]
    for s in joined:
        s.move("join", {"code": code})
    task = host.move("begin")["task"]
    assert task["typing"] is False
    with pytest.raises(PlatformError):
        host.move("submit", {"step": 0, "text": "something rude"})
    host.move("submit", {"step": 0, "text": task["suggestions"][0]})


def test_a_room_isnt_changed_by_two_saves_at_once(table):
    service, clock, game, players, _ = table
    store = service.store
    seats, code = sit(service, game, players[:3])
    a = store.room_get(store.rooms(game.key, FAC, None, ["lobby"])[0].id)
    b = store.room_get(a.id)
    a.step = 5
    assert store.room_save(a)
    b.step = 6
    assert not store.room_save(b)
    assert store.room_get(a.id).step == 5


def test_old_rooms_close_and_are_deleted(table):
    service, clock, game, players, _ = table
    seats, code = sit(service, game, players[:3])
    clock.advance(3 * 3600)
    assert seats[0].move("poll")["room"] is None  # an idle waiting room closes
    clock.advance(8 * 24 * 3600)
    seats[0].move("create")
    assert len(service.store.rooms(game.key, FAC, None, ["lobby", "closed"])) == 1
