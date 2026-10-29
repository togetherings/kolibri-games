"""Reading Wikipedia and the Wiki BLAZE rules, using the tiny wiki in examples/ (no libzim needed)."""
import os

import pytest

from kolibri_games import registry, views_common, wiki, wikirace
from kolibri_games.service import GameService, MemoryStore, PlatformError, Player
from tests.helpers import ROOT, Clock, folder_game

TINY = os.path.join(ROOT, "examples", "tiny-wiki")
FAC = "f" * 32
CLASS_A = "e" * 32


@pytest.fixture
def blaze():
    """Wiki BLAZE with the tiny wiki as its Wikipedia file."""
    os.environ["KOLIBRI_GAMES_DATA_WIKIPEDIA"] = TINY
    try:
        game = folder_game("wiki-blaze")
        assert game.playable, game.problems
        clock = Clock()
        service = GameService(MemoryStore(), now=clock, background=lambda fn: fn())
        amina = Player("a" * 32, "Amina Learner", FAC, class_ids={CLASS_A})
        ben = Player("b" * 32, "Ben Learner", FAC, class_ids={CLASS_A})
        coach = Player("c" * 32, "Ms Coach", FAC, is_coach=True, coach_class_ids={CLASS_A})
        # The game's own list is Wikipedia for Schools, which the tiny wiki doesn't have: use every article.
        service.save_settings(game, FAC, {}, {"list": "all"}, coach.id)
        yield game, service, clock, amina, ben, coach
    finally:
        del os.environ["KOLIBRI_GAMES_DATA_WIKIPEDIA"]


def tiny():
    return wiki.open_wiki(TINY)


# --------------------------------------------------------------- reading


def test_articles_are_cleaned_and_links_checked():
    a = wiki.clean_article(tiny(), "Mammal", None)
    assert a["title"] == "Mammal"
    assert a["links"] == ["Animal", "Milk", "Whale", "Cat"]  # "Cats" is a redirect to "Cat"
    assert "<script" not in a["html"] and "edit" not in a["html"] and "[1]" not in a["html"]
    assert '<a data-to="Animal">' in a["html"] and "href" not in a["html"]
    egg = wiki.clean_article(tiny(), "Egg", None)
    assert egg["links"] == ["Bird"] and "Unicorn" in egg["html"]  # missing article: plain text
    cat = wiki.clean_article(tiny(), "Cat", None)
    assert 'src="__wiki__/I/cat.png"' in cat["html"]


def test_links_respect_an_article_list():
    allowed = {"Cat", "Mammal", "Whale"}
    a = wiki.clean_article(tiny(), "Mammal", allowed, "test-list")
    assert a["links"] == ["Whale", "Cat"] and "Animal" in a["html"]


def test_resolve_href():
    assert wiki.resolve_href("A/Cat", "../I/x.png") == "I/x.png"
    assert wiki.resolve_href("Cat", "./Dog#History") == "Dog"
    assert wiki.resolve_href("Cat", ".NET") == ".NET"
    assert wiki.resolve_href("Cat", "Caf%C3%A9") == "Café"
    for outside in ("https://example.org", "//x", "#top", "/etc/passwd", "../../x", "mailto:a@b"):
        assert wiki.resolve_href("Cat", outside) is None


def test_lists_suggestions_pairs_and_routes():
    w = tiny()
    resolved = wiki.resolve_list(w, wiki.parse_list("# animals\nCat\nmammal\nWhale\nOcean\nEarth\nMoon\nNope"), "t1")
    assert resolved["paths"] == {"Cat", "Mammal", "Whale", "Ocean", "Earth", "Moon"} and resolved["missing"] == ["Nope"]
    assert [s["title"] for s in wiki.suggest(w, "m", resolved)] == ["Mammal", "Moon"]
    assert wiki.suggest(w, "sun")[0]["path"] == "Sun"
    best = wiki.shortest_route(w, "Cat", "Moon", None)
    assert best == {"status": "found", "route": ["Cat", "Mammal", "Whale", "Ocean", "Earth", "Moon"]}
    assert wiki.shortest_route(w, "Cat", "Moon", None, max_pages=2)["status"] == "too_far"
    assert wiki.shortest_route(w, "Egg", "Moon", {"Egg", "Moon"})["status"] == "not_found"
    for _ in range(5):
        start, goal = wiki.random_pair(w, None)
        assert goal not in wiki.links_fast(w, start, None) and start != goal


