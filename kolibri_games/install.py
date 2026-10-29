"""
Installing Free-play Games: a device administrator uploads a game's .zip on
the Setup page, and it's checked and saved in the games folder. No Django
imports.

The games folder (``$KOLIBRI_HOME/kolibri_games/games``) looks like this::

    games/
      org.togetherings.number-hunt.zip      installed games, named <game id>.zip
      org.togetherings.wiki-blaze.zip
      .previous/
        org.togetherings.wiki-blaze.zip     the version before the last update
      .incoming/                            uploads in progress

* Installing a newer (or older) version of a game keeps the replaced file in
  .previous, so an administrator can go back to it. Only one previous version
  is kept.
* Removing a game deletes its files. Learners' results stay in the database,
  so they come back if the game is installed again.
* A zip can also be copied into the games folder by hand; it's found the same
  way (see registry.py).
"""
import os
import shutil
import uuid

from . import registry
from .manifest import ManifestError
from .sources import SourceError, ZipSource, forget_zip

#: Uploads bigger than this are refused (big data, like Wikipedia, is a data source, not part of a game).
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
CHUNK = 1024 * 1024


class InstallError(Exception):
    pass


def previous_dir():
    return os.path.join(registry.games_dir(), ".previous")


def incoming_dir():
    return os.path.join(registry.games_dir(), ".incoming")


def save_upload(chunks):
    """Write uploaded bytes (an iterable of byte strings) to a temporary file and return its path."""
    os.makedirs(incoming_dir(), exist_ok=True)
    path = os.path.join(incoming_dir(), uuid.uuid4().hex + ".zip")
    size = 0
    try:
        with open(path, "wb") as f:
            for chunk in chunks:
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise InstallError("That file is too big. Games can be at most %d MB." % (MAX_UPLOAD_BYTES // (1024 * 1024)))
                f.write(chunk)
    except BaseException:
        _remove(path)
        raise
    if size == 0:
        _remove(path)
        raise InstallError("The file was empty.")
    return path


def _remove(path):
    try:
        forget_zip(path)
        os.remove(path)
    except OSError:
        pass


def _installed_files(game_id):
    """Zips in the games folder that hold this game (normally just <id>.zip)."""
    found = []
    base = registry.games_dir()
    if not os.path.isdir(base):
        return found
    for name in os.listdir(base):
        path = os.path.join(base, name)
        if name.startswith(".") or not name.lower().endswith(".zip") or not os.path.isfile(path):
            continue
        try:
            if ZipSource(path).manifest().id == game_id:
                found.append(path)
        except (ManifestError, SourceError, Exception):
            continue
    return found


def install(upload_path):
    """Check an uploaded zip and install it. Returns {"game", "replaced", "problems"}.

    ``problems`` are things to fix before the game can be played (for example a
    data source to choose); the game is installed anyway.
    """
    source = ZipSource(upload_path)
    try:
        if not source.has_manifest():
            raise InstallError(
                "This zip has no kolibri-game.json at its top level, so it isn't a Kolibri Games game. "
                "(If you zipped a folder, zip the files inside it instead.)"
            )
        try:
            manifest = source.manifest()
        except ManifestError as e:
            raise InstallError("This game's kolibri-game.json has problems: " + " ".join(e.problems))
        except SourceError as e:
            raise InstallError(str(e))
        if manifest.is_classroom:
            raise InstallError(
                "This is a Classroom Game. Classroom Games aren't installed here: add the zip to a "
                "channel (for example with Kolibri Studio) so learners open it from Learn."
            )
        if not source.exists(manifest.entry):
            raise InstallError("The game's start page (%s) isn't in the zip." % manifest.entry)
    except InstallError:
        _remove(upload_path)
        raise

    target = os.path.join(registry.games_dir(), manifest.id + ".zip")
    replaced = None
    old_files = _installed_files(manifest.id)
    if old_files:
        # Keep the version being replaced, so it can be restored.
        os.makedirs(previous_dir(), exist_ok=True)
        keep = target if target in old_files else old_files[0]
        replaced = ZipSource(keep).manifest().version
        forget_zip(keep)
        os.replace(keep, os.path.join(previous_dir(), manifest.id + ".zip"))
        for extra in old_files:
            if extra != keep:
                _remove(extra)
    forget_zip(upload_path)
    os.replace(upload_path, target)
    registry.refresh()
    entry = registry.get(registry.FREE_PLAY_PREFIX + manifest.id, refresh=True)
    return {
        "game": {"key": registry.FREE_PLAY_PREFIX + manifest.id, "title": manifest.title, "version": manifest.version},
        "replaced": replaced,
        "problems": entry.problems if entry else [],
    }


def previous_version(game_id):
    """The version kept in .previous for this game, or None."""
    path = os.path.join(previous_dir(), game_id + ".zip")
    if not os.path.isfile(path):
        return None
    try:
        return ZipSource(path).manifest().version
    except Exception:
        return None


def restore_previous(game_id):
    """Swap the installed version and the kept previous version."""
    kept = os.path.join(previous_dir(), game_id + ".zip")
    if not os.path.isfile(kept):
        raise InstallError("There's no earlier version of this game to go back to.")
    current = os.path.join(registry.games_dir(), game_id + ".zip")
    swap = os.path.join(previous_dir(), game_id + ".swap")
    forget_zip(current)
    forget_zip(kept)
    if os.path.isfile(current):
        os.replace(current, swap)
    os.replace(kept, current)
    if os.path.isfile(swap):
        os.replace(swap, kept)
    registry.refresh()
    return {"version": ZipSource(current).manifest().version}


def remove(game_id):
    """Delete a game's files (results stay in the database)."""
    files = _installed_files(game_id)
    kept = os.path.join(previous_dir(), game_id + ".zip")
    if os.path.isfile(kept):
        files.append(kept)
    if not files:
        raise InstallError("This game wasn't installed from the Setup page, so it can't be removed here.")
    for path in files:
        _remove(path)
    registry.refresh()
    return {"ok": True}


def clear_incoming():
    """Delete uploads left behind by a server restart."""
    shutil.rmtree(incoming_dir(), ignore_errors=True)
