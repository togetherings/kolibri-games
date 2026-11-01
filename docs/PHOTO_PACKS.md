# Photo packs

Photo packs hold the street photos for games that use the `photo-guess` service, such as
[BeaconHunt](https://github.com/togetherings/beacon-hunt). Each pack covers one region of the
world (for example West Africa). A game can use one region, or every pack on the device at once
(the "whole world").

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
    }
  }
]
```

`pano` is `true` for a 360° photo (equirectangular, twice as wide as it is tall), `false` for an
ordinary photo.

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
"photos": {"countries": "map/countries.json"},
"settings": [
  {"key": "region", "type": "photo_region", "label": "Region", "default": "world"},
  {"key": "rounds", "type": "integer", "label": "Rounds", "min": 1, "max": 10, "default": 5}
]
```

The countries file maps each country code to its name and a point inside it:
`{"SLE": {"name": "Sierra Leone", "lat": 8.56, "lon": -11.79}, ...}`. Wrong guesses are scored by
the distance from the photo to that point.

The game plays like this:

```js
const start = await KG.start();
// start.public: {rounds, round, photo: {url, pano}, results, total, done}
// show the photo: <img src="{photo.url}"> (relative to the game), or a 360° viewer if pano
const reply = await KG.move("guess", { country: "SLE" });
// reply.result: {correct, guess_name, answer_name, distance_km, points, lat, lon, credit}
// reply.photo: the next round's photo, until reply.done
await KG.finish({});   // the server adds up the points
```

Points per round: 5000 for the right country, otherwise up to 4000, less the further the guessed
country is from the photo (4000 × e^(−distance / 800 km)).

In a challenge, every learner gets the same photos, picked when the coach saves the challenge.