# ---------------------------------------------------------------- the race


def test_race_chain_back_and_loops():
    race = wikirace.Race(tiny(), None, "all")
    state, public = race.start("Cat", "Moon")
    assert public["page"]["title"] == "Cat" and public["steps"] == 0 and public["goal"]["title"] == "Moon"
    with pytest.raises(wikirace.RaceError):
        race.move(state, "go", {"to": "Moon"})  # not linked from Cat
    for target in ("Mammal", "Animal", "Bird"):
        state, reply, log = race.move(state, "go", {"to": target})
    assert reply["steps"] == 3 and log["title"] == "Bird"
    state, reply, _ = race.move(state, "back", {"step": 1})  # back to Mammal, free
    assert [c["title"] for c in reply["chain"]] == ["Cat", "Mammal"]
    state, reply, _ = race.move(state, "go", {"to": "Cat"})  # a loop counts as going back
    assert reply["steps"] == 0
    with pytest.raises(wikirace.RaceError):
        race.finish(state)
    for target in ("Mammal", "Whale", "Ocean", "Earth", "Moon"):
        state, reply, _ = race.move(state, "go", {"to": target})
    assert reply["done"]
    with pytest.raises(wikirace.RaceError):
        race.move(state, "go", {"to": "Earth"})
    score, detail = race.finish(state)
    assert score == 5 and detail["route"] == ["Cat", "Mammal", "Whale", "Ocean", "Earth", "Moon"]
    assert detail["pages_visited"] == 10 and detail["times_gone_back"] == 2


def test_check_pair():
    w = tiny()
    assert wikirace.check_pair(w, None, "", "") == (None, None, {})
    assert wikirace.check_pair(w, None, "cat", "space exploration")[:2] == ("Cat", "Space_exploration")
    assert "goal" in wikirace.check_pair(w, None, "Cat", "Unicorn")[2]
    assert "isn't in the chosen" in wikirace.check_pair(w, {"Cat"}, "Cat", "Moon")[2]["goal"]
    assert "different" in wikirace.check_pair(w, None, "Cat", "Cats")[2]["goal"]
    assert "start" in wikirace.check_pair(w, None, "", "Moon")[2]


# ------------------------------------------------------- through the service


def run_race(service, game, player, challenge=None, route=("Mammal", "Whale", "Ocean", "Earth", "Moon")):
    started = service.start(game, player, challenge, resume=False)
    aid = started["attempt"]["id"]
    for target in route:
        reply = service.move(game, player, aid, "go", {"to": target})
    assert reply["done"]
    return service.finish(game, player, aid, {"score": 1})  # a claimed score is ignored


def test_free_play_uses_random_pairs_and_has_no_scoreboard(blaze):
    game, service, clock, amina, ben, coach = blaze
    started = service.start(game, amina)
    assert started["public"]["page"]["path"] == started["public"]["start"]["path"]
    assert started["public"]["start"]["path"] != started["public"]["goal"]["path"]
    again = service.start(game, amina)  # picks up where she left off
    assert again["resumed"] and again["public"]["chain"] == started["public"]["chain"]
    assert service.scoreboard(game, amina)["no_scoreboard"] is True


