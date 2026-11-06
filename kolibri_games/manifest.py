"""
The game manifest (``kolibri-game.json``): parsing, validation, and the
settings that coaches fill in. No Django or Kolibri imports.

Every game is a zip file with a ``kolibri-game.json`` at its root. The
``type`` field says which kind of game it is:

* ``"saved"``: Saved Games keep each learner's progress, and nothing more.
* ``"scored"``: Scored Games also report scores, for scoreboards (see scoring.py).
* ``"server"``: Server Games need this plugin's server to play (Wiki BLAZE,
  BeaconHunt): the server runs the rules, so they can't work offline or
  anywhere else. They use one of the plugin's services.

Saved and Scored Games are made with EduGame Kit (github.com/togetherings/edugame-kit)
and added to Kolibri through Kolibri Studio, in a channel. The games page shows
Scored Games' scoreboards from the data they save (docs/CHANNEL_GAMES.md).
Server Games, which can't go through Studio, are installed on the games page
(docs/GAME_FORMAT.md). The games page can install the other kinds too, but
that isn't the way they're meant to reach learners.
"""
import json
import posixpath
import re

from . import MANIFEST_FORMAT, scoring
from .versions import VersionError, parse_spec, parse_version

MANIFEST_PATH = "kolibri-game.json"

ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,99}$")
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
LANG_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")

GAME_TYPES = ("saved", "scored", "server")

#: Server-side services built into this plugin that a Server Game uses (exactly one).
#: "wikipedia-race": the server reads Wikipedia articles for the game, checks
#: every link the learner follows and works out the score (see wikirace.py).
#: "photo-guess": the server picks street photos from photo packs, keeps where
#: they were taken hidden, and scores each guess (see photoguess.py).
SERVICES = ("wikipedia-race", "photo-guess")
MAP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,59}$")

#: Setting types. "article" (a Wikipedia article title) and "article_list" (a
#: list of allowed articles) are only for games that use "wikipedia-race".
#: "photo_map" (the whole world, or one of the game's maps) is only for "photo-guess".
SETTING_TYPES = ("integer", "number", "boolean", "choice", "text", "article", "article_list", "photo_map")
WIKI_SETTING_TYPES = ("article", "article_list")
SERVICE_SETTING_TYPES = {"article": "wikipedia-race", "article_list": "wikipedia-race", "photo_map": "photo-guess"}

#: Settings every game on the games page has, managed by the platform rather than the game.
PLATFORM_SETTINGS = [
    {
        "key": "counts",
        "type": "choice",
        "label": "Which attempt counts on the scoreboard",
        "choices": [
            {"value": "first", "label": "First attempt only (later attempts are practice)"},
            {"value": "best", "label": "Best attempt"},
            {"value": "latest", "label": "Latest attempt"},
            {"value": "total", "label": "Every attempt added up"},
        ],
        "default": None,  # filled in from the manifest's scoring.counts
    },
    {
        "key": "scoreboard",
        "type": "choice",
        "label": "What learners see on the scoreboard",
        "choices": [
            {"value": "names", "label": "Full names"},
            {"value": "initials", "label": "Initials only"},
            {"value": "hidden", "label": "Only their own result"},
        ],
        "default": "names",
    },
    {
        "key": "time_limit",
        "type": "integer",
        "label": "Time limit in minutes (0 for none)",
        "min": 0,
        "max": 240,
        "default": 0,
    },
]


class ManifestError(ValueError):
    def __init__(self, problems):
        if isinstance(problems, str):
            problems = [problems]
        self.problems = list(problems)
        super(ManifestError, self).__init__("; ".join(self.problems))


def safe_relpath(path):
    """Normalise a relative path inside a game, or return None if it escapes the game."""
    if not isinstance(path, str) or not path or "\\" in path or "\x00" in path:
        return None
    if path.startswith("/"):
        return None
    norm = posixpath.normpath(path)
    if norm in (".", "..") or norm.startswith("../"):
        return None
    return norm


