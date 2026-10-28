"""
Package a game folder as a ZIM file, ready to upload to Kolibri Studio or to
copy into a device's local games folder.

    kolibri-games-pack path/to/my-game              # writes dist/<id>_<version>.zim
    kolibri-games-pack path/to/my-game -o game.zim
    kolibri-games-pack --check game.zim             # is this ZIM a valid game?

Needs the ``libzim`` Python package (installed with this plugin).
"""
import argparse
import os
import struct
import sys
import zlib
from datetime import date

from . import __version__
from .manifest import MANIFEST_PATH, ManifestError
from .registry import check
from .sources import FolderSource, SourceError, ZimSource, guess_type
from .views_common import SDK_PATH

ISO639_3 = {
    "ar": "ara", "bn": "ben", "de": "deu", "en": "eng", "es": "spa", "fa": "fas", "fr": "fra", "ha": "hau",
    "hi": "hin", "id": "ind", "it": "ita", "ja": "jpn", "ko": "kor", "my": "mya", "ne": "nep", "pt": "por",
    "ru": "rus", "rw": "kin", "so": "som", "sw": "swa", "ta": "tam", "tr": "tur", "uk": "ukr", "ur": "urd",
    "vi": "vie", "yo": "yor", "zh": "zho", "zu": "zul", "am": "amh", "ny": "nya", "sn": "sna", "xh": "xho",
}
NO_COMPRESS = ("image/png", "image/jpeg", "image/gif", "image/webp", "audio/", "video/", "font/woff2", "application/zip")
ASSETS = os.path.join(os.path.dirname(__file__), "assets")


class PackError(Exception):
    pass


