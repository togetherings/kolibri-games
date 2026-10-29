"""
Build a small Wikipedia-style ZIM file from examples/tiny-wiki, for testing
Wiki BLAZE with real ZIM reading (libzim). Used by tests/test_zim.py and the
real-Kolibri test in CI.

    python -m tests.make_test_zim OUTPUT.zim
"""
import json
import os
import re
import struct
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TINY = os.path.join(ROOT, "examples", "tiny-wiki")


def _png48():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes([194, 65, 12]) * 48 for _ in range(48))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 48, 48, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def build(output):
    from libzim.writer import Creator, Hint, Item, StringProvider

    class Entry(Item):
        def __init__(self, path, title, mimetype, content, front):
            super().__init__()
            self.path, self.title, self.mimetype, self.content, self.front = path, title, mimetype, content, front

        def get_path(self):
            return self.path

        def get_title(self):
            return self.title

        def get_mimetype(self):
            return self.mimetype

        def get_contentprovider(self):
            return StringProvider(self.content)

        def get_hints(self):
            return {Hint.FRONT_ARTICLE: self.front}

    with open(os.path.join(TINY, "_redirects.json")) as f:
        redirects = json.load(f)
    with Creator(output).config_indexing(False, "eng") as c:
        c.set_mainpath("Cat")
        c.add_illustration(48, _png48())
        for name, value in {"Name": "test_wiki_en", "Title": "Tiny wiki", "Description": "A tiny wiki for tests",
                            "Language": "eng", "Creator": "Kolibri Games", "Publisher": "Kolibri Games",
                            "Date": "2026-10-28"}.items():
            c.add_metadata(name, value)
        for name in sorted(os.listdir(TINY)):
            full = os.path.join(TINY, name)
            if name.endswith(".html"):
                html = open(full, encoding="utf-8").read()
                title = re.search(r"<title>(.*?)</title>", html).group(1)
                c.add_item(Entry(name[:-5], title, "text/html", html.encode("utf-8"), True))
        for name in os.listdir(os.path.join(TINY, "I")):
            data = open(os.path.join(TINY, "I", name), "rb").read()
            c.add_item(Entry("I/" + name, "", "image/png", data, False))
        for src, target in redirects.items():
            c.add_redirection(src, src, target, {Hint.FRONT_ARTICLE: True})
    return output


if __name__ == "__main__":
    print(build(sys.argv[1]))
