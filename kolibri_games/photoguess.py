"""
The rules of a photo-guessing game (BeaconHunt), run on the server so the
answers stay hidden. No Django imports.

An attempt has a few rounds. Each round shows one street photo. The server
knows where every photo was taken and only reveals it after the guess.

There are two modes (the game's "mode" setting):

* **country**: the learner picks a country on the map. Points:

  * the right country: 1000
  * a neighbouring country: 500. The pack tool lists, for each photo, the
    countries that count: ones that border the photo's country (on land, or
    across less than about 150 km of water) and are within about 500 km of
    the photo. So for a photo in Miami, Cuba counts; for one in Kansas it
    doesn't.
  * a country in the same region (UN sub-region) as the photo: 300
  * a country on the same continent: 100

  A country can be in several regions and continents (Russia is in Eastern
  Europe and Northern Asia; France has land in the Caribbean, South America
  and East Africa). The photo's own region is where it was taken.

* **location**: the learner puts a pin where they think the photo was taken.
  Points: 1000 x e^(-distance / scale), where the scale belongs to the map
  being played (the whole world is forgiving, a continent stricter).

The game chooses a **map**: the whole world (every photo) or one of the
game's maps (photos whose continent is that map's id). Maps come from the
game's manifest: "photos": {"maps": [{"id", "title", "scale_km"}]}.

**How often each country comes up**: by its "weight" in the countries file,
raised to a power for each mode ("photos": {"weights": {"country": 1,
"location": 2}}), with caps: "max_share" (the most rounds any one country
gets) and "max_photo_ratio" (no country comes up much more often than its
share of the photos, so countries with few photos don't repeat). See
pick_places().
"""
import math
import random

from . import photos

MAX_POINTS = 1000
#: Country mode: points for each kind of guess.
TIER_POINTS = {"right": 1000, "neighbour": 500, "region": 300, "continent": 100, "none": 0}
MODES = ("country", "location")
WORLD = "world"
DEFAULT_SCALE_KM = 1500.0
MAX_ROUNDS = 20
PHOTO_PREFIX = "__photos__/"


class GuessError(Exception):
    def __init__(self, message, code="bad_move"):
        super(GuessError, self).__init__(message)
        self.code = code


def location_points(km, scale_km):
    return int(round(MAX_POINTS * math.exp(-km / float(scale_km or DEFAULT_SCALE_KM))))


def country_tier(guess, place, countries):
    """How good a country guess is: right, neighbour, region, continent or none."""
    if guess == place["country"]:
        return "right"
    if guess in place.get("near", ()):
        return "neighbour"
    info = countries.get(guess, {})
    if place.get("region") and place["region"] in (info.get("regions") or ()):
        return "region"
    if place.get("continent") and place["continent"] in (info.get("continents") or ()):
        return "continent"
    return "none"


def map_info(maps, map_id):
    """The game's map with this id ({"id", "title", "scale_km"}); the whole world if it has none."""
    for m in maps or ():
        if m.get("id") == map_id:
            return m
    if map_id in (None, "", WORLD):
        return {"id": WORLD, "title": "The whole world", "scale_km": DEFAULT_SCALE_KM}
    return None


def places_on_map(packs, countries, map_id):
    """(pack, place) for every photo that can be played on a map (one the game's countries file knows)."""
    for pack in packs:
        for place in pack.places.values():
            if place["country"] not in countries:
                continue  # e.g. a disputed area the game leaves out
            if map_id in (None, "", WORLD) or place.get("continent") == map_id:
                yield pack, place


def capped_weights(weights, photo_counts, max_share=None, max_photo_ratio=None):
    """Each country's weight after the caps, as shares that add up to 1.

    * max_share: no country gets more than this share of the rounds (0.04: 4%).
    * max_photo_ratio: no country comes up more than this many times as often
      as its share of the photos (3: a country with 1% of the photos gets at
      most 3% of the rounds), so countries with few photos don't repeat.

    What a capped country loses goes to the others, in proportion to their
    weights (and so on, until no one is over their cap).
    """
    total_photos = float(sum(photo_counts.values())) or 1.0
    caps = {}
    for c in weights:
        cap = 1.0
        if max_share:
            cap = min(cap, max_share)
        if max_photo_ratio:
            cap = min(cap, max_photo_ratio * photo_counts.get(c, 0) / total_photos)
        caps[c] = cap
    shares, fixed = {}, set()
    while True:
        free = [c for c in weights if c not in fixed]
        left = 1.0 - sum(shares[c] for c in fixed)
        total = sum(weights[c] for c in free)
        if not free or total <= 0 or left <= 0:
            break
        over = []
        for c in free:
            shares[c] = left * weights[c] / total
            if shares[c] > caps[c]:
                over.append(c)
        if not over:
            break
        for c in over:
            shares[c] = caps[c]
            fixed.add(c)
    return shares


