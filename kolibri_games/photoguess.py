"""
The rules of a photo-guessing game (BeaconHunt), run on the server so the
answers stay hidden. No Django imports.

An attempt has a few rounds. Each round shows one street photo; the learner
guesses which country it was taken in. The server knows where every photo was
taken and only reveals it after the guess.

Points for a round:

* the right country: 5000
* the wrong country: up to 4000, less the further the guessed country is from
  where the photo was taken (4000 x e^(-distance / 800 km)): a neighbouring
  country still earns a good part, the other side of the world almost nothing.

The score is the total. Distances to a country are measured to a point inside
its largest piece of land (from the game's countries file).
"""
import math
import random

from . import photos

CORRECT_POINTS = 5000
WRONG_MAX_POINTS = 4000
DISTANCE_SCALE_KM = 800.0
MAX_ROUNDS = 20
PHOTO_PREFIX = "__photos__/"


class GuessError(Exception):
    def __init__(self, message, code="bad_move"):
        super(GuessError, self).__init__(message)
        self.code = code


def points_for(correct, km):
    if correct:
        return CORRECT_POINTS
    return int(round(WRONG_MAX_POINTS * math.exp(-km / DISTANCE_SCALE_KM)))


def pick_places(packs, count, rng=random):
    """``count`` place references ("pack/place") spread over as many countries as possible."""
    by_country = {}
    for pack in packs:
        for place in pack.places.values():
            by_country.setdefault(place["country"], []).append("%s/%s" % (pack.id, place["id"]))
    if not by_country:
        raise GuessError("There are no photos for this region on this device.", "no_photos")
    countries = list(by_country)
    rng.shuffle(countries)
    chosen = []
    # Take one place from each country in turn, so a round of 5 visits 5 countries when it can.
    while len(chosen) < count and any(by_country[c] for c in countries):
        for c in countries:
            if by_country[c] and len(chosen) < count:
                chosen.append(by_country[c].pop(rng.randrange(len(by_country[c]))))
    rng.shuffle(chosen)
    return chosen


class Hunt(object):
    """One game's rules: the photo packs in play and the countries the map knows."""

    def __init__(self, packs, countries):
        self.packs = {p.id: p for p in packs}
        self.countries = countries  # code -> {"name", "lat", "lon", ...}

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
            "rounds": n,
            "round": min(current + 1, n),
            "photo": self.photo_info(state, attempt_id, current) if current < n else None,
            "results": state["results"],
            "total": sum(r["points"] for r in state["results"]),
            "done": current >= n,
        }

    def start(self, refs):
        return {"places": list(refs), "results": []}

    def move(self, state, kind, data, attempt_id):
        """(state, reply, what to keep in the move list)."""
        data = data if isinstance(data, dict) else {}
        n = len(state["places"])
        current = len(state["results"])
        if kind != "guess":
            raise GuessError("BeaconHunt only understands 'guess'.")
        if current >= n:
            raise GuessError("All the rounds are done.", "finished")
        code = data.get("country")
        if code not in self.countries:
            raise GuessError("Choose a country on the map.")
        _pack, place = self.place(state["places"][current])
        answer = place["country"]
        correct = code == answer
        guessed = self.countries[code]
        km = 0.0 if correct else photos.distance_km(place["lat"], place["lon"], guessed["lat"], guessed["lon"])
        result = {
            "round": current + 1,
            "guess": code,
            "guess_name": guessed["name"],
            "answer": answer,
            "answer_name": self.countries.get(answer, {}).get("name", answer),
            "correct": correct,
            "distance_km": int(round(km)),
            "points": points_for(correct, km),
            "lat": round(place["lat"], 4),
            "lon": round(place["lon"], 4),
            "credit": place["credit"],
        }
        state["results"] = state["results"] + [result]
        reply = dict(self.public(state, attempt_id), result=result)
        log = {"guess": code, "answer": answer, "points": result["points"]}
        return state, reply, log

    def finish(self, state):
        if len(state["results"]) < len(state["places"]):
            raise GuessError("Finish all the rounds first.", "not_finished")
        total = sum(r["points"] for r in state["results"])
        return total, {
            "rounds": [
                {k: r[k] for k in ("round", "guess_name", "answer_name", "correct", "distance_km", "points")}
                for r in state["results"]
            ],
            "correct": sum(1 for r in state["results"] if r["correct"]),
        }
