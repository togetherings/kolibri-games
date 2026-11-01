"""Photo packs and the photo-guess rules (BeaconHunt), with a small generated test pack."""
import os

import pytest

from kolibri_games import photoguess, photos, registry
from kolibri_games.registry import GameEntry, check
from kolibri_games.service import GameService, MemoryStore, PlatformError, Player
from kolibri_games.sources import FolderSource
from tests.helpers import ROOT, Clock
from tests.make_test_pack import make

FAC = "f" * 32
CLASS_A = "e" * 32
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "photo-game")


def photo_game():
    source = FolderSource(FIXTURE)
    manifest = source.manifest()
    return GameEntry("f-" + manifest.id, source, "folder", manifest, check(manifest, source))


@pytest.fixture
def hunt(tmp_path):
    folder = str(tmp_path / "packs")
    make(folder)
    os.environ["KOLIBRI_GAMES_DATA_PHOTO_PACKS"] = folder
    try:
        game = photo_game()
        assert game.playable, game.problems
        clock = Clock()
        service = GameService(MemoryStore(), now=clock)
        amina = Player("a" * 32, "Amina Learner", FAC, class_ids={CLASS_A})
        ben = Player("b" * 32, "Ben Learner", FAC, class_ids={CLASS_A})
        coach = Player("c" * 32, "Ms Coach", FAC, is_coach=True, coach_class_ids={CLASS_A})
        yield game, service, clock, amina, ben, coach, folder
    finally:
        del os.environ["KOLIBRI_GAMES_DATA_PHOTO_PACKS"]


def place_of(service, attempt_id, index):
    ref = service.store.attempt_get(attempt_id).state["places"][index]
    pack_id, _, place_id = ref.partition("/")
    return photos.find_packs(os.environ["KOLIBRI_GAMES_DATA_PHOTO_PACKS"])[pack_id].places[place_id]


# ----------------------------------------------------------------- packs


def test_packs_are_found_as_folders_or_zips(tmp_path):
    folder = str(tmp_path)
    make(folder)
    make(folder, as_zip=True, pack_id="zipped", title="Zipped")
    (tmp_path / "notes.txt").write_text("not a pack")
    (tmp_path / "broken").mkdir()
    packs = photos.find_packs(folder)
    assert sorted(packs) == ["test-west-africa", "zipped"]
    assert len(packs["zipped"].places) == 6 and packs["zipped"].places["0001"]["pano"] is True
    assert any("broken" in p for p in photos.pack_problems(folder))
    data, mimetype = packs["zipped"].photo(packs["zipped"].places["0003"])
    assert mimetype == "image/png" and data.startswith(b"\x89PNG")


def test_hidden_jpeg_data_is_removed():
    exif = b"Exif\x00\x00GPSLatitude=8.48"
    app1 = b"\xff\xe1" + (len(exif) + 2).to_bytes(2, "big") + exif
    app0 = b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    comment = b"\xff\xfe\x00\x07hello"
    image = b"\xff\xda\x00\x02picture-bytes\xff\xd9"
    jpeg = b"\xff\xd8" + app0 + app1 + comment + image
    cleaned = photos.strip_jpeg_metadata(jpeg)
    assert b"GPS" not in cleaned and b"hello" not in cleaned
    assert cleaned == b"\xff\xd8" + app0 + image
    assert photos.strip_jpeg_metadata(b"not a jpeg") == b"not a jpeg"


def test_points_and_distances():
    assert photoguess.points_for(True, 0) == 5000
    assert photoguess.points_for(False, 0) == 4000
    assert 2000 < photoguess.points_for(False, 500) < 2300
    assert photoguess.points_for(False, 8000) == 0
    assert 330 < photos.distance_km(8.48, -13.23, 6.32, -10.81) < 400  # Freetown to Monrovia, about 360 km


def test_places_are_spread_over_countries(tmp_path):
    make(str(tmp_path))
    packs = photos.find_packs(str(tmp_path)).values()
    refs = photoguess.pick_places(packs, 5)
    countries = {photos.find_packs(str(tmp_path))["test-west-africa"].places[r.split("/")[1]]["country"] for r in refs}
    assert len(refs) == 5 and len(countries) == 5  # 5 countries in the pack, so one photo from each


def test_the_game_needs_photo_packs(tmp_path):
    os.environ["KOLIBRI_GAMES_DATA_PHOTO_PACKS"] = str(tmp_path)
    try:
        game = photo_game()
        assert not game.playable and "needs photo packs" in " ".join(game.problems)
    finally:
        del os.environ["KOLIBRI_GAMES_DATA_PHOTO_PACKS"]


