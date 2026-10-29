"""
Where a game's files come from:

* a zip file: how every game is shared (a Kolibri HTML5 app, or a Free-play
  Game installed into this plugin)
* a plain folder: handy while making a game (the preview server and
  KOLIBRI_GAMES_PATH can point at folders)

No Django imports.
"""
import mimetypes
import os
import threading
import zipfile

from .manifest import MANIFEST_PATH, ManifestError, loads, safe_relpath

EXTRA_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".json": "application/json",
    ".wasm": "application/wasm",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ogg": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".txt": "text/plain",
    ".css": "text/css",
    ".html": "text/html",
}

#: Files bigger than this inside a game are not served (protects the server's memory).
MAX_FILE_BYTES = 32 * 1024 * 1024
#: The manifest must be small.
MAX_MANIFEST_BYTES = 256 * 1024


def guess_type(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in EXTRA_TYPES:
        return EXTRA_TYPES[ext]
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


class SourceError(Exception):
    pass


class GameSource(object):
    kind = None

    def __init__(self, location):
        self.location = location

    def read(self, path):
        """(bytes, mimetype) for a file in the game, or None if missing."""
        raise NotImplementedError

    def exists(self, path):
        return self.read(path) is not None

    def manifest(self):
        """The validated Manifest. Raises ManifestError or SourceError."""
        found = self.read(MANIFEST_PATH)
        if found is None:
            raise SourceError("No %s found." % MANIFEST_PATH)
        if len(found[0]) > MAX_MANIFEST_BYTES:
            raise SourceError("%s is too large." % MANIFEST_PATH)
        try:
            text = found[0].decode("utf-8-sig")
        except UnicodeDecodeError:
            raise SourceError("%s must be saved as UTF-8 text." % MANIFEST_PATH)
        return loads(text)


class FolderSource(GameSource):
    kind = "folder"

    def __init__(self, location):
        super(FolderSource, self).__init__(os.path.abspath(location))
        self._real_root = os.path.realpath(self.location)

    def read(self, path):
        rel = safe_relpath(path)
        if rel is None:
            return None
        full = os.path.realpath(os.path.join(self.location, rel))
        # Refuse anything outside the folder, including through symbolic links.
        if not (full == self._real_root or full.startswith(self._real_root + os.sep)):
            return None
        if not os.path.isfile(full) or os.path.getsize(full) > MAX_FILE_BYTES:
            return None
        with open(full, "rb") as f:
            return f.read(), guess_type(full)


# Open zip files are kept so each request doesn't re-read the zip's table of
# contents. Keyed by (path, modification time, size) so a replaced file is
# opened again. A small limit keeps memory use low.
_open_zips = {}
_open_lock = threading.Lock()
MAX_OPEN_ZIPS = 16


def _zip(path):
    key = (path, os.path.getmtime(path), os.path.getsize(path))
    with _open_lock:
        z = _open_zips.get(key)
        if z is None:
            z = zipfile.ZipFile(path)
            for old in [k for k in _open_zips if k[0] == path]:
                _open_zips.pop(old).close()
            if len(_open_zips) >= MAX_OPEN_ZIPS:
                _open_zips.pop(next(iter(_open_zips))).close()
            _open_zips[key] = z
        return z


def forget_zip(path):
    """Close a cached zip (before it's moved or deleted)."""
    with _open_lock:
        for old in [k for k in _open_zips if k[0] == path]:
            _open_zips.pop(old).close()


class ZipSource(GameSource):
    kind = "zip"

    def __init__(self, location):
        super(ZipSource, self).__init__(os.path.abspath(location))

    def read(self, path):
        rel = safe_relpath(path)
        if rel is None:
            return None
        try:
            z = _zip(self.location)
            with _open_lock:  # one reader at a time: a ZipFile shares one open file
                try:
                    info = z.getinfo(rel)
                except KeyError:
                    return None
                if info.is_dir() or info.file_size > MAX_FILE_BYTES:
                    return None
                return z.read(info), guess_type(rel)
        except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError, ValueError):
            return None

    def has_manifest(self):
        try:
            z = _zip(self.location)
            with _open_lock:
                return MANIFEST_PATH in z.NameToInfo
        except (OSError, zipfile.BadZipFile, ValueError):
            return False


def open_source(location):
    if os.path.isdir(location):
        return FolderSource(location)
    if location.lower().endswith(".zip"):
        return ZipSource(location)
    raise SourceError("%s is not a folder or a .zip file." % location)


__all__ = ["FolderSource", "ZipSource", "GameSource", "SourceError", "ManifestError", "open_source", "guess_type", "forget_zip"]
