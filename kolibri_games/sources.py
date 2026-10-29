"""
Where a game's files come from: a ZIM file (how Free-play Games are
distributed, e.g. through a Kolibri channel), a zip file (a Kolibri HTML5 app,
which is how Classroom Games are distributed) or a plain folder (handy while
making a game).
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
        return loads(found[0].decode("utf-8"))

    def stamp(self):
        """Changes whenever the game's files change (used for caching)."""
        try:
            return os.path.getmtime(self.location)
        except OSError:
            return 0


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
        if not (full == self._real_root or full.startswith(self._real_root + os.sep)):
            return None
        if not os.path.isfile(full):
            return None
        with open(full, "rb") as f:
            return f.read(), guess_type(full)

    def stamp(self):
        try:
            return os.path.getmtime(os.path.join(self.location, MANIFEST_PATH))
        except OSError:
            return 0


_zim_cache = {}
_zim_lock = threading.Lock()


def _open_archive(path):
    key = (path, os.path.getmtime(path), os.path.getsize(path))
    with _zim_lock:
        archive = _zim_cache.get(key)
        if archive is None:
            try:
                from libzim.reader import Archive
            except ImportError:
                raise SourceError("The libzim Python package is not installed, so ZIM games can't be opened.")
            try:
                archive = Archive(path)
            except Exception as e:
                raise SourceError("Can't open ZIM file: %s" % e)
            for old in [k for k in _zim_cache if k[0] == path]:
                del _zim_cache[old]
            _zim_cache[key] = archive
        return archive


class ZimSource(GameSource):
    kind = "zim"

    def __init__(self, location):
        super(ZimSource, self).__init__(os.path.abspath(location))

    def read(self, path):
        rel = safe_relpath(path)
        if rel is None:
            return None
        archive = _open_archive(self.location)
        try:
            if not archive.has_entry_by_path(rel):
                return None
            entry = archive.get_entry_by_path(rel)
            hops = 0
            while entry.is_redirect:
                hops += 1
                if hops > 5:
                    return None
                entry = entry.get_redirect_entry()
            item = entry.get_item()
            return bytes(item.content), item.mimetype or guess_type(rel)
        except Exception:
            return None

    def has_manifest(self):
        try:
            return _open_archive(self.location).has_entry_by_path(MANIFEST_PATH)
        except SourceError:
            return False


MAX_ZIP_MEMBER = 8 * 1024 * 1024


class ZipSource(GameSource):
    """A Kolibri HTML5 app (.zip). Only small files are read: the manifest and the icon."""

    kind = "zip"

    def __init__(self, location):
        super(ZipSource, self).__init__(os.path.abspath(location))

    def read(self, path):
        rel = safe_relpath(path)
        if rel is None:
            return None
        try:
            with zipfile.ZipFile(self.location) as z:
                try:
                    info = z.getinfo(rel)
                except KeyError:
                    return None
                if info.file_size > MAX_ZIP_MEMBER:
                    return None
                return z.read(info), guess_type(rel)
        except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError):
            return None

    def has_manifest(self):
        try:
            with zipfile.ZipFile(self.location) as z:
                return MANIFEST_PATH in z.namelist()
        except (OSError, zipfile.BadZipFile):
            return False


def open_source(location):
    if os.path.isdir(location):
        return FolderSource(location)
    if location.lower().endswith(".zim"):
        return ZimSource(location)
    if location.lower().endswith(".zip"):
        return ZipSource(location)
    raise SourceError("%s is not a folder, a .zim file or a .zip file." % location)


__all__ = ["FolderSource", "ZimSource", "ZipSource", "GameSource", "SourceError", "ManifestError", "open_source", "guess_type"]