# ------------------------------------------------------------ playing


def test_a_full_game_is_scored_by_the_server(hunt):
    game, service, clock, amina, ben, coach, folder = hunt
    started = service.start(game, amina)
    aid, public = started["attempt"]["id"], started["public"]
    assert public["rounds"] == 3 and public["round"] == 1 and public["photo"]["url"] == "__photos__/%d/0" % aid
    assert "lat" not in str(public) and "country" not in str(public)  # nothing gives the answer away
    # Only rounds already reached can be fetched, and only by the player.
    assert service.attempt_photo(game, amina.id, aid, 0)[1] == "image/png"
    assert service.attempt_photo(game, amina.id, aid, 1) is None
    assert service.attempt_photo(game, ben.id, aid, 0) is None
    with pytest.raises(PlatformError):
        service.move(game, amina, aid, "guess", {"country": "ATLANTIS"})
    total = 0
    for i in range(3):
        answer = place_of(service, aid, i)["country"]
        guess = answer if i < 2 else "FRA"
        reply = service.move(game, amina, aid, "guess", {"country": guess})
        result = reply["result"]
        assert result["answer"] == answer and result["correct"] == (i < 2)
        assert result["credit"]["source"] == "Mapillary" and result["lat"]
        total += result["points"]
        assert reply["done"] == (i == 2)
    assert result["points"] < 400  # France is far from West Africa
    with pytest.raises(PlatformError):
        service.move(game, amina, aid, "guess", {"country": "SLE"})
    done = service.finish(game, amina, aid, {"score": 999999})  # a claimed score is ignored
    assert done["attempt"]["score"] == total and done["attempt"]["detail"]["correct"] == 2


def test_finishing_early_is_refused_and_resuming_keeps_the_round(hunt):
    game, service, clock, amina, *_ = hunt
    aid = service.start(game, amina)["attempt"]["id"]
    service.move(game, amina, aid, "guess", {"country": "SLE"})
    with pytest.raises(PlatformError):
        service.finish(game, amina, aid, {})
    again = service.start(game, amina)
    assert again["resumed"] and again["public"]["round"] == 2 and len(again["public"]["results"]) == 1


def test_regions_and_settings(hunt):
    game, service, clock, amina, ben, coach, folder = hunt
    choices = service.schema(game, FAC)["game"][0]["choices"]
    assert [c["value"] for c in choices] == ["world", "test-west-africa"]
    service.save_settings(game, FAC, {}, {"region": "test-west-africa", "rounds": 2}, coach.id)
    assert service.start(game, amina, resume=False)["public"]["rounds"] == 2
    with pytest.raises(PlatformError) as e:
        service.save_settings(game, FAC, {}, {"region": "east-asia"}, coach.id)
    assert "region" in e.value.fields


def test_a_challenge_gives_everyone_the_same_hidden_photos(hunt):
    game, service, clock, amina, ben, coach, folder = hunt
    c = service.save_challenge(game, coach, {"title": "Coast", "class_id": CLASS_A,
                                             "settings": {"region": "test-west-africa", "rounds": 4}}, {CLASS_A: "Class A"})
    assert "_places" not in c["settings"]  # the picked places stay on the server
    assert "_places" not in str(service.context(game, amina, c["id"]).settings)
    a = service.start(game, amina, c["id"])["attempt"]["id"]
    b = service.start(game, ben, c["id"])["attempt"]["id"]
    assert service.store.attempt_get(a).state["places"] == service.store.attempt_get(b).state["places"]
    assert len(service.store.attempt_get(a).state["places"]) == 4
    # Changing only the name keeps the same photos.
    again = service.save_challenge(game, coach, {"title": "Coast 2", "class_id": CLASS_A,
                                                 "settings": {"region": "test-west-africa", "rounds": 4}},
                                   {CLASS_A: "Class A"}, c["id"])
    assert service.store.challenge_get(again["id"]).settings["_places"] == service.store.attempt_get(a).state["places"]


def test_setup_lists_packs(hunt):
    status = registry.photo_packs_status()
    assert [p["id"] for p in status["packs"]] == ["test-west-africa"] and status["packs"][0]["places"] == 6
    assert registry.check_data_source("photo-packs", "/no/such/folder")
    assert registry.check_data_source("photo-packs", "") is None
