"""
Which result counts for each learner, and how results are ranked. Used for the
games page (attempts) and for games in channels (saved data). No Django imports.

A result is a dict of values, one per field of the game's scoring spec (see
scoring.py): {"acc": 97, "wpm": 41, "time": 63.2, "plays": 3}. Results are
ranked by the spec's ``rank_by``: the first field decides, the next ones break
ties, and each field is better lower ("asc") or higher ("desc"). A missing
value ranks last.

Attempts are any objects (Django models or plain objects) with:

    id, user_id, user_name, number, voided, status, score, seconds,
    finished_at, board, values

``status`` is one of: started, finished, abandoned, expired.
"""

FINISHED = "finished"


def num(value):
    """4.0 -> 4 so whole-number scores display cleanly (databases store floats)."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def rank_key(spec, values, rank_by=None):
    """Sorts best first. A missing value ranks after every real one."""
    orders = {f["key"]: f["order"] for f in spec["fields"]}
    key = []
    for k in rank_by or spec["rank_by"]:
        v = values.get(k)
        if v is None:
            key.append((1, 0))
        else:
            key.append((0, -v if orders.get(k) == "desc" else v))
    return tuple(key)


def add_up(spec, results):
    """Several results combined into one, each field by its ``total`` rule (see scoring.py)."""
    out = {}
    best = min(results, key=lambda v: rank_key(spec, v)) if results else {}
    for f in spec["fields"]:
        vals = [r.get(f["key"]) for r in results if r.get(f["key"]) is not None]
        rule = f["total"]
        if not vals:
            out[f["key"]] = None
        elif rule == "sum":
            out[f["key"]] = num(round(sum(vals), 6))
        elif rule == "average":
            out[f["key"]] = num(round(sum(vals) / float(len(vals)), 6))
        elif rule == "min":
            out[f["key"]] = min(vals)
        elif rule == "max":
            out[f["key"]] = max(vals)
        elif rule == "latest":
            out[f["key"]] = vals[-1]
        else:  # best: the value from the best result
            out[f["key"]] = best.get(f["key"])
    return out


# ------------------------------------------------------------ attempts


def attempt_values(attempt, spec):
    """An attempt's values: what the game reported, plus the time the server measured."""
    values = dict(getattr(attempt, "values", None) or {})
    if not values and attempt.score is not None and spec.get("primary"):
        values[spec["primary"]] = num(attempt.score)  # Server Games and one-score games
    for f in spec["fields"]:
        if f["source"] == "time":
            values[f["key"]] = round(attempt.seconds, 1) if attempt.seconds is not None else None
    return values


def _is_ranked(attempt):
    return attempt.status == FINISHED and not attempt.voided and (
        attempt.score is not None or bool(getattr(attempt, "values", None))
    )


def first_attempt(attempts):
    """The first attempt that hasn't been voided by a coach (the one that counts in 'first' mode)."""
    live = [a for a in attempts if not a.voided]
    return min(live, key=lambda a: a.number) if live else None


def is_practice(attempt, attempts, counts):
    if counts != "first" or attempt.voided:
        return False
    first = first_attempt([a for a in attempts if (getattr(a, "board", "") or "") == (getattr(attempt, "board", "") or "")])
    return first is not None and first.number != attempt.number


class Result(object):
    """One learner's counted result on one board."""

    def __init__(self, user_id, user_name, values, attempt=None, finished_at=0):
        self.user_id = user_id
        self.user_name = user_name
        self.values = values
        self.attempt = attempt  # the attempt it comes from (None when results are added up)
        self.finished_at = finished_at


def _with_plays(spec, values, plays):
    for f in spec["fields"]:
        if f["source"] == "plays":
            values[f["key"]] = plays
    return values


def _stamp(a):
    return a.finished_at.timestamp() if getattr(a, "finished_at", None) else 0


