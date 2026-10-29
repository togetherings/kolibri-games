"""
Finds games on this device. No Django imports at module level (Kolibri's
content tables are only touched inside functions, and only when Kolibri is
running).

* Free-play Games: zip files in the plugin's games folder
  (``$KOLIBRI_HOME/kolibri_games/games``), put there by the Setup page's
  install button (see install.py) or copied by hand. Game authors can also add
  folders with ``KOLIBRI_GAMES_PATH``; a game folder there works like a zip.
* Classroom Games: HTML5 apps (.zip) in Kolibri channels that contain a
  ``kolibri-game.json`` with ``"type": "classroom"``. Every resource with the
  same manifest id is one game. Other HTML5 apps are left alone.

Each game gets a stable *key* used in addresses and in the database:
``f-<manifest id>`` for Free-play Games and ``c-<manifest id>`` for Classroom
Games. Files that look like games but can't be used get an ``x-`` key, so
administrators can see what's wrong on the Setup page.
"""
import hashlib
import json
import logging
import os
import re
import threading
import time

from . import __version__
from . import classroom
from .manifest import ManifestError
from .sources import FolderSource, SourceError, ZipSource
from .versions import satisfies

logger = logging.getLogger(__name__)

KEY_RE = re.compile(r"^[a-z]-[a-z0-9._-]{1,100}$")
FREE_PLAY_PREFIX = "f-"
BROKEN_PREFIX = "x-"
#: How long the list of games is reused before looking at the disk again.
CACHE_SECONDS = 15


def kolibri_home():
    try:
        from kolibri.utils.conf import KOLIBRI_HOME

        return KOLIBRI_HOME
    except Exception:
        return os.environ.get("KOLIBRI_HOME", os.path.expanduser("~/.kolibri"))


def plugin_home():
    return os.path.join(kolibri_home(), "kolibri_games")


def games_dir():
    """Where installed Free-play Games live."""
    return os.path.join(plugin_home(), "games")


def local_game_dirs():
    """The games folder, then any folders in KOLIBRI_GAMES_PATH (for game authors)."""
    dirs = [games_dir()]
    extra = os.environ.get("KOLIBRI_GAMES_PATH", "")
    dirs += [d for d in extra.split(os.pathsep) if d.strip()]
    return dirs


# ------------------------------------------------------------- data sources
#
# Large data a game needs from the device, by name. For now that's only
# "wikipedia": the path of a Wikipedia .zim file (or, for testing, a folder of
# .html articles). Administrators choose it on the Setup page, which writes
# data_sources.json; KOLIBRI_GAMES_DATA_<NAME> variables also work.

#: Folders searched for .zim files to offer on the Setup page (IIAB keeps them in /library/zims/content).
ZIM_FOLDERS = ["/library/zims/content", "/library/zims", "/opt/iiab/zims"]


def data_sources_file():
    return os.path.join(plugin_home(), "data_sources.json")


def data_sources():
    """name -> path, from data_sources.json plus KOLIBRI_GAMES_DATA_<NAME> variables."""
    found = {}
    try:
        with open(data_sources_file()) as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            found.update({str(k): str(v) for k, v in loaded.items()})
    except (OSError, ValueError):
        pass
    for var, value in os.environ.items():
        if var.startswith("KOLIBRI_GAMES_DATA_") and value:
            found[var[len("KOLIBRI_GAMES_DATA_"):].lower().replace("_", "-")] = value
    return found


def set_data_source(name, path):
    """Save (or with path None, forget) one data source in data_sources.json."""
    current = {}
    try:
        with open(data_sources_file()) as f:
            current = json.load(f) or {}
    except (OSError, ValueError):
        pass
    if path:
        current[name] = path
    else:
        current.pop(name, None)
    os.makedirs(plugin_home(), exist_ok=True)
    tmp = data_sources_file() + ".tmp"
    with open(tmp, "w") as f:
        json.dump(current, f, indent=1)
    os.replace(tmp, data_sources_file())
    refresh()


def zim_candidates():
    """ZIM files found in the usual places, for the Setup page's chooser. Looks one level deep only."""
    found = []
    folders = ZIM_FOLDERS + [os.path.join(plugin_home(), "data")]
    for folder in folders:
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for name in names[:500]:
            path = os.path.join(folder, name)
            if name.lower().endswith(".zim") and os.path.isfile(path):
                found.append({"path": path, "name": name, "size": os.path.getsize(path)})
    return found


