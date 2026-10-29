"""
The game manifest (``kolibri-game.json``): parsing, validation, and the
settings that coaches fill in. No Django or Kolibri imports.

Every game is a zip file with a ``kolibri-game.json`` at its root. The
``type`` field says which kind of game it is:

* ``"free-play"`` (the default): installed into this plugin and played on the
  games page. See docs/GAME_FORMAT.md.
* ``"classroom"``: an HTML5 app in a Kolibri channel, played in Learn. The
  games page shows scoreboards from its saved data. See docs/CLASSROOM_GAMES.md.
"""
import json
import posixpath
import re

from . import MANIFEST_FORMAT
from .versions import VersionError, parse_spec, parse_version

MANIFEST_PATH = "kolibri-game.json"

ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,99}$")
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

GAME_TYPES = ("free-play", "classroom")

#: Server-side services built into this plugin that a Free-play Game can use.
#: "wikipedia-race": the server reads Wikipedia articles for the game, checks
#: every link the learner follows and works out the score (see wikirace.py).
SERVICES = ("wikipedia-race",)

#: Setting types. "article" (a Wikipedia article title) and "article_list" (a
#: list of allowed articles) are only for games that use "wikipedia-race".
SETTING_TYPES = ("integer", "number", "boolean", "choice", "text", "article", "article_list")
WIKI_SETTING_TYPES = ("article", "article_list")

# For Classroom Games' scoreboards.
SAVED_IN = ("scorm",)
COMBINE = ("best", "sum", "max")
MAX_FIELDS = 8

