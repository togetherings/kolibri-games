"""
Which attempt counts, and how results are ranked. Works on any objects with
these attributes (Django models or plain objects):

    user_id, user_name, number, voided, status, score, seconds, verified, finished_at

``status`` is one of: started, finished, abandoned, expired.
"""

FINISHED = "finished"


def num(value):
    """4.0 -> 4 so whole-number scores display cleanly (databases store floats)."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _is_ranked(attempt):
    return attempt.status == FINISHED and attempt.score is not None and not attempt.voided


def sort_key(attempt, scoring):
    score = attempt.score
    primary = score if scoring.get("order", "asc") == "asc" else -score
    secondary = (attempt.seconds or 0) if scoring.get("tiebreak", "seconds") == "seconds" else 0
    finished = attempt.finished_at.timestamp() if attempt.finished_at else 0
    return (primary, secondary, finished)


def first_attempt(attempts):
    """The first attempt that hasn't been voided by a coach (the one that counts in 'first' mode)."""
    live = [a for a in attempts if not a.voided]
    return min(live, key=lambda a: a.number) if live else None


def counted_attempt(attempts, scoring, counts):
    """The attempt that represents this player on the scoreboard, or None."""
    if counts == "first":
        first = first_attempt(attempts)
        return first if first is not None and _is_ranked(first) else None
    ranked = [a for a in attempts if _is_ranked(a)]
    return min(ranked, key=lambda a: sort_key(a, scoring)) if ranked else None


def is_practice(attempt, attempts, counts):
    if counts != "first" or attempt.voided:
        return False
    first = first_attempt(attempts)
    return first is not None and first.number != attempt.number


def by_user(attempts):
    groups = {}
    for a in attempts:
        groups.setdefault(a.user_id, []).append(a)
    return groups


def ranked(attempts, scoring, counts):
    """[(rank, attempt)] using standard competition ranking (1, 2, 2, 4)."""
    chosen = []
    for user_attempts in by_user(attempts).values():
        a = counted_attempt(user_attempts, scoring, counts)
        if a is not None:
            chosen.append(a)
    chosen.sort(key=lambda a: sort_key(a, scoring))
    result, prev, rank = [], None, 0
    for i, a in enumerate(chosen, start=1):
        key = sort_key(a, scoring)[:2]
        if key != prev:
            rank = i
            prev = key
        result.append((rank, a))
    return result


def initials(name):
    parts = [p for p in (name or "").replace(".", " ").split() if p]
    if not parts:
        return "?"
    return "".join(p[0].upper() + "." for p in parts[:3])


def scoreboard_rows(attempts, scoring, counts, me_id=None, visibility="names", limit=20):
    """Rows for display. With visibility 'hidden' only the viewer's own row is returned."""
    rows = []
    for rank, a in ranked(attempts, scoring, counts):
        me = a.user_id == me_id
        if visibility == "hidden" and not me:
            continue
        name = a.user_name
        if visibility == "initials" and not me:
            name = initials(a.user_name)
        rows.append(
            {
                "rank": rank,
                "name": name,
                "score": num(a.score),
                "seconds": round(a.seconds or 0, 1),
                "verified": bool(a.verified),
                "me": me,
            }
        )
    top = rows[:limit]
    mine = [r for r in rows if r["me"]]
    if mine and mine[0] not in top:
        top.append(mine[0])
    return top
