"""
Package a game folder as a .zip, ready to install on the games page's Setup
page (Free-play Games) or to upload to Kolibri Studio as an HTML5 app
(Classroom Games). It checks the game first. No Django imports.

    kolibri-games-pack path/to/my-game                # writes dist/<id>-<version>.zip
    kolibri-games-pack path/to/my-game -o game.zip
    kolibri-games-pack games/* --out-dir dist/games   # several games at once
    kolibri-games-pack --check game.zip               # is this zip a valid game?

Any zip tool works too: what matters is that kolibri-game.json and the start
page are at the top of the zip, not inside a folder.
"""
import argparse
import os
import sys
import zipfile

from .manifest import ManifestError
from .registry import check
from .sources import FolderSource, SourceError, ZipSource

#: Files and folders left out of the zip.
SKIP = {".git", ".DS_Store", "__MACOSX", "Thumbs.db", "node_modules", ".idea", ".vscode"}
#: Already compressed: stored as they are, which is faster to pack and to read.
STORED = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp3", ".ogg", ".mp4", ".webm", ".woff2", ".zip", ".zim")


class PackError(Exception):
    pass


def verify(source):
    """(manifest, problems) for a folder or zip. Problems that only matter on a device
    (like a missing data source) are not reported here."""
    try:
        manifest = source.manifest()
    except (ManifestError, SourceError) as e:
        return None, (e.problems if isinstance(e, ManifestError) else [str(e)])
    problems = []
    if manifest.is_classroom:
        if not source.exists("index.html"):
            problems.append("Kolibri needs an index.html at the top of an HTML5 app.")
    else:
        problems = [p for p in check(manifest, source) if "data source" not in p]
    return manifest, problems


def pack(folder, out=None, out_dir="dist"):
    source = FolderSource(folder)
    manifest, problems = verify(source)
    if manifest is None or problems:
        raise PackError("%s: %s" % (folder, " ".join(problems)))
    out = out or os.path.join(out_dir, "%s-%s.zip" % (manifest.id, manifest.version))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tmp = out + ".tmp"
    with zipfile.ZipFile(tmp, "w") as z:
        for root, dirs, files in os.walk(folder):
            dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.startswith("."))
            for name in sorted(files):
                if name in SKIP or name.startswith("."):
                    continue
                full = os.path.join(root, name)
                rel = os.path.relpath(full, folder).replace(os.sep, "/")
                kind = zipfile.ZIP_STORED if name.lower().endswith(STORED) else zipfile.ZIP_DEFLATED
                z.write(full, rel, compress_type=kind)
    os.replace(tmp, out)
    return out, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description="Package Kolibri Games games as .zip files.")
    parser.add_argument("paths", nargs="+", help="Game folders (or zips with --check).")
    parser.add_argument("-o", "--output", help="Output file (only with one game).")
    parser.add_argument("--out-dir", default="dist", help="Folder for output files (default: dist).")
    parser.add_argument("--check", action="store_true", help="Only check zips or folders; write nothing.")
    args = parser.parse_args(argv)
    if args.output and len(args.paths) > 1:
        parser.error("-o only works with one game")
    failed = False
    for path in args.paths:
        if args.check:
            source = ZipSource(path) if path.lower().endswith(".zip") else FolderSource(path)
            manifest, problems = verify(source)
            if manifest and not problems:
                print("ok   %s: %s %s (%s)" % (path, manifest.title, manifest.version, manifest.type))
            else:
                failed = True
                print("FAIL %s: %s" % (path, " ".join(problems)))
            continue
        if not os.path.isdir(path):
            continue
        try:
            out, manifest = pack(path, args.output, args.out_dir)
            print("%s -> %s (%d KB)" % (manifest.title, out, (os.path.getsize(out) + 1023) // 1024))
        except PackError as e:
            failed = True
            print("FAIL %s" % e)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
