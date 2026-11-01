"""
Photo packs: street photos with their locations, for games that use the
"photo-guess" service (BeaconHunt). No Django imports.

A photo pack is a folder or a .zip in the photo-packs folder on the device
(by default ``<KOLIBRI_HOME>/kolibri_games/photo-packs``; an administrator can
choose another on the Setup page). One pack per region, for example
``west-africa`` or ``west-africa.zip``::

    pack.json      {"format": 1, "id": "west-africa", "title": "West Africa",
                    "countries": ["BEN", ...], "license": "CC BY-SA 4.0", ...}
    places.json    [{"id": "0001", "photo": "photos/0001.jpg", "lat": 8.48,
                     "lon": -13.23, "country": "SLE", "pano": true,
                     "credit": {"author": "...", "source": "Mapillary",
                                "url": "...", "license": "CC BY-SA 4.0",
                                "captured": "2021-05-01"}}, ...]
    photos/        the photos (JPEG)
    LICENSE.txt    the photos' license
    CREDITS.txt    who took each photo

Packs are made with BeaconHunt's pack tool (github.com/togetherings/beacon-hunt).
The places (with their locations) never reach the browser: the server picks
them and sends only the photos, with any GPS data inside the files removed.
"""
import json
import math
import os
import re
import threading

from .sources import FolderSource, ZipSource

PACK_FILE = "pack.json"
PLACES_FILE = "places.json"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,59}$")
#: Packs are re-read when their files change; this many are kept in memory.
MAX_CACHED = 64


class PackError(Exception):
    pass


class PhotoPack(object):
    """One region's photos. Places are read once and kept in memory (a few hundred KB)."""

    def __init__(self, source, info):
        self.source = source
        self.id = info["id"]
        self.title = info.get("title") or self.id
        self.countries = [c for c in info.get("countries", []) if isinstance(c, str)]
        self.license = info.get("license", "")
        self.version = str(info.get("version", ""))
        self._places = None
        self._lock = threading.Lock()

    @property
    def places(self):
        """{place id: place dict}. Places with missing fields are skipped."""
        with self._lock:
            if self._places is None:
                found = self.source.read(PLACES_FILE)
                if found is None:
                    raise PackError("The %s photo pack has no %s." % (self.id, PLACES_FILE))
                try:
                    data = json.loads(found[0].decode("utf-8"))
                except ValueError:
                    raise PackError("The %s photo pack's %s isn't valid JSON." % (self.id, PLACES_FILE))
                places = {}
                for p in data if isinstance(data, list) else []:
                    try:
                        place = {
                            "id": str(p["id"]),
                            "photo": str(p["photo"]),
                            "lat": float(p["lat"]),
                            "lon": float(p["lon"]),
                            "country": str(p["country"]),
                            "pano": bool(p.get("pano", False)),
                            "credit": p.get("credit") if isinstance(p.get("credit"), dict) else {},
                        }
                    except (KeyError, TypeError, ValueError):
                        continue
                    places[place["id"]] = place
                self._places = places
            return self._places

    def describe(self):
        return {"id": self.id, "title": self.title, "countries": self.countries, "places": len(self.places),
                "location": self.source.location, "license": self.license, "version": self.version}

    def photo(self, place):
        """(bytes, mimetype) of a place's photo, with GPS and other hidden data removed."""
        found = self.source.read(place["photo"])
        if found is None:
            return None
        data, mimetype = found
        if mimetype == "image/jpeg":
            data = strip_jpeg_metadata(data)
        return data, mimetype


_cache = {}
_cache_lock = threading.Lock()


def _stamp(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def find_packs(folder):
    """{pack id: PhotoPack} for the packs in a folder. Broken packs are skipped (see pack_problems)."""
    packs, _problems = _scan(folder)
    return packs


def pack_problems(folder):
    return _scan(folder)[1]


def _scan(folder):
    if not folder or not os.path.isdir(folder):
        return {}, []
    key = (folder, _stamp(folder), tuple(sorted((n, _stamp(os.path.join(folder, n))) for n in os.listdir(folder))))
    with _cache_lock:
        if key in _cache:
            return _cache[key]
    packs, problems = {}, []
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if name.startswith("."):
            continue
        if os.path.isdir(path):
            source = FolderSource(path)
        elif name.lower().endswith(".zip"):
            source = ZipSource(path)
        else:
            continue
        found = source.read(PACK_FILE)
        if found is None:
            problems.append("%s: no %s, so it isn't a photo pack." % (name, PACK_FILE))
            continue
        try:
            info = json.loads(found[0].decode("utf-8"))
            if not isinstance(info, dict) or not ID_RE.match(str(info.get("id", ""))):
                raise ValueError("pack.json needs an id like west-africa")
        except ValueError as e:
            problems.append("%s: %s" % (name, e))
            continue
        if info["id"] in packs:
            problems.append("%s: another pack already has the id %s, so this one is ignored." % (name, info["id"]))
            continue
        packs[info["id"]] = PhotoPack(source, info)
    with _cache_lock:
        if len(_cache) > MAX_CACHED:
            _cache.clear()
        _cache[key] = (packs, problems)
    return packs, problems


# ------------------------------------------------------------------ helpers


def strip_jpeg_metadata(data):
    """A JPEG without its APP1-APP15 and comment segments (EXIF with GPS, XMP, ...).

    Only the hidden data before the image itself is removed; the picture is
    not re-encoded, so this is fast and lossless. Anything that isn't a
    well-formed JPEG is returned unchanged.
    """
    if data[:2] != b"\xff\xd8":
        return data
    out = [data[:2]]
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            return data  # not what we expected: leave it alone
        marker = data[i + 1]
        if marker == 0xDA:  # start of the image data: keep the rest as it is
            out.append(data[i:])
            return b"".join(out)
        length = (data[i + 2] << 8) | data[i + 3]
        segment = data[i:i + 2 + length]
        if not (0xE1 <= marker <= 0xEF or marker == 0xFE):
            out.append(segment)  # keep JFIF (APP0), tables, frame headers
        i += 2 + length
    return data


def distance_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in kilometres."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))
