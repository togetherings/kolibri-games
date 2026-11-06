"""
What a game's scores look like, for every Scored and Server Game, on the games
page and in channels. No Django imports.

A game's ``scoring`` section can be short, for games with one score::

    "scoring": {"label": "Guesses", "unit": "guesses", "order": "asc",
                "tiebreak": "seconds", "counts": "first", "min": 1, "max": 1000}

or full, for anything else: several scores, each ranked its own way, levels
with their own scoreboards, and a total scoreboard::

    "scoring": {
      "fields": [
        {"key": "acc",  "label": "Accuracy", "unit": "%",   "order": "desc", "total": "average"},
        {"key": "wpm",  "label": "Speed",    "unit": "wpm", "order": "desc", "total": "average"},
        {"key": "time", "label": "Time", "source": "time", "seconds": true, "total": "sum"},
        {"key": "plays", "label": "Times played", "source": "plays"}
      ],
      "rank_by": ["acc", "wpm"],          the first ranks; the next ones break ties
      "counts": "best",                   first, best, latest or total (see COUNTS)
      "boards": {                         levels or lessons, each with its own scoreboard
        "label": "Lesson",
        "names": {"en-01": "Lesson 1"},
        "total": {"label": "All lessons"}  a scoreboard for the whole game, too
      }
    }

The short form is turned into the full form (fields "score" and, with
tiebreak "seconds", "time"), so the rest of the plugin only sees full specs.

Each field:

* ``key``: its name, in the game's results and saved data.
* ``label``, ``unit``, ``decimals``, ``seconds`` (show as 1:05): how it looks.
* ``order``: "asc" (lower is better) or "desc" (higher is better). Fields in
  ``rank_by`` need one; each field has its own.
* ``min``, ``max``: values outside these are refused (games page).
* ``source``: "game" (the game reports it, the default), "time" (the time a
  round took: measured by the server on the games page, by the game in
  channels) or "plays" (how many rounds the learner has finished).
* ``total``: how values add up, for counts "total" (all of a learner's rounds)
  and for the total scoreboard (all of a learner's boards): "sum",
  "average", "min", "max", "best" or "latest". Default: "sum".
* ``from`` (channels only): where the value is in each board's saved entry,
  a name like "acc" or a position like 0 (see ``saved_data``).

``saved_data`` (channels only) says how a game in a channel saves its scores
in SCORM ``cmi.suspend_data``:

* Left out: the EduGame Kit way. Each board is a key holding a list of the
  fields' values in ``fields`` order; keys starting with "_" are never boards.
* ``{"in": "scorm", "only_if": {"from": "done", "equals": 1}}``: a game's own
  way (Lessons In Typing, Studies In Geography). Each field says ``from``.
"""
import re

COUNTS = ("first", "best", "latest", "total")
TOTALS = ("sum", "average", "min", "max", "best", "latest")
SOURCES = ("game", "time", "plays")
SAVED_IN = ("scorm",)
MAX_FIELDS = 8
MAX_RANK_BY = 4
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
#: Board id for games without levels (EduGame Kit saves its scores under it).
MAIN_BOARD = "main"
#: The id of the total scoreboard, which can't clash with a board (board ids never start with "_").
TOTAL_BOARD = "_total"
#: The extra field on the total scoreboard: how many boards a learner has a result on.
BOARDS_FIELD = "boards"


