"""
Make a small photo pack for tests: a few places in West Africa with tiny
coloured pictures (PNG) instead of real photos. The real packs come from
BeaconHunt's pack tool.

    python -m tests.make_test_pack OUTPUT_FOLDER [--zip]
"""
import json
import os
import struct
import sys
import zipfile
import zlib

# (id, country, lat, lon, colour)
PLACES = [
    ("0001", "SLE", 8.4844, -13.2344, (200, 60, 40)),    # Freetown
    ("0002", "SLE", 7.8767, -11.1875, (210, 90, 50)),    # Kenema
    ("0003", "LBR", 6.3156, -10.8074, (40, 120, 200)),   # Monrovia
    ("0004", "GIN", 9.5092, -13.7122, (60, 160, 80)),    # Conakry
    ("0005", "GHA", 5.6037, -0.1870, (230, 190, 40)),    # Accra
    ("0006", "CIV", 5.3600, -4.0083, (150, 70, 160)),    # Abidjan
]


# The countries that count as neighbours for photos in each country (the pack tool works these out per photo).
NEAR = {"SLE": ["GIN", "LBR"], "LBR": ["SLE", "GIN", "CIV"], "GIN": ["SLE", "LBR", "CIV"], "GHA": ["CIV"], "CIV": ["GHA", "LBR", "GIN"]}


def png(rgb, w=8, h=4):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def files(pack_id="test-west-africa", title="Test West Africa"):
    places, out = [], {}
    for pid, country, lat, lon, rgb in PLACES:
        out["photos/%s.png" % pid] = png(rgb)
        places.append({
            "id": pid, "photo": "photos/%s.png" % pid, "lat": lat, "lon": lon, "country": country,
            "pano": pid == "0001",
            "credit": {"author": "tester%s" % pid, "source": "Mapillary", "license": "CC BY-SA 4.0",
                       "url": "https://www.mapillary.com/app/?pKey=%s" % pid, "captured": "2024-01-0%s" % pid[-1]},
            "region": "Western Africa", "continent": "africa", "near": NEAR.get(country, []),
        })
    out["pack.json"] = json.dumps({"format": 1, "id": pack_id, "title": title, "version": "1",
                                   "countries": sorted({p[1] for p in PLACES}), "license": "CC BY-SA 4.0"}).encode()
    out["places.json"] = json.dumps(places).encode()
    out["LICENSE.txt"] = b"Creative Commons Attribution-ShareAlike 4.0 International (test copy)\n"
    return out


def make(folder, as_zip=False, **kw):
    os.makedirs(folder, exist_ok=True)
    data = files(**kw)
    pack_id = json.loads(data["pack.json"])["id"]
    if as_zip:
        path = os.path.join(folder, pack_id + ".zip")
        with zipfile.ZipFile(path, "w") as z:
            for name, content in data.items():
                z.writestr(name, content)
        return path
    root = os.path.join(folder, pack_id)
    for name, content in data.items():
        os.makedirs(os.path.dirname(os.path.join(root, name)), exist_ok=True)
        with open(os.path.join(root, name), "wb") as f:
            f.write(content)
    return root


if __name__ == "__main__":
    print(make(sys.argv[1], "--zip" in sys.argv))
