# Photo packs

Photo packs hold the street photos for games that use the `photo-guess` service, such as
[BeaconHunt](https://github.com/togetherings/beacon-hunt). Each pack covers one region of the
world (for example West Africa). A game plays photos from every pack on the device, either on
the whole world map or on one continent's map.

Packs are made with BeaconHunt's pack tool, on a computer with internet. They're too big to go
through the Setup page's install button, so copy them onto the device (for example with a USB
stick).

## Where they go

Into the photo-packs folder: `<KOLIBRI_HOME>/kolibri_games/photo-packs/` (on Internet-in-a-Box,
`/library/kolibri/kolibri_games/photo-packs/`). Administrators can choose another folder on the
Setup page, which also lists the packs it finds.

Each pack is a folder or a `.zip`:

```
photo-packs/
  west-africa/            (or west-africa.zip)
    pack.json
    places.json
    photos/0001.jpg ...
    LICENSE.txt
    CREDITS.txt
```

## pack.json

```json
{
  "format": 1,
  "id": "west-africa",
  "title": "West Africa",
  "version": "2026.11.01",
  "countries": ["BEN", "BFA", "CIV", "..."],
  "license": "CC BY-SA 4.0",
  "source": "Mapillary"
}
```

`id` is lower-case letters, digits, `-` or `_`, and must be different for every pack. Countries
are three-letter ISO codes, as in the game's countries file.

## places.json

```json
[
  {
    "id": "0001",
    "photo": "photos/0001.jpg",
    "lat": 8.4844,
    "lon": -13.2344,
    "country": "SLE",
    "pano": true,
    "credit": {
      "author": "someone",
      "source": "Mapillary",
      "url": "https://www.mapillary.com/app/?pKey=123456789",
      "license": "CC BY-SA 4.0",
      "captured": "2023-05-01"
    },
    "region": "Western Africa",
    "continent": "africa",
    "near": ["GIN", "LBR"]
  }
]
```

`pano` is `true` for a 360° photo (equirectangular, twice as wide as it is tall), `false` for an
ordinary photo.

The last three fields are for scoring country guesses, and the pack tool works them out for each
photo from where it was taken:

* `region`: the UN sub-region of the spot (a photo in Hawaii is in Polynesia, though the country
  is the United States).
* `continent`: the id of the game's map the photo belongs to.
* `near`: the countries that count as neighbours for this photo: ones that border its country (on
  land, or across less than about 150 km of water) and are within about 500 km of it.

## How the photos are kept secret

Places never reach the browser. The server picks the places for a game, sends only the photos,
and reveals where a photo was taken after the learner guesses. Photos are served one round at a
time (a learner can't fetch the next round's photo early), and any hidden GPS data in a JPEG is
removed as it's sent, as well as by the pack tool.

## The game's side

A game that uses photo packs declares, in its `kolibri-game.json`:

```json
"service": "photo-guess",
"data": [{"name": "photo-packs"}],
"photos": {
  "countries": "map/countries.json",
  "maps": [
    {"id": "world", "title": "The whole world", "scale_km": 1500},
    {"id": "africa", "title": "Africa", "scale_km": 600}
  ]
},
"settings": [
  {"key": "mode", "type": "choice", "label": "Guess", "default": "country",
   "choices": [{"value": "country", "label": "The country"}, {"value": "location", "label": "The place"}]},
  {"key": "map", "type": "photo_map", "label": "Map", "default": "world"},
  {"key": "rounds", "type": "integer", "label": "Rounds", "min": 1, "max": 10, "default": 5}
]
```

**Maps.** `world` plays every photo; another map plays the photos whose `continent` is its id.
The settings form offers only the maps that have photos on the device. `scale_km` sets how
strictly location guesses are scored on that map.

**The countries file** maps each country code to its name, a point inside it, and the regions
and continents it has land in:
`{"SLE": {"name": "Sierra Leone", "lat": 8.56, "lon": -11.79, "regions": ["Western Africa"],
"continents": ["africa"]}, ...}`. Only countries in this file can be guessed, and photos from
other places (for example a disputed area the game leaves out) are never picked.

The game plays like this:

```js
const start = await KG.start();
// start.public: {mode, map, rounds, round, photo: {url, pano}, results, total, done}
// show the photo: <img src="{photo.url}"> (relative to the game), or a 360° viewer if pano
const reply = await KG.move("guess", { country: "SLE" });      // country mode
const reply = await KG.move("guess", { lat: 8.5, lon: -13.2 }); // location mode
// reply.result: {answer, answer_name, lat, lon, credit, points, and
//   country mode: guess, guess_name, tier ("right", "neighbour", "region", "continent", "none"), correct
//   location mode: guess_lat, guess_lon, distance_km}
// reply.photo: the next round's photo, until reply.done
await KG.finish({});   // the server adds up the points
```

Points per round, out of 1000:

* **Country mode:** the right country 1000, a neighbour (from the photo's `near`) 500, a country
  with land in the photo's region 300, one on the photo's continent 100, anything else 0.
* **Location mode:** 1000 × e^(−distance / scale_km), with the map's `scale_km`.

The mode and map are kept with each attempt, so changing the settings doesn't change a game
that's already going.

In a challenge, every learner gets the same photos, picked when the coach saves the challenge.