def pick_places(found, count, rng=random, countries=None, power=1.0, max_share=None, max_photo_ratio=None):
    """``count`` place references ("pack/place") spread over as many countries as possible.

    ``found`` is (pack, place) pairs, as from places_on_map(). Countries are
    drawn by their "weight" in the countries file raised to ``power``, then
    capped (see capped_weights). BeaconHunt's weight mixes area and
    population; country mode uses it as it is (power 1), place mode squared
    (power 2), so in place mode big, populous countries come up much more
    often. Without weights, all countries are equally likely.
    """
    by_country = {}
    for pack, place in found:
        by_country.setdefault(place["country"], []).append("%s/%s" % (pack.id, place["id"]))
    if not by_country:
        raise GuessError("There are no photos for this map on this device.", "no_photos")
    info = countries or {}

    def weight(code):
        try:
            return max(1e-9, float(info.get(code, {}).get("weight") or 1) ** float(power))
        except (TypeError, ValueError, AttributeError, OverflowError):
            return 1.0

    shares = capped_weights({c: weight(c) for c in by_country}, {c: len(v) for c, v in by_country.items()},
                            max_share, max_photo_ratio)
    # A weighted shuffle: each country's key is random ** (1 / share), highest first
    # (Efraimidis and Spirakis), so countries with bigger shares tend to come earlier.
    order = sorted(sorted(by_country), key=lambda c: rng.random() ** (1.0 / max(1e-12, shares.get(c, 1e-12))),
                   reverse=True)
    chosen = []
    # Take one place from each country in turn, so a game of 5 visits 5 countries when it can.
    while len(chosen) < count and any(by_country[c] for c in order):
        for c in order:
            if by_country[c] and len(chosen) < count:
                chosen.append(by_country[c].pop(rng.randrange(len(by_country[c]))))
    rng.shuffle(chosen)
    return chosen


class Hunt(object):
    """One game's rules: the photo packs, the countries the map knows, the map and the mode."""

    def __init__(self, packs, countries, game_map=None, mode="country", options=None):
        self.packs = {p.id: p for p in packs}
        self.countries = countries  # code -> {"name", "lat", "lon", "regions", "continents", "weight"}
        self.map = game_map or map_info(None, WORLD)
        self.mode = mode if mode in MODES else "country"
        self.options = options or {}  # the manifest's "photos": weights, max_share, max_photo_ratio

    def places(self):
        return places_on_map(self.packs.values(), self.countries, self.map["id"])

    def pick(self, count, rng=random):
        """The places for a new game, by the game's weights for this mode and its caps."""
        powers = self.options.get("weights") or {}
        return pick_places(self.places(), count, rng, self.countries, power=powers.get(self.mode, 1),
                           max_share=self.options.get("max_share"),
                           max_photo_ratio=self.options.get("max_photo_ratio"))

    def place(self, ref):
        pack_id, _, place_id = ref.partition("/")
        pack = self.packs.get(pack_id)
        place = pack.places.get(place_id) if pack else None
        if place is None:
            raise GuessError("A photo in this game isn't on this device any more.", "no_photos")
        return pack, place

    def photo_info(self, state, attempt_id, index):
        _pack, place = self.place(state["places"][index])
        return {"url": "%s%s/%d" % (PHOTO_PREFIX, attempt_id, index), "pano": place["pano"]}

    def public(self, state, attempt_id):
        """What the game sees: the current photo and the rounds played so far."""
        n = len(state["places"])
        current = len(state["results"])
        return {
            "mode": state.get("mode", self.mode),
            "map": state.get("map", self.map["id"]),
            "rounds": n,
            "round": min(current + 1, n),
            "photo": self.photo_info(state, attempt_id, current) if current < n else None,
            "results": state["results"],
            "total": sum(r["points"] for r in state["results"]),
            "done": current >= n,
        }

    def start(self, refs):
        # The mode and map are kept with the attempt, so changing the settings
        # later doesn't change a game that's already going.
        return {"places": list(refs), "results": [], "mode": self.mode, "map": self.map["id"],
                "scale_km": self.map.get("scale_km") or DEFAULT_SCALE_KM}

    def move(self, state, kind, data, attempt_id):
        """(state, reply, what to keep in the move list)."""
        data = data if isinstance(data, dict) else {}
        n = len(state["places"])
        current = len(state["results"])
        if kind != "guess":
            raise GuessError("Photo games only understand 'guess'.")
        if current >= n:
            raise GuessError("All the rounds are done.", "finished")
        _pack, place = self.place(state["places"][current])
        answer = place["country"]
        result = {
            "round": current + 1,
            "answer": answer,
            "answer_name": self.countries.get(answer, {}).get("name", answer),
            "lat": round(place["lat"], 4),
            "lon": round(place["lon"], 4),
            "credit": place["credit"],
        }
        if state.get("mode", "country") == "location":
            try:
                lat, lon = float(data.get("lat")), float(data.get("lon"))
            except (TypeError, ValueError):
                raise GuessError("Put a pin on the map.")
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise GuessError("Put a pin on the map.")
            km = photos.distance_km(place["lat"], place["lon"], lat, lon)
            result.update(guess_lat=round(lat, 4), guess_lon=round(lon, 4), distance_km=int(round(km)),
                          points=location_points(km, state.get("scale_km")))
            log = {"guess": [result["guess_lat"], result["guess_lon"]], "answer": answer, "points": result["points"]}
        else:
            code = data.get("country")
            if code not in self.countries:
                raise GuessError("Choose a country on the map.")
            tier = country_tier(code, place, self.countries)
            result.update(guess=code, guess_name=self.countries[code]["name"], tier=tier,
                          correct=tier == "right", points=TIER_POINTS[tier])
            log = {"guess": code, "answer": answer, "points": result["points"]}
        state["results"] = state["results"] + [result]
        reply = dict(self.public(state, attempt_id), result=result)
        return state, reply, log

    def finish(self, state):
        if len(state["results"]) < len(state["places"]):
            raise GuessError("Finish all the rounds first.", "not_finished")
        results = state["results"]
        total = sum(r["points"] for r in results)
        keep = ("round", "answer_name", "guess_name", "tier", "correct", "distance_km", "points")
        detail = {"mode": state.get("mode", "country"), "map": state.get("map", WORLD),
                  "rounds": [{k: r[k] for k in keep if k in r} for r in results]}
        if detail["mode"] == "location":
            detail["average_km"] = int(round(sum(r["distance_km"] for r in results) / float(len(results) or 1)))
        else:
            detail["correct"] = sum(1 for r in results if r.get("correct"))
        return total, detail
