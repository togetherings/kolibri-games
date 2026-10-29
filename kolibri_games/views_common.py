"""Response building shared by the Kolibri views and the preview server (no Django imports)."""
import csv
import io
from html import escape
from urllib.parse import unquote

from . import API_VERSION, __version__

ASSET_TYPES = {
    "app.js": "text/javascript",
    "app.css": "text/css",
    "sdk.js": "text/javascript",
}

SDK_PATH = "__kolibri_games__/sdk.js"
#: Pictures from the Wikipedia file, for games that use wikipedia-race (see wiki.py).
WIKI_PREFIX = "__wiki__/"

# Applied to every game file. "sandbox" keeps a game in an opaque origin even if
# someone opens its URL directly, and the source lists stop games from loading
# anything from outside this server.
GAME_CSP = (
    "sandbox allow-scripts allow-forms allow-pointer-lock; "
    "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob:; "
    "connect-src 'self'; form-action 'none'; base-uri 'self'"
)


def game_file_headers():
    return {
        "Content-Security-Policy": GAME_CSP,
        "Access-Control-Allow-Origin": "*",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }


def card(service, game, player):
    """A game as the games list shows it, with the viewer's own results and challenges."""
    data = {
        "key": game.key,
        "title": game.title,
        "origin": game.origin,
        "playable": game.playable,
        "problems": game.problems,
    }
    if game.manifest is not None:
        data.update(game.manifest.to_public())
        if game.playable:
            data["summary"] = service.summary(game, player)
            if not game.is_classroom:
                data["free_play_scoreboard"] = game.manifest.free_play_scoreboard
                data["challenges"] = service.challenges_for(game, player)
    if game.is_classroom:
        data["resources"] = [r.public() for r in game.resources]
    return data


def session(service, game, player, challenge_id=None):
    """Everything the page needs to open a game (the caller adds play_url)."""
    ctx = service.context(game, player, challenge_id)
    return {
        "game": dict(game.manifest.to_public(), key=game.key, origin=game.origin),
        "player": {"name": player.name, "role": player.role},
        "platform": {"version": __version__, "api": API_VERSION},
        "settings": ctx.settings,
        "rules": {
            "counts": ctx.counts,
            "scoreboard": ctx.visibility,
            "time_limit": ctx.time_limit or None,
            "free_play_scoreboard": game.manifest.free_play_scoreboard,
        },
        "challenge": service.challenge_public(game, ctx.challenge, player) if ctx.challenge else None,
        "summary": service.challenge_summary(game, player, ctx.challenge) if ctx.challenge else service.summary(game, player),
        "sdk_path": SDK_PATH,
    }


def wiki_file(service, game, path):
    """(bytes, mimetype) of an image from the Wikipedia file, for a game that uses wikipedia-race."""
    if game.manifest is None or game.manifest.service != "wikipedia-race":
        return None
    try:
        source = service.wiki_source(game)
    except Exception:
        return None
    found = source.read_file(unquote(path))
    if found is None or not found[1].startswith("image/"):
        return None  # only pictures: articles go through the race rules
    return found


def default_icon_svg(title, color):
    letter = escape((title or "?").strip()[:1].upper() or "?")
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">'
        '<rect width="96" height="96" rx="22" fill="%s"/>'
        '<text x="48" y="64" font-family="system-ui,sans-serif" font-size="46" font-weight="700" '
        'text-anchor="middle" fill="#fff">%s</text></svg>' % (escape(color), letter)
    )


def icon(game):
    """(bytes, content type) for the game's icon, or a generated one."""
    found = game.source.read(game.manifest.icon) if game.manifest and game.manifest.icon else None
    if found is None or not found[1].startswith("image/"):
        title = game.manifest.title if game.manifest else game.title
        color = game.manifest.color if game.manifest else "#667085"
        found = (default_icon_svg(title, color).encode("utf-8"), "image/svg+xml")
    return found


def csv_response_headers(game, what):
    safe = "".join(c if c.isalnum() else "-" for c in game.title.lower()).strip("-")
    return {"Content-Disposition": 'attachment; filename="%s-%s.csv"' % (safe or "game", what)}


def _csv_value(field, value):
    if value is None:
        return ""
    return value


def scoreboards_csv(data):
    out = io.StringIO()
    writer = csv.writer(out)
    spec = data["spec"]
    fields = spec["fields"]
    writer.writerow(
        [spec["board_label"], "Rank", "Name"]
        + ["%s (%s)" % (f["label"], "seconds" if f["seconds"] else f["unit"]) if (f["unit"] or f["seconds"]) else f["label"] for f in fields]
    )
    for board in data["boards"]:
        for row in board["rows"]:
            writer.writerow(
                [board["name"], row["rank"], row["name"]] + [_csv_value(f, row["values"].get(f["key"])) for f in fields]
            )
    return out.getvalue()


def results_csv(data):
    out = io.StringIO()
    writer = csv.writer(out)
    label = (data.get("scoring") or {}).get("label", "Score")
    writer.writerow(["Rank", "Name", "Counted %s" % label, "Counted seconds", "Best %s" % label, "Attempts", "Last played", "Route"])
    for r in data["rows"]:
        counted, best = r["counted"] or {}, r["best"] or {}
        route = ""
        for a in r.get("history") or []:
            if counted and a["id"] == counted.get("id"):
                route = " > ".join((a.get("detail") or {}).get("route") or [])
        writer.writerow(
            [
                r["rank"] or "",
                r["name"],
                counted.get("score", ""),
                counted.get("seconds", ""),
                best.get("score", ""),
                r["attempts"],
                r["last_played"] or "",
                route,
            ]
        )
    return out.getvalue()
