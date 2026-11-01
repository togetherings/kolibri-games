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


def pick_places(found, count, rng=random):
    """``count`` place references ("pack/place") spread over as many countries as possible.

    ``found`` is (pack, place) pairs, as from places_on_map().
    """
    by_country = {}
    for pack, place in found:
        by_country.setdefault(place["country"], []).append("%s/%s" % (pack.id, place["id"]))
    if not by_country:
        raise GuessError("There are no photos for this map on this device.", "no_photos")
    countries = sorted(by_country)
    rng.shuffle(countries)
    chosen = []
    # Take one place from each country in turn, so a game of 5 visits 5 countries when it can.
    while len(chosen) < count and any(by_country[c] for c in countries):
        for c in countries:
            if by_country[c] and len(chosen) < count:
                chosen.append(by_country[c].pop(rng.randrange(len(by_country[c]))))
    rng.shuffle(chosen)
    return chosen


class Hunt(object):
    """One game's rules: the photo packs, the countries the map knows, the map and the mode."""

    def __init__(self, packs, countries, game_map=None, mode="country"):
        self.packs = {p.id: p for p in packs}
        self.countries = countries  # code -> {"name", "lat", "lon", "regions", "continents"}
        self.map = game_map or map_info(None, WORLD)
        self.mode = mode if mode in MODES else "country"

    def places(self):
        return places_on_map(self.packs.values(), self.countries, self.map["id"])

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