class Manifest(object):
    """A validated game manifest. Attributes mirror the JSON fields."""

    def __init__(self, data):
        self.raw = data
        self.format = data["format"]
        self.type = data["type"]
        self.id = data["id"]
        self.version = data["version"]
        self.title = data["title"]
        self.description = data.get("description", "")
        self.entry = data.get("entry", "index.html")
        self.language = data.get("language", "en")
        self.requires_platform = data.get("requires_platform", "")
        self.icon = data.get("icon")
        self.color = data.get("color", "#3b6e8f")
        self.authors = data.get("authors", [])
        self.license = data.get("license", "")
        self.languages = data.get("languages") or [self.language]
        # Checked and in full form (scoring.check): fields, rank_by, counts, boards, saved_data.
        self.scoring = data.get("scoring")
        self.settings = data.get("settings", [])
        self.data = data.get("data", [])
        self.service = data.get("service")
        self.wikipedia = data.get("wikipedia") or {}
        self.photos = data.get("photos") or {}

    @property
    def is_server(self):
        return self.type == "server"

    @property
    def in_channels(self):
        """Saved and Scored Games can be put in Kolibri channels; Server Games can't."""
        return self.type in ("saved", "scored")

    @property
    def channel_spec(self):
        """How to read this game's scores from its saved data in a channel, or None (Saved Games).

        It's the scoring spec: games made with EduGame Kit save scores the kit's
        way, and other games say how they save theirs in scoring.saved_data
        (see scoring.py and docs/CHANNEL_GAMES.md).
        """
        if self.type != "scored":
            return None
        return self.scoring

    @property
    def has_scores(self):
        return self.scoring is not None

    @property
    def free_play_scoreboard(self):
        """False for games whose free-play rounds can't be compared (like random Wiki BLAZE pairs)."""
        return self.has_scores and self.scoring.get("free_play_scoreboard", True)

    def platform_settings_schema(self, in_channel=False):
        schema = [dict(s) for s in PLATFORM_SETTINGS]
        if in_channel:
            board = dict([f for f in schema if f["key"] == "scoreboard"][0])
            return [board]
        for field in schema:
            if field["key"] == "counts":
                field["default"] = (self.scoring or {}).get("counts", "first")
        if not self.has_scores:
            schema = [f for f in schema if f["key"] == "time_limit"]
        return schema

    def to_public(self):
        """Fields safe to show in the UI."""
        return {
            "id": self.id,
            "type": self.type,
            "version": self.version,
            "title": self.title,
            "description": self.description,
            "language": self.language,
            "languages": self.languages,
            "scoring": scoring.public(self.scoring),
            "color": self.color,
            "authors": self.authors,
            "license": self.license,
            "service": self.service,
        }


def _check_setting(field, i, problems, service):
    where = "settings[%d]" % i
    if not isinstance(field, dict):
        problems.append("%s must be an object." % where)
        return
    key = field.get("key")
    if not isinstance(key, str) or not KEY_RE.match(key):
        problems.append("%s.key must be lower_case letters, digits or _." % where)
    ftype = field.get("type")
    if ftype not in SETTING_TYPES:
        problems.append("%s.type must be one of %s." % (where, ", ".join(SETTING_TYPES)))
        return
    if ftype in SERVICE_SETTING_TYPES and service != SERVICE_SETTING_TYPES[ftype]:
        problems.append("%s: '%s' settings are only for games that use the %s service." % (where, ftype, SERVICE_SETTING_TYPES[ftype]))
    if not isinstance(field.get("label"), str) or not field["label"].strip():
        problems.append("%s.label is required." % where)
    if ftype == "choice":
        choices = field.get("choices")
        if not isinstance(choices, list) or not choices:
            problems.append("%s.choices must be a non-empty list." % where)
        else:
            for c in choices:
                if not isinstance(c, dict) or "value" not in c or "label" not in c:
                    problems.append("%s.choices entries need a value and a label." % where)
                    break
    if "default" not in field:
        problems.append("%s.default is required." % where)
    else:
        try:
            clean_value(field, field["default"])
        except ValueError as e:
            problems.append("%s.default: %s" % (where, e))