def _number_or_none(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_field(f, i, problems, own_format):
    fw = "scoring.fields[%d]" % i
    if not isinstance(f, dict):
        problems.append("%s must be an object." % fw)
        return None
    key = f.get("key")
    if not isinstance(key, str) or not KEY_RE.match(key) or key == BOARDS_FIELD:
        problems.append("%s.key must be lower_case letters, digits or _ (and not '%s')." % (fw, BOARDS_FIELD))
    if not isinstance(f.get("label"), str) or not f["label"].strip():
        problems.append("%s.label is required." % fw)
    if f.get("order") not in (None, "asc", "desc"):
        problems.append("%s.order must be 'asc' (lower is better) or 'desc' (higher is better)." % fw)
    source = f.get("source", "game")
    if source not in SOURCES:
        problems.append("%s.source must be one of %s." % (fw, ", ".join(SOURCES)))
    total = f.get("total", "sum")
    if total not in TOTALS:
        problems.append("%s.total must be one of %s." % (fw, ", ".join(TOTALS)))
    decimals = f.get("decimals", 0)
    if not isinstance(decimals, int) or isinstance(decimals, bool) or not 0 <= decimals <= 6:
        problems.append("%s.decimals must be a whole number from 0 to 6." % fw)
    for bound in ("min", "max"):
        if f.get(bound) is not None and not _number_or_none(f[bound]):
            problems.append("%s.%s must be a number." % (fw, bound))
    if "unit" in f and not isinstance(f["unit"], str):
        problems.append("%s.unit must be text." % fw)
    src = f.get("from", key if own_format else i)
    if isinstance(src, bool) or not (
        (isinstance(src, int) and 0 <= src < 100) or (isinstance(src, str) and 0 < len(src) <= 40)
    ):
        problems.append("%s.from must be a name (like \"acc\") or a position in a list (like 0)." % fw)
    return {
        "key": key,
        "label": f.get("label"),
        "unit": f.get("unit", ""),
        "order": f.get("order"),
        "decimals": decimals,
        "seconds": bool(f.get("seconds", source == "time")),
        "min": f.get("min"),
        "max": f.get("max"),
        "source": source,
        "total": total,
        "from": src,
    }


def _short_form(s):
    """The fields of a short scoring section: "score", and "time" when time breaks ties."""
    fields = [{
        "key": "score", "label": s.get("label", "Score"), "unit": s.get("unit", ""), "order": s.get("order"),
        "decimals": s.get("decimals", 0), "min": s.get("min"), "max": s.get("max"), "total": s.get("total", "sum"),
    }]
    rank_by = ["score"]
    if s.get("tiebreak", "seconds") == "seconds":
        fields.append({"key": "time", "label": "Time", "source": "time", "seconds": True, "order": "asc"})
        rank_by.append("time")
    return fields, rank_by


def _check_boards(b, problems):
    if b is None:
        return None
    if not isinstance(b, dict):
        problems.append("scoring.boards must be an object.")
        return None
    label = b.get("label", "Level")
    if not isinstance(label, str) or not label.strip():
        problems.append("scoring.boards.label must be text.")
    names = b.get("names", {})
    if not isinstance(names, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in names.items()):
        problems.append("scoring.boards.names must map board ids to names.")
        names = {}
    rules = b.get("name_rules", [])
    if not isinstance(rules, list) or not all(
        isinstance(r, dict) and isinstance(r.get("name"), str)
        and isinstance(r.get("prefix", ""), str) and isinstance(r.get("suffix", ""), str) for r in rules
    ):
        problems.append("scoring.boards.name_rules must be a list of {name, prefix, suffix}.")
        rules = []
    total = b.get("total")
    if total is True:
        total = {}
    if total is not None and total is not False:
        if not isinstance(total, dict):
            problems.append("scoring.boards.total must be true or an object.")
            total = None
        else:
            total = {
                "label": total.get("label", "All"),
                "count_label": total.get("count_label", "%ss played" % label),
                "rank_by": total.get("rank_by"),
            }
    else:
        total = None
    return {
        "label": label,
        "names": names,
        "name_rules": rules,
        "after_resource": bool(b.get("after_resource", False)),
        "total": total,
    }


def check(scoring, problems):
    """A scoring section checked and in full form (see the module docstring), or None."""
    if not isinstance(scoring, dict):
        problems.append("scoring must be an object.")
        return None
    saved = scoring.get("saved_data")
    own_format = saved is not None
    if own_format:
        if not isinstance(saved, dict) or saved.get("in", "scorm") not in SAVED_IN:
            problems.append("scoring.saved_data must be {\"in\": \"scorm\"}, with an optional only_if.")
            saved = {}
        only_if = saved.get("only_if")
        if only_if is not None and not (isinstance(only_if, dict) and "from" in only_if and "equals" in only_if):
            problems.append("scoring.saved_data.only_if needs 'from' and 'equals'.")
        saved = {"in": "scorm", "format": "own", "only_if": only_if}
    else:
        saved = {"in": "scorm", "format": "kit", "only_if": None}

    if "fields" in scoring:
        raw_fields, rank_by = scoring.get("fields"), scoring.get("rank_by")
        if "tiebreak" in scoring or "order" in scoring:
            problems.append("scoring: with fields, give each field its own order and list rank_by (leave out order and tiebreak).")
    else:
        if scoring.get("order") not in ("asc", "desc"):
            problems.append("scoring.order must be 'asc' (lower is better) or 'desc' (higher is better).")
        if scoring.get("tiebreak", "seconds") not in ("seconds", "none"):
            problems.append("scoring.tiebreak must be 'seconds' or 'none'.")
        raw_fields, rank_by = _short_form(scoring)
    if not isinstance(raw_fields, list) or not 0 < len(raw_fields) <= MAX_FIELDS:
        problems.append("scoring.fields must list 1 to %d values." % MAX_FIELDS)
        raw_fields = []
    fields, keys = [], {}
    for i, f in enumerate(raw_fields):
        clean = _check_field(f, i, problems, own_format)
        if clean is None:
            continue
        if clean["key"] in keys:
            problems.append("scoring.fields[%d].key '%s' is used twice." % (i, clean["key"]))
        keys[clean["key"]] = clean
        fields.append(clean)
    if not isinstance(rank_by, list) or not 0 < len(rank_by) <= MAX_RANK_BY:
        problems.append("scoring.rank_by must list 1 to %d fields: the first ranks, the next ones break ties." % MAX_RANK_BY)
        rank_by = []
    for k in rank_by:
        if k not in keys:
            problems.append("scoring.rank_by: '%s' isn't one of the fields." % k)
        elif not keys[k]["order"]:
            problems.append("scoring.rank_by: give the field '%s' an order." % k)
    if rank_by and rank_by[0] in keys and keys[rank_by[0]]["source"] != "game":
        problems.append("scoring.rank_by: the first field must be one the game reports (source 'game').")
    counts = scoring.get("counts", "first")
    if counts not in COUNTS:
        problems.append("scoring.counts must be one of %s." % ", ".join(COUNTS))
    if not isinstance(scoring.get("free_play_scoreboard", True), bool):
        problems.append("scoring.free_play_scoreboard must be true or false.")
    boards = _check_boards(scoring.get("boards"), problems)
    if boards and boards["total"] and boards["total"]["rank_by"] is not None:
        tr = boards["total"]["rank_by"]
        if not isinstance(tr, list) or not tr or not all(k == BOARDS_FIELD or k in keys for k in tr):
            problems.append("scoring.boards.total.rank_by must list '%s' or fields." % BOARDS_FIELD)
    primary = keys.get(rank_by[0]) if rank_by else None
    return {
        "fields": fields,
        "rank_by": list(rank_by),
        "counts": counts,
        "free_play_scoreboard": scoring.get("free_play_scoreboard", True),
        "boards": boards,
        "saved_data": saved,
        # The first ranked field, for places that show one score (game cards, the SDK's "score").
        "primary": rank_by[0] if rank_by else None,
        "label": primary["label"] if primary else "Score",
        "unit": primary["unit"] if primary else "",
        "decimals": primary["decimals"] if primary else 0,
    }


def field(spec, key):
    for f in spec["fields"]:
        if f["key"] == key:
            return f
    return None


def game_fields(spec):
    """The fields a game reports itself."""
    return [f for f in spec["fields"] if f["source"] == "game"]


def check_values(spec, claimed):
    """A game's reported values, checked: {key: number}. Raises ValueError with a message for learners.

    ``claimed`` is {"values": {...}} or, for one score, {"score": n}.
    """
    values = claimed.get("values")
    if values is None and "score" in claimed:
        values = {spec["primary"]: claimed.get("score")}
    if not isinstance(values, dict):
        raise ValueError("The result needs a score.")
    clean = {}
    for f in game_fields(spec):
        v = values.get(f["key"])
        if v is None:
            if f["key"] in spec["rank_by"]:
                raise ValueError("The result needs a value for %s." % f["label"])
            continue
        if not _number_or_none(v) or v != v or v in (float("inf"), float("-inf")):
            raise ValueError("%s must be a number." % f["label"])
        if f["min"] is not None and v < f["min"]:
            raise ValueError("That %s is too low to be possible." % f["label"].lower())
        if f["max"] is not None and v > f["max"]:
            raise ValueError("That %s is too high to be possible." % f["label"].lower())
        clean[f["key"]] = v
    return clean


def board_name(spec, board_id):
    """A board's name from scoring.boards, or None if it doesn't name it."""
    if board_id == TOTAL_BOARD:
        return ((spec.get("boards") or {}).get("total") or {}).get("label", "All")
    boards = spec.get("boards") or {}
    names = boards.get("names") or {}
    # Rules come first: they build a name from part of the id, and {name} is the
    # names entry for that part (or the part itself).
    for rule in boards.get("name_rules") or []:
        prefix, suffix = rule.get("prefix", ""), rule.get("suffix", "")
        if len(board_id) <= len(prefix) + len(suffix):
            continue
        if board_id.startswith(prefix) and board_id.endswith(suffix):
            base = board_id[len(prefix):len(board_id) - len(suffix)] if suffix else board_id[len(prefix):]
            return rule["name"].replace("{name}", names.get(base, base)).replace("{id}", base)
    return names.get(board_id)


def total_spec(spec):
    """The spec of the total scoreboard: a count of boards, then the game's fields added up."""
    total = (spec.get("boards") or {}).get("total")
    if not total:
        return None
    count = {"key": BOARDS_FIELD, "label": total["count_label"], "unit": "", "order": "desc", "decimals": 0,
             "seconds": False, "min": None, "max": None, "source": "plays", "total": "sum", "from": None}
    fields = [count] + [dict(f, decimals=max(f["decimals"], 1) if f["total"] == "average" else f["decimals"])
                        for f in spec["fields"]]
    rank_by = total["rank_by"] or [BOARDS_FIELD] + spec["rank_by"]
    return dict(spec, fields=fields, rank_by=list(rank_by), boards=None)


def public(spec):
    """What the games page needs to show scores."""
    if spec is None:
        return None
    keep = ("key", "label", "unit", "order", "decimals", "seconds", "source", "total")
    out = {
        "fields": [{k: f[k] for k in keep} for f in spec["fields"]],
        "rank_by": spec["rank_by"],
        "counts": spec["counts"],
        "primary": spec["primary"],
        "label": spec["label"],
        "unit": spec["unit"],
        "decimals": spec["decimals"],
        "free_play_scoreboard": spec["free_play_scoreboard"],
        "boards": None,
    }
    if spec.get("boards"):
        b = spec["boards"]
        out["boards"] = {"label": b["label"], "total": bool(b["total"]),
                         "total_label": b["total"]["label"] if b["total"] else None}
    return out
