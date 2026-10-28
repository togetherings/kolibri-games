"""Packing games as ZIMs and playing them from the ZIM. Skipped if libzim isn't installed."""
import os

import pytest

from kolibri_games import registry
from kolibri_games.pack import default_illustration, png_size
from kolibri_games.service import GameService, MemoryStore, Player
from tests.helpers import GAMES

libzim = pytest.importorskip("libzim")

from kolibri_games.pack import pack, verify  # noqa: E402
from kolibri_games.sources import ZimSource  # noqa: E402


def test_default_illustration_is_a_48px_png():
    assert png_size(default_illustration("#2f6f8f")) == (48, 48)


def test_pack_and_play_from_zim(tmp_path):
    out = tmp_path / "games"
    out.mkdir()
    paths = [pack(os.path.join(GAMES, name), str(out / (name + ".zim")), quiet=True) for name in sorted(os.listdir(GAMES))]
    for path in paths:
        m = verify(path)
        src = ZimSource(path)
        assert src.read("__kolibri_games__/sdk.js")[1] == "text/javascript"
        assert src.read(m.entry)[1].startswith("text/html")
        assert src.read("icon.svg")[1] == "image/svg+xml"

    os.environ["KOLIBRI_HOME"] = str(tmp_path / "home")
    os.environ["KOLIBRI_GAMES_PATH"] = str(out)
    try:
        games = {g.key: g for g in registry.discover(refresh=True)}
        game = games["l-org.togetherings.number-hunt"]
        assert game.source.kind == "zim" and game.playable, game.problems
        service = GameService(MemoryStore())
        player = Player("a" * 32, "Amina", "f" * 32)
        aid = service.start(game, player)["attempt"]["id"]
        secret = service.store.attempt_get(aid).vstate["secret"]
        service.event(game, player, aid, "guess", {"value": secret})
        assert service.finish(game, player, aid, {})["attempt"]["score"] == 1
    finally:
        del os.environ["KOLIBRI_GAMES_PATH"]
        del os.environ["KOLIBRI_HOME"]
        registry.discover(refresh=True)
