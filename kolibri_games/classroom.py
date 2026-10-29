"""
Classroom Games: HTML5 apps in Kolibri channels that learners open from Learn.

Kolibri keeps each learner's saved data for an HTML5 app (for example SCORM
``cmi.suspend_data``) on the server. A Classroom Game's ``kolibri-game.json``
says how to read scores out of that data. This module turns the saved data of
every resource (lesson) of one game into scoreboards, so the games page can
show them. No Django or Kolibri imports.

Words used here:

* game: the umbrella, for example "Lessons In Typing". One manifest id.
* resource: one HTML5 app in a channel (one Kolibri content item). A game can
  have many, and they can be in different lessons and channels.
* board: one scored thing inside the saved data, for example a typing lesson
  or a map played in one mode. The same board can be saved by more than one
  resource; those are merged, keeping each learner's best result.
"""
import json
import math
import re

from . import ranking
from .versions import VersionError, parse_version

KEY_PREFIX = "g-"
MAX_SAVED_CHARS = 65536
MAX_BOARD_ID = 100
MAX_BOARDS_PER_SAVE = 500


# ------------------------------------------------------------ reading data


def suspend_data(content_state):
    """The parsed SCORM suspend_data of one learner and one resource, or None."""
    if not isinstance(content_state, dict):
        return None
    scorm = content_state.get("SCORM")
    if not isinstance(scorm, dict):
        return None
    raw = None
    cmi = scorm.get("cmi")
    if isinstance(cmi, dict):
        raw = cmi.get("suspend_data")
    if raw is None:
        raw = scorm.get("cmi.suspend_data")
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip() or len(raw) > MAX_SAVED_CHARS:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _pick(entry, where):
    if isinstance(where, int):
        if isinstance(entry, (list, tuple)) and 0 <= where < len(entry):
            return entry[where]
        return None
    if isinstance(entry, dict):
        return entry.get(where)
    return None


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    if isinstance(value, float) and value == int(value) and abs(value) < 1e15:
        return int(value)
    return value


def read_boards(spec, content_state):
    """{board_id: {field_key: number or None}} from one learner's saved data."""
    data = suspend_data(content_state) if spec.get("saved_in", "scorm") == "scorm" else None
    if not data:
        return {}
    only_if = spec.get("only_if")
    found = {}
    for board_id, entry in list(data.items())[:MAX_BOARDS_PER_SAVE]:
        if not isinstance(board_id, str) or not board_id or len(board_id) > MAX_BOARD_ID:
            continue
        if only_if and _pick(entry, only_if["from"]) != only_if["equals"]:
            continue
        values = {f["key"]: _number(_pick(entry, f["from"])) for f in spec["fields"]}
        if all(v is None for v in values.values()):
            continue
        found[board_id] = values
    return found


# ------------------------------------------------------------- board names


def board_name(spec, board_id):
    """A board's display name from the manifest, or None if it doesn't name it."""
    names = spec.get("board_names") or {}
    # Rules come first: they say how to build a name from part of the id, and
    # {name} is the board_names entry for that part (or the part itself).
    for rule in spec.get("board_name_rules") or []:
        prefix, suffix = rule.get("prefix", ""), rule.get("suffix", "")
        if len(board_id) <= len(prefix) + len(suffix):
            continue
        if board_id.startswith(prefix) and board_id.endswith(suffix):
            base = board_id[len(prefix):len(board_id) - len(suffix)] if suffix else board_id[len(prefix):]
            return rule["name"].replace("{name}", names.get(base, base)).replace("{id}", base)
    return names.get(board_id)


def natural_key(text):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text or "")]


# ----------------------------------------------------------------- ranking


def _rank_key(spec, values):
    fields = {f["key"]: f for f in spec["fields"]}
    key = []
    for k in spec["rank_by"]:
        v = values.get(k)
        if v is None:
            key.append((1, 0))
        else:
            key.append((0, -v if fields[k]["order"] == "desc" else v))
    return tuple(key)


def combine(spec, entries):
    """One learner's result on one board from the entries saved by different resources."""
    best = min(entries, key=lambda values: _rank_key(spec, values))
    result = {}
    for f in spec["fields"]:
        vals = [e.get(f["key"]) for e in entries if e.get(f["key"]) is not None]
        if f["combine"] == "sum":
            result[f["key"]] = sum(vals) if vals else None
        elif f["combine"] == "max":
            result[f["key"]] = max(vals) if vals else None
        else:
            result[f["key"]] = best.get(f["key"])
    return result


# ---------------------------------------------------------------- the game


class ClassroomResource(object):
    """One HTML5 app in a channel (or several copies of it with the same content id)."""

    def __init__(self, source, manifest, content):
        self.source = source
        self.manifest = manifest
        self.content = content  # content_id, node_id, title, channel_id
        self.node_ids = [content.get("node_id")]

    @property
    def content_id(self):
        return self.content.get("content_id")

    @property
    def title(self):
        return self.content.get("title") or self.manifest.title

    def public(self):
        return {"content_id": self.content_id, "node_id": self.node_ids[0], "title": self.title}


