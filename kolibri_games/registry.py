"""
Finds games on this device:

* Standalone Games: ZIM resources in Kolibri channels that contain a
  ``kolibri-game.json`` (normal ZIMs, like Wikipedia, are ignored)
* Standalone Games placed in the local games folders
  (``$KOLIBRI_HOME/kolibri_games/games`` and any folders in
  ``KOLIBRI_GAMES_PATH``), either as .zim files or as plain folders, which is
  handy while making a game
* Lesson Games: HTML5 app resources (.zip) in Kolibri channels that contain a
  ``kolibri-game.json`` with ``"type": "lesson"``. Every resource with the same
  manifest id is one game. Other HTML5 apps are left alone.

Each game gets a stable *key* used in URLs and in the database:
``c-<content_id>`` for channel games, ``l-<manifest id>`` for local games and
``g-<manifest id>`` for Lesson Games.
"""
import json
import logging
import os
import re
import threading
import time

from . import __version__
from . import lessons
from . import validators
from .manifest import ManifestError
from .sources import FolderSource, SourceError, ZimSource, ZipSource
from .versions import satisfies

logger = logging.getLogger(__name__)

KEY_RE = re.compile(r"^[a-z]-[a-z0-9._-]{1,100}$")
CACHE_SECONDS = 15


def kolibri_home():
    try:
        from kolibri.utils.conf import KOLIBRI_HOME

        return KOLIBRI_HOME
    except Exception:
        return os.environ.get("KOLIBRI_HOME", os.path.expanduser("~/.kolibri"))


def plugin_home():
    return os.path.join(kolibri_home(), "kolibri_games")


def local_game_dirs():
    dirs = [os.path.join(plugin_home(), "games")]
    extra = os.environ.get("KOLIBRI_GAMES_PATH", "")
    dirs += [d for d in extra.split(os.pathsep) if d.strip()]
    return dirs


# ------------------------------------------------------------- data sources


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


# -------------------------------------------------------------------- games


class GameEntry(object):
    """A Standalone Game, or a file that looks like a game but can't be used."""

    is_lesson = False

    def __init__(self, key, source, origin, manifest=None, problems=None, content=None):
        self.key = key
        self.source = source
        self.origin = origin  # "channel" or "local"
        self.manifest = manifest
        self.problems = problems or []
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
            "content": self.content,
        }


def check(manifest, source):
    """Reasons this device can't run the game (empty list = playable)."""
    problems = []
    if manifest.is_lesson:
        return [
            "This is a Lesson Game. Lesson Games are HTML5 apps: add its .zip to a channel "
            "(for example with Kolibri Studio) so learners open it from Learn."
        ]
    if manifest.requires_platform and not satisfies(__version__, manifest.requires_platform):
        problems.append(
            "This game needs Kolibri Games %s, but this device has %s. Ask your administrator to update the Kolibri Games plugin."
            % (manifest.requires_platform, __version__)
        )
    if manifest.validator and validators.get(manifest.validator) is None:
        problems.append(
            "This game needs the '%s' rule checker, which isn't installed on this device." % manifest.validator
        )
    configured = data_sources()
    for d in manifest.data:
        if d.get("required", True) and d["name"] not in configured:
            problems.append("This game needs the '%s' data source, which isn't set up on this device." % d["name"])
    if not source.exists(manifest.entry):
        problems.append("The game's start page (%s) is missing." % manifest.entry)
    return problems


def _load(key, source, origin, content=None):
    try:
        manifest = source.manifest()
    except (ManifestError, SourceError) as e:
        problems = e.problems if isinstance(e, ManifestError) else [str(e)]
        return GameEntry(key, source, origin, None, ["Invalid game: %s" % p for p in problems], content)
    except Exception as e:  # unreadable file, bad UTF-8, ...
        return GameEntry(key, source, origin, None, ["Invalid game: %s" % e], content)
    if key is None:
        key = "l-" + manifest.id
    return GameEntry(key, source, origin, manifest, check(manifest, source), content)