def validate(data):
    """Return a Manifest, or raise ManifestError listing every problem found."""
    problems = []
    if not isinstance(data, dict):
        raise ManifestError("The manifest must be a JSON object.")

    if data.get("format") != MANIFEST_FORMAT:
        problems.append("format must be %d." % MANIFEST_FORMAT)
    gtype = data.get("type")
    if gtype not in GAME_TYPES:
        problems.append("type must be 'saved', 'scored' or 'server'.")
    gid = data.get("id")
    if not isinstance(gid, str) or not ID_RE.match(gid):
        problems.append("id must be 3-100 lower-case letters, digits, '.', '_' or '-' (e.g. org.example.my-game).")
    try:
        parse_version(data.get("version", ""))
    except VersionError:
        problems.append("version must look like 1.0.0.")
    title = data.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > 100:
        problems.append("title is required (at most 100 characters).")
    if "description" in data and not isinstance(data["description"], str):
        problems.append("description must be text.")
    if safe_relpath(data.get("entry", "index.html")) is None:
        problems.append("entry must be a relative path inside the game.")
    if "icon" in data and safe_relpath(data["icon"]) is None:
        problems.append("icon must be a relative path inside the game.")
    if "color" in data and not (isinstance(data["color"], str) and COLOR_RE.match(data["color"])):
        problems.append("color must look like #3b6e8f.")
    try:
        parse_spec(data.get("requires_platform", ""))
    except VersionError:
        problems.append("requires_platform must look like '>=0.2' or '>=0.2,<1'.")

    clean = dict(data)
    clean["type"] = gtype
    clean["entry"] = safe_relpath(data.get("entry", "index.html"))
    languages = data.get("languages", [data.get("language", "en")])
    if not isinstance(languages, list) or not languages or not all(
        isinstance(code, str) and LANG_RE.match(code) for code in languages
    ):
        problems.append("languages must list language codes like 'en' or 'pt-BR'.")

    service = data.get("service")
    if gtype == "server":
        if service not in SERVICES:
            problems.append("Server Games need a service: one of %s." % ", ".join(SERVICES))
        if isinstance(data.get("scoring"), dict) and "saved_data" in data["scoring"]:
            problems.append("scoring.saved_data is only for Scored Games in channels.")
    elif service is not None:
        problems.append("Only Server Games (type 'server') use a service.")
    if "scoreboards" in data:
        problems.append("scoreboards is now part of scoring (see docs/GAME_FORMAT.md).")
    if gtype == "saved" and "scoring" in data:
        problems.append("Saved Games don't keep scores, so they can't have 'scoring'. Use type 'scored'.")
    if gtype == "scored" and not data.get("scoring"):
        problems.append("Scored Games need a scoring section: what the scores are called, and whether more is better.")
    if gtype != "server":
        for name in ("data", "wikipedia", "photos"):
            if name in data:
                problems.append("'%s' is only for Server Games." % name)
    if data.get("scoring") is not None:
        clean["scoring"] = scoring.check(data["scoring"], problems)
    settings = data.get("settings", [])
    if not isinstance(settings, list):
        problems.append("settings must be a list.")
    else:
        seen = set()
        for i, field in enumerate(settings):
            _check_setting(field, i, problems, service)
            key = field.get("key") if isinstance(field, dict) else None
            if key in seen:
                problems.append("settings key '%s' is used twice." % key)
            seen.add(key)
    sources = data.get("data", [])
    if not isinstance(sources, list):
        problems.append("data must be a list.")
    else:
        for i, src in enumerate(sources):
            if not isinstance(src, dict) or not isinstance(src.get("name"), str) or not NAME_RE.match(src["name"]):
                problems.append("data[%d].name must be a name like 'wikipedia'." % i)
    if service == "wikipedia-race":
        wiki = data.get("wikipedia", {})
        if not isinstance(wiki, dict):
            problems.append("wikipedia must be an object.")
        elif "default_list" in wiki and safe_relpath(wiki["default_list"]) is None:
            problems.append("wikipedia.default_list must be a relative path inside the game.")
        names = [d.get("name") for d in sources if isinstance(d, dict)] if isinstance(sources, list) else []
        if "wikipedia" not in names:
            problems.append("Games that use wikipedia-race must list the 'wikipedia' data source.")
        if not data.get("scoring"):
            problems.append("Games that use wikipedia-race need a scoring section.")
        types = {f.get("key"): f.get("type") for f in settings if isinstance(f, dict)} if isinstance(settings, list) else {}
        if types.get("start") != "article" or types.get("goal") != "article" or types.get("list") != "article_list":
            problems.append(
                "Games that use wikipedia-race need the settings 'start' and 'goal' (type article) "
                "and 'list' (type article_list)."
            )

    if service == "photo-guess":
        photos = data.get("photos", {})
        if not isinstance(photos, dict) or safe_relpath(photos.get("countries", "")) is None:
            problems.append("Games that use photo-guess need photos.countries: the path of their countries file.")
        maps = photos.get("maps") if isinstance(photos, dict) else None
        if not isinstance(maps, list) or not maps or not all(
            isinstance(m, dict) and isinstance(m.get("id"), str) and MAP_ID_RE.match(m["id"])
            and isinstance(m.get("title"), str) and isinstance(m.get("scale_km"), (int, float)) and m["scale_km"] > 0
            for m in maps
        ):
            problems.append("Games that use photo-guess need photos.maps: a list of {id, title, scale_km}.")
        elif "world" not in [m["id"] for m in maps]:
            problems.append("photos.maps needs a map with the id 'world'.")
        weights = photos.get("weights", {}) if isinstance(photos, dict) else {}
        if not isinstance(weights, dict) or not all(
            k in ("country", "location") and isinstance(v, (int, float)) and 0 <= v <= 4 for k, v in weights.items()
        ):
            problems.append("photos.weights must give each mode (country, location) a power from 0 to 4.")
        for key in ("max_share", "max_photo_ratio"):
            v = photos.get(key) if isinstance(photos, dict) else None
            if v is not None and (not isinstance(v, (int, float)) or v <= 0):
                problems.append("photos.%s must be a number above 0." % key)
        names = [d.get("name") for d in sources if isinstance(d, dict)] if isinstance(sources, list) else []
        if "photo-packs" not in names:
            problems.append("Games that use photo-guess must list the 'photo-packs' data source.")
        if not data.get("scoring"):
            problems.append("Games that use photo-guess need a scoring section.")
        types = {f.get("key"): f.get("type") for f in settings if isinstance(f, dict)} if isinstance(settings, list) else {}
        if types.get("map") != "photo_map" or types.get("rounds") != "integer":
            problems.append("Games that use photo-guess need the settings 'map' (type photo_map) and 'rounds' (type integer).")
        mode = [f for f in settings if isinstance(f, dict) and f.get("key") == "mode"] if isinstance(settings, list) else []
        if mode and (mode[0].get("type") != "choice" or not set(c.get("value") for c in mode[0].get("choices") or []
                                                              if isinstance(c, dict)) <= {"country", "location"}):
            problems.append("A photo-guess game's 'mode' setting must be a choice of 'country' and 'location'.")

    if problems:
        raise ManifestError(problems)
    return Manifest(clean)