# -------------------------------------------------------------------- games


class GameEntry(object):
    """A Free-play Game, or a file that looks like a game but can't be used."""

    is_classroom = False

    def __init__(self, key, source, origin, manifest=None, problems=None, content=None):
        self.key = key
        self.source = source
        self.origin = origin  # "installed" (games folder), "folder" (KOLIBRI_GAMES_PATH) or "channel"
        self.manifest = manifest
        self.problems = problems or []  # reasons the game can't be played
        self.notes = []  # things worth knowing that don't stop it (like a second copy)
        self.content = content or {}

    @property
    def playable(self):
        return self.manifest is not None and not self.problems

    @property
    def title(self):
        if self.manifest:
            return self.manifest.title
        return self.content.get("title") or os.path.basename(self.source.location)

    def data_paths(self):
        configured = data_sources()
        return {d["name"]: configured[d["name"]] for d in (self.manifest.data if self.manifest else []) if d["name"] in configured}

    def describe(self):
        return {
            "key": self.key,
            "origin": self.origin,
            "kind": self.source.kind,
            "type": self.manifest.type if self.manifest else None,
            "location": self.source.location,
            "title": self.title,
            "version": self.manifest.version if self.manifest else None,
            "id": self.manifest.id if self.manifest else None,
            "playable": self.playable,
            "problems": self.problems,
            "notes": self.notes,
            "content": self.content,
        }


def check(manifest, source):
    """Reasons this device can't run a Free-play Game (empty list = playable)."""
    if manifest.is_classroom:
        return [
            "This is a Classroom Game. Classroom Games are HTML5 apps: add its .zip to a channel "
            "(for example with Kolibri Studio) so learners open it from Learn."
        ]
    problems = []
    if manifest.requires_platform and not satisfies(__version__, manifest.requires_platform):
        problems.append(
            "This game needs Kolibri Games %s, but this device has %s. Ask your administrator to update the Kolibri Games plugin."
            % (manifest.requires_platform, __version__)
        )
    configured = data_sources()
    for d in manifest.data:
        if d.get("required", True) and d["name"] not in configured:
            problems.append(
                "This game needs the '%s' data source. An administrator can choose it on the Setup page." % d["name"]
            )
    if not source.exists(manifest.entry):
        problems.append("The game's start page (%s) is missing." % manifest.entry)
    return problems


def broken_key(location):
    return BROKEN_PREFIX + hashlib.sha1(location.encode("utf-8")).hexdigest()[:16]


def load(source, origin):
    """A GameEntry for one zip or folder."""
    try:
        manifest = source.manifest()
    except (ManifestError, SourceError) as e:
        problems = e.problems if isinstance(e, ManifestError) else [str(e)]
        return GameEntry(broken_key(source.location), source, origin, None, ["Invalid game: %s" % p for p in problems])
    except Exception as e:  # unreadable file, ...
        return GameEntry(broken_key(source.location), source, origin, None, ["Invalid game: %s" % e])
    problems = check(manifest, source)
    key = FREE_PLAY_PREFIX + manifest.id if not manifest.is_classroom else broken_key(source.location)
    return GameEntry(key, source, origin, manifest, problems)


def _local_games():
    entries = []
    for i, base in enumerate(local_game_dirs()):
        if not os.path.isdir(base):
            continue
        origin = "installed" if i == 0 else "folder"
        for name in sorted(os.listdir(base)):
            if name.startswith("."):
                continue  # .previous (kept versions) and partial uploads
            path = os.path.join(base, name)
            if os.path.isdir(path) and os.path.exists(os.path.join(path, "kolibri-game.json")):
                entries.append(load(FolderSource(path), origin))
            elif name.lower().endswith(".zip") and os.path.isfile(path):
                entries.append(load(ZipSource(path), origin))
    return entries


# ------------------------------------------------------- Classroom Games