class ClassroomGame(object):
    """The umbrella over every resource that shares one manifest id."""

    origin = "channel"
    is_classroom = True

    def __init__(self, resources):
        resources = sorted(resources, key=lambda r: natural_key(r.title))
        self.resources = resources
        newest = max(resources, key=lambda r: ranking_version(r.manifest.version))
        self.manifest = newest.manifest
        self.source = newest.source
        self.key = KEY_PREFIX + self.manifest.id
        self.problems = []
        self.spec = merged_spec([r.manifest for r in resources], self.manifest)

    playable = True

    @property
    def title(self):
        return self.manifest.title

    @property
    def content_ids(self):
        return [r.content_id for r in self.resources]

    def data_paths(self):
        return {}

    def describe(self):
        return {
            "key": self.key,
            "origin": self.origin,
            "kind": self.source.kind,
            "type": "classroom",
            "location": self.source.location,
            "title": self.title,
            "version": self.manifest.version,
            "id": self.manifest.id,
            "playable": True,
            "problems": self.problems,
            "content": {"resources": [r.public() for r in self.resources]},
        }


def ranking_version(version):
    try:
        return parse_version(version)
    except VersionError:
        return ()


def merged_spec(manifests, newest):
    """The newest manifest's scoreboards, with board names from every version (newer names win)."""
    spec = dict(newest.scoreboards)
    names = {}
    for m in sorted(manifests, key=lambda m: ranking_version(m.version)):
        names.update(m.scoreboards.get("board_names") or {})
    spec["board_names"] = names
    return spec


def group_resources(resources):
    """[ClassroomGame] from ClassroomResources, one game per manifest id. Copies of a content id are joined."""
    by_content = {}
    for r in resources:
        if r.content_id in by_content:
            by_content[r.content_id].node_ids.append(r.content.get("node_id"))
        else:
            by_content[r.content_id] = r
    by_id = {}
    for r in by_content.values():
        by_id.setdefault(r.manifest.id, []).append(r)
    return [ClassroomGame(rs) for rs in by_id.values()]


# -------------------------------------------------------------- scoreboards


def collect(game, saves):
    """{board_id: {"users": {user_id: [values...]}, "names": {user_id: name}, "resources": [content_id]}}"""
    resources = {r.content_id: r for r in game.resources}
    boards = {}
    for save in saves:
        resource = resources.get(save["content_id"])
        if resource is None:
            continue
        for board_id, values in read_boards(game.spec, save.get("content_state")).items():
            board = boards.setdefault(board_id, {"users": {}, "names": {}, "resources": []})
            board["users"].setdefault(save["user_id"], []).append(values)
            board["names"][save["user_id"]] = save.get("user_name") or "?"
            if resource.content_id not in board["resources"]:
                board["resources"].append(resource.content_id)
    return boards


def _board_title(game, board_id, resource_ids, resources, boards_in_resource):
    name = board_name(game.spec, board_id)
    if name:
        return name
    if game.spec.get("name_boards_after_resource") and resource_ids:
        first = resources[resource_ids[0]]
        if boards_in_resource.get(first.content_id, 1) > 1:
            return "%s (%s)" % (first.title, board_id)
        return first.title
    return board_id


def public_spec(spec):
    return {
        "board_label": spec["board_label"],
        "rank_by": spec["rank_by"],
        "fields": [
            {k: f[k] for k in ("key", "label", "unit", "order", "decimals", "seconds", "combine")} for f in spec["fields"]
        ],
    }


def scoreboards(game, saves, viewer_id, visibility="names"):
    """Everything the games page shows for a Classroom Game."""
    spec = game.spec
    resources = {r.content_id: r for r in game.resources}
    boards = collect(game, saves)
    boards_in_resource = {}
    for board in boards.values():
        for cid in board["resources"]:
            boards_in_resource[cid] = boards_in_resource.get(cid, 0) + 1
    out = []
    for board_id, board in boards.items():
        results = []
        for user_id, entries in board["users"].items():
            results.append((user_id, combine(spec, entries)))
        results.sort(key=lambda item: (_rank_key(spec, item[1]), board["names"][item[0]].lower()))
        rows, prev, rank = [], None, 0
        for i, (user_id, values) in enumerate(results, start=1):
            key = _rank_key(spec, values)
            if key != prev:
                rank, prev = i, key
            me = user_id == viewer_id
            if visibility == "hidden" and not me:
                continue
            name = board["names"][user_id]
            if visibility == "initials" and not me:
                name = ranking.initials(name)
            rows.append({"rank": rank, "name": name, "me": me, "values": values})
        out.append(
            {
                "id": board_id,
                "name": _board_title(game, board_id, board["resources"], resources, boards_in_resource),
                "players": len(results),
                "resources": [resources[cid].public() for cid in board["resources"]],
                "rows": rows,
                "mine": next((r for r in rows if r["me"]), None),
            }
        )
    out.sort(key=lambda b: natural_key(b["name"]))
    return {
        "spec": public_spec(spec),
        "visibility": visibility,
        "boards": out,
        "resources": [r.public() for r in game.resources],
    }


def summary(game, saves):
    """The viewer's own progress, for the game card. ``saves`` are the viewer's only."""
    boards = collect(game, saves)
    return {"boards": len(boards), "resources": len(game.resources)}