#: Settings every Free-play Game has, managed by the platform rather than the game.
PLATFORM_SETTINGS = [
    {
        "key": "counts",
        "type": "choice",
        "label": "Which attempt counts on the scoreboard",
        "choices": [
            {"value": "first", "label": "First attempt only (later attempts are practice)"},
            {"value": "best", "label": "Best attempt"},
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
        self.type = data.get("type", "free-play")
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
        # Free-play Games
        self.scoring = data.get("scoring")
        self.settings = data.get("settings", [])
        self.data = data.get("data", [])
        self.service = data.get("service")
        self.wikipedia = data.get("wikipedia") or {}
        # Classroom Games
        self.scoreboards = data.get("scoreboards")

    @property
    def is_classroom(self):
        return self.type == "classroom"

    @property
    def has_scores(self):
        return self.scoring is not None

    @property
    def free_play_scoreboard(self):
        """False for games whose free-play rounds can't be compared (like random Wiki BLAZE pairs)."""
        return self.has_scores and self.scoring.get("free_play_scoreboard", True)

    def platform_settings_schema(self):
        schema = [dict(s) for s in PLATFORM_SETTINGS]
        if self.is_classroom:
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
            "scoring": self.scoring,
            "color": self.color,
            "authors": self.authors,
            "license": self.license,
            "service": self.service,
            "scoreboards": self.scoreboards,
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
    if ftype in WIKI_SETTING_TYPES and service != "wikipedia-race":
        problems.append("%s: '%s' settings are only for games that use the wikipedia-race service." % (where, ftype))
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


def _check_scoring(scoring, problems):
    if not isinstance(scoring, dict):
        problems.append("scoring must be an object.")
        return None
    if scoring.get("order") not in ("asc", "desc"):
        problems.append("scoring.order must be 'asc' (lower is better) or 'desc' (higher is better).")
    if scoring.get("counts", "first") not in ("first", "best"):
        problems.append("scoring.counts must be 'first' or 'best'.")
    if scoring.get("tiebreak", "seconds") not in ("seconds", "none"):
        problems.append("scoring.tiebreak must be 'seconds' or 'none'.")
    for bound in ("min", "max"):
        if bound in scoring and not isinstance(scoring[bound], (int, float)):
            problems.append("scoring.%s must be a number." % bound)
    if not isinstance(scoring.get("decimals", 0), int):
        problems.append("scoring.decimals must be a whole number.")
    if not isinstance(scoring.get("free_play_scoreboard", True), bool):
        problems.append("scoring.free_play_scoreboard must be true or false.")
    return {
        "label": scoring.get("label", "Score"),
        "unit": scoring.get("unit", ""),
        "order": scoring.get("order"),
        "counts": scoring.get("counts", "first"),
        "tiebreak": scoring.get("tiebreak", "seconds"),
        "decimals": scoring.get("decimals", 0),
        "min": scoring.get("min"),
        "max": scoring.get("max"),
        "free_play_scoreboard": scoring.get("free_play_scoreboard", True),
    }


def _check_scoreboards(sb, problems):
    """Checks the "scoreboards" section of a Classroom Game and returns it with defaults filled in."""
    if not isinstance(sb, dict):
        problems.append("Classroom Games need a scoreboards section that says how to read their saved data.")
        return None
    where = "scoreboards"
    saved_in = sb.get("saved_in", "scorm")
    if saved_in not in SAVED_IN:
        problems.append("%s.saved_in must be one of %s." % (where, ", ".join(SAVED_IN)))
    fields = sb.get("fields")
    keys = {}
    if not isinstance(fields, list) or not 0 < len(fields) <= MAX_FIELDS:
        problems.append("%s.fields must list 1 to %d values to show." % (where, MAX_FIELDS))
        fields = []
    clean_fields = []
    for i, f in enumerate(fields):
        fw = "%s.fields[%d]" % (where, i)
        if not isinstance(f, dict):
            problems.append("%s must be an object." % fw)
            continue
        key = f.get("key")
        if not isinstance(key, str) or not KEY_RE.match(key):
            problems.append("%s.key must be lower_case letters, digits or _." % fw)
        elif key in keys:
            problems.append("%s.key '%s' is used twice." % (fw, key))
        src = f.get("from", key)
        if isinstance(src, bool) or not (
            (isinstance(src, int) and 0 <= src < 100) or (isinstance(src, str) and 0 < len(src) <= 40)
        ):
            problems.append("%s.from must be a name (like \"acc\") or a position in a list (like 0)." % fw)
        if not isinstance(f.get("label"), str) or not f["label"].strip():
            problems.append("%s.label is required." % fw)
        if f.get("order") not in (None, "asc", "desc"):
            problems.append("%s.order must be 'asc' (lower is better) or 'desc' (higher is better)." % fw)
        if f.get("combine", "best") not in COMBINE:
            problems.append("%s.combine must be one of %s." % (fw, ", ".join(COMBINE)))
        if not isinstance(f.get("decimals", 0), int) or isinstance(f.get("decimals", 0), bool):
            problems.append("%s.decimals must be a whole number." % fw)
        if "unit" in f and not isinstance(f["unit"], str):
            problems.append("%s.unit must be text." % fw)
        clean = {
            "key": key,
            "from": src,
            "label": f.get("label"),
            "unit": f.get("unit", ""),
            "order": f.get("order"),
            "combine": f.get("combine", "best"),
            "decimals": f.get("decimals", 0),
            "seconds": bool(f.get("seconds", False)),
        }
        keys[key] = clean
        clean_fields.append(clean)
    rank_by = sb.get("rank_by")
    if not isinstance(rank_by, list) or not rank_by:
        problems.append("%s.rank_by must list the values used to rank players, best first." % where)
        rank_by = []
    for k in rank_by:
        if k not in keys:
            problems.append("%s.rank_by: '%s' isn't one of the fields." % (where, k))
        elif not keys[k]["order"]:
            problems.append("%s.rank_by: give the field '%s' an order." % (where, k))
        elif keys[k]["combine"] != "best":
            problems.append("%s.rank_by: '%s' can't be used for ranking because it's combined with %s." % (where, k, keys[k]["combine"]))
    only_if = sb.get("only_if")
    if only_if is not None and not (isinstance(only_if, dict) and "from" in only_if and "equals" in only_if):
        problems.append("%s.only_if needs 'from' and 'equals'." % where)
    names = sb.get("board_names", {})
    if not isinstance(names, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in names.items()):
        problems.append("%s.board_names must map board ids to names." % where)
        names = {}
    rules = sb.get("board_name_rules", [])
    if not isinstance(rules, list):
        problems.append("%s.board_name_rules must be a list." % where)
        rules = []
    for i, r in enumerate(rules):
        if not (
            isinstance(r, dict)
            and isinstance(r.get("name"), str)
            and isinstance(r.get("prefix", ""), str)
            and isinstance(r.get("suffix", ""), str)
        ):
            problems.append("%s.board_name_rules[%d] needs a name, and an optional prefix and suffix." % (where, i))
    label = sb.get("board_label", "Scoreboard")
    if not isinstance(label, str) or not label.strip():
        problems.append("%s.board_label must be text." % where)
    return {
        "saved_in": saved_in,
        "fields": clean_fields,
        "rank_by": list(rank_by),
        "only_if": only_if,
        "board_label": label,
        "board_names": names,
        "board_name_rules": rules,
        "name_boards_after_resource": bool(sb.get("name_boards_after_resource", False)),
    }


def validate(data):
    """Return a Manifest, or raise ManifestError listing every problem found."""
    problems = []
    if not isinstance(data, dict):
        raise ManifestError("The manifest must be a JSON object.")

    if data.get("format") != MANIFEST_FORMAT:
        problems.append("format must be %d." % MANIFEST_FORMAT)
    gtype = data.get("type", "free-play")
    if gtype not in GAME_TYPES:
        problems.append("type must be 'free-play' or 'classroom'.")
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

    if gtype == "classroom":
        for name in ("scoring", "settings", "data", "service", "wikipedia"):
            if name in data:
                problems.append("Classroom Games can't use '%s'. Their scores come from their saved data." % name)
        clean["scoreboards"] = _check_scoreboards(data.get("scoreboards"), problems)
    else:
        if "scoreboards" in data:
            problems.append("scoreboards is only for Classroom Games (type 'classroom').")
        service = data.get("service")
        if service is not None and service not in SERVICES:
            problems.append("service must be one of %s." % ", ".join(SERVICES))
        if data.get("scoring") is not None:
            clean["scoring"] = _check_scoring(data["scoring"], problems)
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