def test_challenge_race_is_scored_by_the_server(blaze):
    game, service, clock, amina, ben, coach = blaze
    c = service.save_challenge(game, coach, {
        "title": "Cat to Moon", "class_id": CLASS_A, "settings": {"start": "cat", "goal": "moon", "list": "all"},
        "opens_at": clock().isoformat(), "closes_at": clock.t.replace(hour=17).isoformat(),
    }, {CLASS_A: "Class A"})
    assert c["start"] == "Cat" and c["goal"] == "Moon"
    assert c["best"] == {"status": "found", "steps": 5, "route": ["Cat", "Mammal", "Whale", "Ocean", "Earth", "Moon"]}
    assert "best" not in service.challenges_for(game, amina)[0]  # learners see it after closing
    result = run_race(service, game, amina, c["id"])
    assert result["attempt"]["score"] == 5 and result["standing"]["rank"] == 1
    longer = ("Pet", "Dog", "Mammal", "Milk", "Water", "Ocean", "Earth", "Moon")
    assert run_race(service, game, ben, c["id"], route=longer)["attempt"]["score"] == 8
    board = service.scoreboard(game, ben, c["id"])
    assert [r["score"] for r in board["rows"]] == [5, 8] and "route" not in board["rows"][0]
    clock.advance(9 * 3600)  # closed: routes and the shortest route are shown
    board = service.scoreboard(game, ben, c["id"])
    assert board["rows"][1]["route"][1] == "Pet" and board["challenge"]["best"]["steps"] == 5
    results = service.coach_results(game, coach, c["id"])
    moves = results["rows"][0]["history"][0]["events"]
    assert moves[0]["data"]["title"] == "Mammal"


def test_blank_pair_is_picked_once_for_the_whole_challenge(blaze):
    game, service, clock, amina, ben, coach = blaze
    c = service.save_challenge(game, coach, {"title": "Surprise", "class_id": CLASS_A, "settings": {"list": "all"}},
                               {CLASS_A: "Class A"})
    assert c["start"] and c["goal"] and c["start"] != c["goal"]
    a = service.start(game, amina, c["id"])["public"]
    b = service.start(game, ben, c["id"])["public"]
    assert a["start"] == b["start"] and a["goal"] == b["goal"]


def test_coach_article_lists(blaze):
    game, service, clock, amina, ben, coach = blaze
    saved = service.save_article_list(coach, {"name": "Space", "titles": "Earth\nMoon\nSun\nStar\nPlanet\nSpace exploration\nMars"})
    info = service.article_list(FAC, saved["id"], game)
    assert info["found"] == 6 and info["missing"] == ["Mars"]
    assert any(c["value"] == saved["value"] for c in service.schema(game, FAC)["game"][0]["choices"])
    with pytest.raises(PlatformError) as e:
        service.save_challenge(game, coach, {"title": "Space", "class_id": CLASS_A,
                                             "settings": {"list": saved["value"], "start": "Cat", "goal": "Moon"}},
                               {CLASS_A: "Class A"})
    assert "isn't in the chosen article list" in e.value.fields["start"]
    titles = [a["title"] for a in service.suggest_articles(game, FAC, "s", saved["value"])]
    assert titles == ["Space exploration", "Star", "Sun"]
    with pytest.raises(PlatformError):
        service.save_article_list(coach, {"name": "", "titles": ""})
    service.delete_article_list(coach, saved["id"])
    assert service.article_lists(FAC) == []


def test_wiki_pictures_are_served_but_articles_are_not(blaze):
    game, service, *_ = blaze
    data, mimetype = views_common.wiki_file(service, game, "I/cat.png")
    assert mimetype == "image/png" and data.startswith(b"\x89PNG")
    assert views_common.wiki_file(service, game, "Cat") is None
    assert views_common.wiki_file(service, game, "../../etc/passwd") is None
    assert views_common.wiki_file(service, folder_game("number-hunt"), "I/cat.png") is None


def test_default_list_is_the_wikipedia_for_schools_list():
    game = folder_game("wiki-blaze")
    titles = wiki.parse_list(game.source.read("lists/wikipedia-for-schools.txt")[0].decode())
    assert len(titles) > 10000 and "Abacus" in titles and not any(t.startswith("Wikipedia:") for t in titles)
    assert registry  # imported for the fixture's environment