def _png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def default_illustration(color, size=48):
    """A plain rounded square in the game's colour, as PNG bytes (no image library needed)."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    radius = size * 0.22
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            cx = min(max(x + 0.5, radius), size - radius)
            cy = min(max(y + 0.5, radius), size - radius)
            inside = (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= radius ** 2
            row += bytes([r, g, b, 255 if inside else 0])
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", header) + _png_chunk(b"IDAT", raw) + _png_chunk(b"IEND", b"")


def png_size(data):
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def _files(folder):
    for base, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__pycache__")
        rel_base = os.path.relpath(base, folder).replace(os.sep, "/")
        if rel_base == "__kolibri_games__" or rel_base.startswith("__kolibri_games__/"):
            continue
        for name in sorted(names):
            if name.startswith(".") or name.endswith((".zim", ".pyc")):
                continue
            rel = name if rel_base == "." else rel_base + "/" + name
            yield rel, os.path.join(base, name)


def _clip(text, limit):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def pack(folder, output=None, quiet=False):
    """Write a game ZIM from ``folder``. Returns the output path."""
    try:
        from libzim.writer import Creator, FileProvider, Hint, Item, StringProvider
    except ImportError:
        raise PackError("The libzim Python package is needed: pip install libzim")

    source = FolderSource(folder)
    try:
        manifest = source.manifest()
    except (ManifestError, SourceError) as e:
        problems = e.problems if isinstance(e, ManifestError) else [str(e)]
        raise PackError("%s isn't a valid game:\n  - %s" % (folder, "\n  - ".join(problems)))
    problems = [p for p in check(manifest, source) if "rule checker" not in p and "data source" not in p]
    if problems:
        raise PackError("%s can't be packed:\n  - %s" % (folder, "\n  - ".join(problems)))

    if output is None:
        os.makedirs("dist", exist_ok=True)
        output = os.path.join("dist", "%s_%s.zim" % (manifest.id, manifest.version))
    if os.path.exists(output):
        os.remove(output)

    class GameItem(Item):
        def __init__(self, path, mimetype, filepath=None, content=None, front=False):
            super(GameItem, self).__init__()
            self._path, self._mimetype, self._filepath, self._content, self._front = path, mimetype, filepath, content, front

        def get_path(self):
            return self._path

        def get_title(self):
            return manifest.title if self._front else ""

        def get_mimetype(self):
            return self._mimetype

        def get_contentprovider(self):
            if self._filepath is not None:
                return FileProvider(self._filepath)
            return StringProvider(self._content)

        def get_hints(self):
            compress = not self._mimetype.startswith(NO_COMPRESS)
            return {Hint.FRONT_ARTICLE: self._front, Hint.COMPRESS: compress}

    lang = manifest.language.split("-")[0].lower()
    lang3 = lang if len(lang) == 3 else ISO639_3.get(lang, "eng")
    illustration = None
    icon_png = os.path.splitext(manifest.icon or "")[0] + ".png" if manifest.icon else None
    for candidate in [manifest.icon, icon_png, "icon-48.png"]:
        found = source.read(candidate) if candidate else None
        if found and png_size(found[0]) == (48, 48):
            illustration = found[0]
            break
    if illustration is None:
        illustration = default_illustration(manifest.color)

    count = 0
    creator = Creator(output).config_indexing(False, lang3)
    with creator as c:
        c.set_mainpath(manifest.entry)
        c.add_illustration(48, illustration)
        slug = manifest.id.split(".")[-1]
        metadata = {
            "Name": "kolibri-game_%s_%s" % (lang, slug),
            "Title": _clip(manifest.title, 30),
            "Description": _clip(manifest.description or manifest.title, 80),
            "Language": lang3,
            "Creator": ", ".join(manifest.authors) or "Unknown",
            "Publisher": "Kolibri Games",
            "Date": date.today().isoformat(),
            "Tags": "_category:other;kolibri-game;_ftindex:no;_videos:no;_details:yes",
            "Source": "kolibri-games-pack %s" % __version__,
        }
        if manifest.description and len(manifest.description) > 80:
            metadata["LongDescription"] = _clip(manifest.description, 4000)
        if manifest.license:
            metadata["License"] = manifest.license
        for name, value in metadata.items():
            c.add_metadata(name, value)
        for rel, full in _files(folder):
            c.add_item(GameItem(rel, guess_type(rel), filepath=full, front=(rel == manifest.entry)))
            count += 1
        # A copy of the SDK so the ZIM also opens in preview mode outside Kolibri
        # (Kolibri Games always serves its own current SDK at this path).
        with open(os.path.join(ASSETS, "sdk.js"), "rb") as f:
            c.add_item(GameItem(SDK_PATH, "text/javascript", content=f.read()))
    if not quiet:
        print("Packed %s %s (%d files) into %s" % (manifest.title, manifest.version, count, output))
    verify(output)
    return output


def verify(path):
    """Open a ZIM the way the plugin does and return its manifest, or raise PackError."""
    source = ZimSource(path)
    if not source.has_manifest():
        raise PackError("%s doesn't contain %s, so it isn't a game." % (path, MANIFEST_PATH))
    try:
        manifest = source.manifest()
    except (ManifestError, SourceError) as e:
        raise PackError("%s has an invalid manifest: %s" % (path, e))
    if not source.exists(manifest.entry):
        raise PackError("%s is missing its start page %s." % (path, manifest.entry))
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description="Package a game folder as a ZIM for Kolibri Games.")
    parser.add_argument("folders", nargs="*", help="Game folders (each with a kolibri-game.json).")
    parser.add_argument("-o", "--output", help="Output .zim path (only with a single folder).")
    parser.add_argument("--out-dir", help="Folder to write .zim files into (default: dist).")
    parser.add_argument("--check", metavar="ZIM", help="Check that a .zim file is a valid game and exit.")
    args = parser.parse_args(argv)
    try:
        if args.check:
            m = verify(args.check)
            print("%s is a valid game: %s %s (%s)" % (args.check, m.title, m.version, m.id))
            return 0
        if not args.folders:
            parser.error("give at least one game folder")
        if args.output and len(args.folders) > 1:
            parser.error("--output only works with one folder; use --out-dir")
        for folder in args.folders:
            out = args.output
            if out is None and args.out_dir:
                os.makedirs(args.out_dir, exist_ok=True)
                m = FolderSource(folder).manifest()
                out = os.path.join(args.out_dir, "%s_%s.zim" % (m.id, m.version))
            pack(folder, out)
    except (PackError, ManifestError, SourceError) as e:
        print("Error: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