def _local_games():
    entries = []
    for base in local_game_dirs():
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            path = os.path.join(base, name)
            if os.path.isdir(path) and os.path.exists(os.path.join(path, "kolibri-game.json")):
                entries.append(_load(None, FolderSource(path), "local"))
            elif name.lower().endswith(".zim") and os.path.isfile(path):
                source = ZimSource(path)
                if source.has_manifest():
                    entries.append(_load(None, source, "local"))
    return entries


def _channel_files(extension, kind=None, preset=None):
    """(path, content dict, file id) for every available file of this type in Kolibri's channels."""
    try:
        from kolibri.core.content.models import File
        from kolibri.core.content.utils.paths import get_content_storage_file_path
    except Exception:
        return []
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


#: Lesson Game resources added by the preview server: [(source, content dict)].
PREVIEW_LESSONS = []

# file id (a checksum, so the file never changes) -> (manifest or None, problems)
_zip_cache = {}


def _zip_manifest(path, file_id):
    if file_id in _zip_cache:
        return _zip_cache[file_id]
    source = ZipSource(path)
    result = (None, [])
    if source.has_manifest():
        try:
            result = (source.manifest(), [])
        except (ManifestError, SourceError) as e:
            result = (None, e.problems if isinstance(e, ManifestError) else [str(e)])
        except Exception as e:  # bad UTF-8, ...
            result = (None, [str(e)])
    else:
        result = (False, [])
    if len(_zip_cache) > 5000:
        _zip_cache.clear()
    _zip_cache[file_id] = result
    return result


def _lesson_games():
    """(Lesson Games, entries for broken ones)."""
    resources, broken = [], []
    found = [(ZipSource(p), c, fid) for p, c, fid in _channel_files("zip", kind="html5", preset="html5_zip")]
    found += [(s, c, None) for s, c in PREVIEW_LESSONS]
    for source, content, file_id in found:
        if file_id is not None:
            manifest, problems = _zip_manifest(source.location, file_id)
        else:
            try:
                manifest, problems = source.manifest(), []
            except (ManifestError, SourceError) as e:
                manifest, problems = None, e.problems if isinstance(e, ManifestError) else [str(e)]
        if manifest is False:
            continue  # an ordinary HTML5 app
        if manifest is None:
            broken.append(GameEntry("c-" + content["content_id"], source, "channel", None,
                                    ["Invalid game: %s" % p for p in problems], content))
        elif not manifest.is_lesson:
            broken.append(GameEntry("c-" + content["content_id"], source, "channel", None,
                                    ["This HTML5 app has a kolibri-game.json for a Standalone Game. "
                                     "Standalone Games are packed as .zim files (see kolibri-games-pack)."], content))
        elif manifest.requires_platform and not satisfies(__version__, manifest.requires_platform):
            broken.append(GameEntry("c-" + content["content_id"], source, "channel", None,
                                    ["This game needs Kolibri Games %s, but this device has %s."
                                     % (manifest.requires_platform, __version__)], content))
        else:
            resources.append(lessons.LessonResource(source, manifest, content))
    return lessons.group_resources(resources), broken


def _channel_games():
    entries = []
    for path, content, _file_id in _channel_files("zim"):
        source = ZimSource(path)
        if source.has_manifest():
            entries.append(_load("c-" + content["content_id"], source, "channel", content))
    return entries


_cache = {"at": 0, "games": None}
_cache_lock = threading.Lock()


def discover(refresh=False):
    """All games found, in display order. Cached for a few seconds."""
    with _cache_lock:
        if not refresh and _cache["games"] is not None and time.time() - _cache["at"] < CACHE_SECONDS:
            return _cache["games"]
        games, seen = [], {}
        lesson_games, broken = _lesson_games()
        for entry in _channel_games() + _local_games() + lesson_games + broken:
            if entry.key in seen:
                seen[entry.key].problems.append(
                    "Another copy of this game was also found at %s and ignored." % entry.source.location
                )
                continue
            seen[entry.key] = entry
            games.append(entry)
        games.sort(key=lambda g: (not g.playable, g.title.lower()))
        _cache.update(at=time.time(), games=games)
        return games


def get(key, refresh=False):
    if not isinstance(key, str) or not KEY_RE.match(key):
        return None
    for entry in discover(refresh=refresh):
        if entry.key == key:
            return entry
    if not refresh:
        return get(key, refresh=True)
    return None