def loads(text):
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ManifestError("kolibri-game.json is not valid JSON: %s" % e)
    return validate(data)


# --------------------------------------------------------------- settings


def clean_value(field, value):
    """Coerce one setting value to its declared type, or raise ValueError."""
    ftype = field["type"]
    if ftype == "boolean":
        if isinstance(value, bool):
            return value
        if value in ("true", "1", 1, "on"):
            return True
        if value in ("false", "0", 0, "", "off", None):
            return False
        raise ValueError("expected true or false")
    if ftype in ("integer", "number"):
        if isinstance(value, bool):
            raise ValueError("expected a number")
        try:
            num = int(value) if ftype == "integer" else float(value)
        except (TypeError, ValueError):
            raise ValueError("expected a number")
        if ftype == "integer" and isinstance(value, float) and value != int(value):
            raise ValueError("expected a whole number")
        if field.get("min") is not None and num < field["min"]:
            raise ValueError("must be at least %s" % field["min"])
        if field.get("max") is not None and num > field["max"]:
            raise ValueError("must be at most %s" % field["max"])
        return num
    if ftype == "choice":
        allowed = [c["value"] for c in field.get("choices", [])]
        if value not in allowed:
            raise ValueError("must be one of %s" % ", ".join(str(a) for a in allowed))
        return value
    if ftype in ("text", "article"):
        # An "article" is a Wikipedia title; whether it exists is checked by the
        # Wikipedia service when a coach saves it (see wikirace.py).
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise ValueError("expected text")
        if len(value) > int(field.get("max_length", 500 if ftype == "text" else 300)):
            raise ValueError("is too long")
        return value.strip() if ftype == "article" else value
    if ftype == "photo_map":
        # "world" or another of the game's maps; whether it has photos on this
        # device is checked when settings are saved.
        if isinstance(value, str) and MAP_ID_RE.match(value):
            return value
        raise ValueError("must be a map")
    if ftype == "article_list":
        # "default" (the game's own list), "all" (every article) or "list-<id>"
        # (a list made by a coach). Whether a coach's list exists is checked
        # when settings are saved.
        if value == "default" or value == "all" or (isinstance(value, str) and re.match(r"^list-\d{1,9}$", value)):
            return value
        raise ValueError("must be an article list")
    raise ValueError("unknown type")


def defaults(schema):
    return {f["key"]: f["default"] for f in schema}


def merge_settings(schema, stored):
    """Defaults overlaid with stored values; stored values that no longer fit the schema are dropped."""
    result = defaults(schema)
    for field in schema:
        if field["key"] in (stored or {}):
            try:
                result[field["key"]] = clean_value(field, stored[field["key"]])
            except ValueError:
                pass
    return result


def clean_settings(schema, submitted):
    """Validate submitted values. Returns (values, errors) where errors maps key -> message."""
    values, errors = {}, {}
    for field in schema:
        key = field["key"]
        if key not in (submitted or {}):
            values[key] = field["default"]
            continue
        try:
            values[key] = clean_value(field, submitted[key])
        except ValueError as e:
            errors[key] = "%s %s." % (field["label"], e)
    return values, errors
