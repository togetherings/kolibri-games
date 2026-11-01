"""Reading a real Wikipedia-style ZIM file. Skipped if libzim isn't installed."""
import pytest

pytest.importorskip("libzim")

from kolibri_games import wiki  # noqa: E402
from tests.make_test_zim import build  # noqa: E402


def test_wiki_blaze_reads_a_zim_file(tmp_path):
    path = build(str(tmp_path / "tiny.zim"))
    w = wiki.open_wiki(path)
    assert isinstance(w, wiki.ZimWiki)
    assert w.find("cat") == ("Cat", "Cat")
    assert w.article("Cats") == ("Cat", "Cat")  # redirect
    assert w.article("I/cat.png") is None and w.read_file("I/cat.png")[1] == "image/png"
    a = wiki.clean_article(w, "Mammal", None)
    assert a["links"] == ["Animal", "Milk", "Whale", "Cat"]
    assert wiki.shortest_route(w, "Cat", "Moon", None)["route"] == ["Cat", "Mammal", "Whale", "Ocean", "Earth", "Moon"]
    start, goal = wiki.random_pair(w, None)
    assert start != goal
    assert w.random_article()
    assert "Moon" in [s["path"] for s in wiki.suggest(w, "Moon")]  # an exact title always works
    try:  # libzim's own suggestions (reported, not required: some versions return none)
        from libzim.suggestion import SuggestionSearcher

        r = SuggestionSearcher(w.archive).suggest("moo")
        detail = "estimated %s, results %s" % (r.getEstimatedMatches(), list(r.getResults(0, 10)))
    except Exception as e:  # noqa: BLE001
        detail = repr(e)
    import libzim

    print("::notice title=libzim suggestions::libzim %s: %s" % (getattr(libzim, "__version__", "?"), detail))
