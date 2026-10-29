"""Packing games as zips, and installing, updating, rolling back and removing them."""
import json
import os
import zipfile

import pytest

from kolibri_games import install, registry
from kolibri_games.pack import PackError, main, pack, verify
from kolibri_games.sources import ZipSource
from tests.helpers import GAMES, ROOT


@pytest.fixture
def home(tmp_path):
    os.environ["KOLIBRI_HOME"] = str(tmp_path)
    registry.refresh()
    try:
        yield tmp_path
    finally:
        del os.environ["KOLIBRI_HOME"]
        registry.refresh()


def packed(tmp_path, name, version=None):
    folder = os.path.join(GAMES, name)
    out = str(tmp_path / ("%s-%s.zip" % (name, version or "x")))
    path, manifest = pack(folder, out)
    if version:  # rewrite the version inside the zip
        z = zipfile.ZipFile(path)
        files = {n: z.read(n) for n in z.namelist()}
        z.close()
        data = json.loads(files["kolibri-game.json"])
        data["version"] = version
        files["kolibri-game.json"] = json.dumps(data).encode()
        with zipfile.ZipFile(path, "w") as z:
            for n, b in files.items():
                z.writestr(n, b)
    return path


def test_pack_makes_a_zip_with_the_files_at_the_top(tmp_path):
    path, manifest = pack(os.path.join(GAMES, "number-hunt"), str(tmp_path / "nh.zip"))
    names = zipfile.ZipFile(path).namelist()
    assert "kolibri-game.json" in names and "index.html" in names
    assert verify(ZipSource(path))[1] == []
    with pytest.raises(PackError):
        pack(str(tmp_path), str(tmp_path / "nothing.zip"))  # no manifest
    with pytest.raises(SystemExit) as e:
        main(["--check", path])
    assert e.value.code == 0


def test_classroom_examples_check_but_need_their_app(tmp_path):
    manifest, problems = verify(ZipSource(str(tmp_path / "missing.zip")))
    assert manifest is None and problems
    from kolibri_games.sources import FolderSource

    m, problems = verify(FolderSource(os.path.join(ROOT, "examples", "classroom-games", "lit")))
    assert m.is_classroom and "index.html" in " ".join(problems)


def test_install_update_rollback_and_remove(home, tmp_path):
    first = install.install(install.save_upload([open(packed(tmp_path, "memory-match", "1.0.0"), "rb").read()]))
    assert first["game"]["key"] == "f-org.togetherings.memory-match" and first["replaced"] is None
    entry = registry.get("f-org.togetherings.memory-match", refresh=True)
    assert entry.playable and entry.origin == "installed" and entry.manifest.version == "1.0.0"
    assert os.path.isfile(os.path.join(registry.games_dir(), "org.togetherings.memory-match.zip"))

    second = install.install(install.save_upload([open(packed(tmp_path, "memory-match", "1.1.0"), "rb").read()]))
    assert second["replaced"] == "1.0.0"
    assert install.previous_version("org.togetherings.memory-match") == "1.0.0"
    assert registry.get("f-org.togetherings.memory-match", refresh=True).manifest.version == "1.1.0"

    assert install.restore_previous("org.togetherings.memory-match") == {"version": "1.0.0"}
    assert install.previous_version("org.togetherings.memory-match") == "1.1.0"
    assert registry.get("f-org.togetherings.memory-match", refresh=True).manifest.version == "1.0.0"

    install.remove("org.togetherings.memory-match")
    assert registry.get("f-org.togetherings.memory-match", refresh=True) is None
    assert install.previous_version("org.togetherings.memory-match") is None
    with pytest.raises(install.InstallError):
        install.remove("org.togetherings.memory-match")


def test_install_refuses_things_that_arent_free_play_games(home, tmp_path):
    def zipped(files):
        path = str(tmp_path / "upload.zip")
        with zipfile.ZipFile(path, "w") as z:
            for n, b in files.items():
                z.writestr(n, b)
        return open(path, "rb").read()

    lit = open(os.path.join(ROOT, "examples", "classroom-games", "lit", "kolibri-game.json")).read()
    cases = {
        "Classroom Game": {"kolibri-game.json": lit, "index.html": "<p>"},
        "no kolibri-game.json at its top": {"game/kolibri-game.json": lit},
        "has problems": {"kolibri-game.json": '{"format": 1}'},
        "start page": {"kolibri-game.json": json.dumps({"format": 1, "id": "org.example.x", "version": "1.0.0", "title": "X"})},
    }
    for expected, files in cases.items():
        with pytest.raises(install.InstallError) as e:
            install.install(install.save_upload([zipped(files)]))
        assert expected in str(e.value), (expected, str(e.value))
    with pytest.raises(install.InstallError):
        install.save_upload([b""])
    old = install.MAX_UPLOAD_BYTES
    install.MAX_UPLOAD_BYTES = 10
    try:
        with pytest.raises(install.InstallError):
            install.save_upload([b"x" * 6, b"x" * 6])
    finally:
        install.MAX_UPLOAD_BYTES = old
    assert os.listdir(install.incoming_dir()) == []  # nothing left behind