def _channel_files(extension, kind=None, preset=None):
    """(path, content dict, file id) for every available file of this type in Kolibri's channels."""
    try:
        from kolibri.core.content.models import File
        from kolibri.core.content.utils.paths import get_content_storage_file_path
    except Exception:
        return []  # not running inside Kolibri
    found = []
    try:
        files = File.objects.filter(local_file__extension=extension, local_file__available=True)
        if kind:
            files = files.filter(contentnode__kind=kind, contentnode__available=True)
        if preset:
            files = files.filter(preset=preset)
        for f in files.select_related("local_file", "contentnode").order_by("contentnode__title"):
            node = f.contentnode
            path = get_content_storage_file_path("%s.%s" % (f.local_file.id, f.local_file.extension))
            if path and os.path.isfile(path):
                content = {
                    "content_id": node.content_id,
                    "node_id": node.id,
                    "title": node.title,
                    "channel_id": node.channel_id,
                }
                found.append((path, content, f.local_file.id))
    except Exception:
        logger.exception("Kolibri Games: could not list %s files in channels", extension)
    return found


#: Classroom Game resources added by the preview server: [(source, content dict)].
PREVIEW_CLASSROOM = []

# file id (a checksum, so the file never changes) -> (manifest, or None if broken, or False if not a game; problems)
_zip_cache = {}


def _zip_manifest(path, file_id):
    """Read a channel zip's manifest once; afterwards the answer is remembered by checksum."""
    if file_id in _zip_cache:
        return _zip_cache[file_id]
    source = ZipSource(path)
    if not source.has_manifest():
        result = (False, [])  # an ordinary HTML5 app
    else:
        try:
            result = (source.manifest(), [])
        except (ManifestError, SourceError) as e:
            result = (None, e.problems if isinstance(e, ManifestError) else [str(e)])
        except Exception as e:
            result = (None, [str(e)])
    if len(_zip_cache) > 5000:
        _zip_cache.clear()
    _zip_cache[file_id] = result
    return result


def _classroom_games():
    """(Classroom Games, entries for broken ones)."""
    resources, broken = [], []
    found = [(ZipSource(p), c, fid) for p, c, fid in _channel_files("zip", kind="html5", preset="html5_zip")]
    found += [(s, c, None) for s, c in PREVIEW_CLASSROOM]
    for source, content, file_id in found:
        if file_id is not None:
            manifest, problems = _zip_manifest(source.location, file_id)
        else:
            try:
                manifest, problems = source.manifest(), []
            except (ManifestError, SourceError) as e:
                manifest, problems = None, e.problems if isinstance(e, ManifestError) else [str(e)]
        if manifest is False:
            continue
        key = BROKEN_PREFIX + content["content_id"]
        if manifest is None:
            broken.append(GameEntry(key, source, "channel", None, ["Invalid game: %s" % p for p in problems], content))
        elif not manifest.is_classroom:
            broken.append(GameEntry(key, source, "channel", None, [
                "This HTML5 app is a Free-play Game. Free-play Games aren't played from channels: "
                "an administrator installs the .zip on the games page's Setup page."
            ], content))
        elif manifest.requires_platform and not satisfies(__version__, manifest.requires_platform):
            broken.append(GameEntry(key, source, "channel", None, [
                "This game needs Kolibri Games %s, but this device has %s." % (manifest.requires_platform, __version__)
            ], content))
        else:
            resources.append(classroom.ClassroomResource(source, manifest, content))
    return classroom.group_resources(resources), broken


# ------------------------------------------------------------------ cache

_cache = {"at": 0, "games": None}
_cache_lock = threading.Lock()


def discover(refresh=False):
    """All games found, in display order. Cached for a few seconds."""
    with _cache_lock:
        if not refresh and _cache["games"] is not None and time.time() - _cache["at"] < CACHE_SECONDS:
            return _cache["games"]
        games, seen = [], {}
        classroom_games, broken = _classroom_games()
        for entry in _local_games() + classroom_games + broken:
            if entry.key in seen:
                seen[entry.key].notes.append(
                    "Another copy of this game was also found at %s and ignored." % entry.source.location
                )
                continue
            seen[entry.key] = entry
            games.append(entry)
        games.sort(key=lambda g: (not g.playable, g.title.lower()))
        _cache.update(at=time.time(), games=games)
        return games


def refresh():
    """Forget the cached list (after installing or removing a game)."""
    with _cache_lock:
        _cache["games"] = None


def get(key, refresh=False):
    if not isinstance(key, str) or not KEY_RE.match(key):
        return None
    for entry in discover(refresh=refresh):
        if entry.key == key:
            return entry
    if not refresh:
        return get(key, refresh=True)
    return None