def counted(attempts, spec, counts):
    """The Result that stands for one learner on one board, or None.

    counts: "first" (their first attempt; later ones are practice), "best",
    "latest", or "total" (every finished attempt added up).
    """
    live = [a for a in attempts if not a.voided]
    done = [a for a in live if _is_ranked(a)]
    if not done:
        return None
    if counts == "first":
        first = first_attempt(live)
        if first is None or not _is_ranked(first):
            return None
        chosen, values = first, attempt_values(first, spec)
    elif counts == "latest":
        chosen = max(done, key=lambda a: (_stamp(a), a.number))
        values = attempt_values(chosen, spec)
    elif counts == "total":
        ordered = sorted(done, key=lambda a: a.number)
        chosen, values = ordered[-1], add_up(spec, [attempt_values(a, spec) for a in ordered])
    else:
        chosen = min(done, key=lambda a: (rank_key(spec, attempt_values(a, spec)), _stamp(a)))
        values = attempt_values(chosen, spec)
    values = _with_plays(spec, values, len(done))
    return Result(chosen.user_id, chosen.user_name, values, chosen if counts != "total" else None, _stamp(chosen))


def by_user(attempts):
    groups = {}
    for a in attempts:
        groups.setdefault(a.user_id, []).append(a)
    return groups


def by_board(attempts):
    groups = {}
    for a in attempts:
        groups.setdefault(getattr(a, "board", "") or "", []).append(a)
    return groups


def rank(spec, results):
    """[(rank, Result)], best first, with standard competition ranking (1, 2, 2, 4)."""
    results = sorted(results, key=lambda r: (rank_key(spec, r.values), r.finished_at, (r.user_name or "").lower()))
    out, prev, place = [], None, 0
    for i, r in enumerate(results, start=1):
        key = rank_key(spec, r.values)
        if key != prev:
            place, prev = i, key
        out.append((place, r))
    return out


def ranked(attempts, spec, counts):
    """[(rank, Result)] for the attempts of one board."""
    results = [counted(mine, spec, counts) for mine in by_user(attempts).values()]
    return rank(spec, [r for r in results if r is not None])


def totals(results_by_board, spec):
    """Each learner's results on every board added up, for the total scoreboard.

    ``results_by_board`` is {board_id: [Result]}; ``spec`` is scoring.total_spec(...).
    """
    mine = {}
    for results in results_by_board.values():
        for r in results:
            mine.setdefault(r.user_id, []).append(r)
    out = []
    for user_id, results in mine.items():
        values = add_up(spec, [r.values for r in results])
        values["boards"] = len(results)
        out.append(Result(user_id, results[0].user_name, values, None, max(r.finished_at for r in results)))
    return rank(spec, out)


def initials(name):
    parts = [p for p in (name or "").replace(".", " ").split() if p]
    if not parts:
        return "?"
    return "".join(p[0].upper() + "." for p in parts[:3])


def rows(spec, ranked_results, me_id=None, visibility="names", limit=20):
    """Rows for display. With visibility 'hidden' only the viewer's own row is returned.

    Each row has ``values`` (every field), and ``score`` and ``seconds`` (the
    first ranked field and the time) for games that show one score. Rows from
    one attempt carry its id as ``attempt_id`` (the caller removes it or uses
    it to add details such as a Wiki BLAZE route).
    """
    time_key = next((f["key"] for f in spec["fields"] if f["source"] == "time"), None)
    out = []
    for place, r in ranked_results:
        me = r.user_id == me_id
        if visibility == "hidden" and not me:
            continue
        name = r.user_name
        if visibility == "initials" and not me:
            name = initials(r.user_name)
        out.append({
            "rank": place,
            "name": name,
            "me": me,
            "values": r.values,
            "score": r.values.get(spec["primary"]),
            "seconds": r.values.get(time_key) if time_key else (round(r.attempt.seconds or 0, 1) if r.attempt else None),
            "attempt_id": r.attempt.id if r.attempt is not None else None,
        })
    top = out[:limit]
    mine = [r for r in out if r["me"]]
    if mine and mine[0] not in top:
        top.append(mine[0])
    return top
