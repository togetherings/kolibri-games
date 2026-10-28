"""
Preview server for game authors: runs the real games page, SDK and game rules
without Kolibri, with pretend users and everything kept in memory.

    python -m kolibri_games.devserver path/to/games-folder [--port 8765]
        [--lessons examples/lesson-games/preview.json]

Then open http://127.0.0.1:8765/ and switch between pretend learners and a
coach with the bar at the bottom of the page. ``--lessons`` adds Lesson Games
with pretend saved data, as if learners had played them in Learn (see
examples/lesson-games/preview.json). Only uses the standard library.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import API_VERSION, __version__, registry, validators, views_common
from .service import GameService, MemoryStore, PlatformError, Player
from .sources import open_source

FACILITY = "f" * 32
CLASS_ID = "e" * 32
USERS = {
    "amina": Player("a" * 32, "Amina Learner", FACILITY),
    "ben": Player("b" * 32, "Ben Learner", FACILITY),
    "coach": Player("c" * 32, "Ms Coach", FACILITY, is_coach=True),
    "admin": Player("d" * 32, "Device Admin", FACILITY, is_admin=True),
}
CLASS_MEMBERS = ["amina", "ben"]
SECRET = secrets.token_bytes(32)
ASSETS = os.path.join(os.path.dirname(__file__), "assets")

store = MemoryStore()
service = GameService(store)


def load_lessons(path):
    """Add the Lesson Game resources and pretend saved data described in a JSON file."""
    with open(path, encoding="utf-8") as f:
        spec = json.load(f)
    base = os.path.dirname(os.path.abspath(path))
    for r in spec.get("resources", []):
        content = {k: r[k] for k in ("content_id", "node_id", "title")}
        content["channel_id"] = r.get("channel_id", "0" * 32)
        registry.PREVIEW_LESSONS.append((open_source(os.path.join(base, r["source"])), content))
    for save in spec.get("saves", []):
        data = save["suspend_data"]
        state = {"SCORM": {"cmi": {"suspend_data": data if isinstance(data, str) else json.dumps(data)}}}
        store.add_lesson_save(USERS[save["user"]], save["content_id"], state)


def sign(payload):
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    mac = hmac.new(SECRET, raw.encode(), hashlib.sha256).hexdigest()[:24]
    return raw + "." + mac


def unsign(token):
    raw, _, mac = token.rpartition(".")
    good = hmac.new(SECRET, raw.encode(), hashlib.sha256).hexdigest()[:24]
    if not hmac.compare_digest(mac, good):
        return None
    return json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))


SWITCHER = """
<div style="position:fixed;left:0;right:0;bottom:0;z-index:50;display:flex;flex-wrap:wrap;gap:.4rem .9rem;
align-items:center;padding:.4rem .8rem;background:#222;color:#eee;font:13px system-ui,sans-serif">
<b>Preview server</b><span>Playing as %(name)s.</span><span>Switch to:</span>%(links)s
<span style="opacity:.7">Nothing is saved when this server stops.</span></div>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "KolibriGamesPreview/" + __version__

    def log_message(self, fmt, *args):
        if os.environ.get("KOLIBRI_GAMES_DEV_QUIET") != "1":
            sys.stderr.write("%s\n" % (fmt % args))

    # ------------------------------------------------------------ plumbing

    def who(self):
        query = parse_qs(urlsplit(self.path).query)
        if "as" in query and query["as"][0] in USERS:
            return query["as"][0], True
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        name = cookie["kg_as"].value if "kg_as" in cookie else "amina"
        return (name if name in USERS else "amina"), False

    def send(self, status, body, ctype, headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def json(self, status, data):
        self.send(status, json.dumps(data), "application/json")

    def body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            raise PlatformError("The request wasn't valid JSON.", "bad_request")
        if not isinstance(data, dict):
            raise PlatformError("The request wasn't a JSON object.", "bad_request")
        return data

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    # -------------------------------------------------------------- routes

    def route(self, method):
        url = urlsplit(self.path)
        path, query = url.path, {k: v[0] for k, v in parse_qs(url.query).items()}
        name, from_query = self.who()
        player = USERS[name]
        try:
            if path == "/" and method == "GET":
                return self.index(name, from_query)
            if path.startswith("/assets/") and method == "GET":
                return self.asset(path[len("/assets/"):])
            if path.startswith("/play/") and method == "GET":
                return self.play(path[len("/play/"):])
            if path.startswith("/api/"):
                return self.api(method, path[len("/api/"):].split("/"), query, player)
        except PlatformError as e:
            extra = {"fields": e.fields} if getattr(e, "fields", None) else {}
            return self.json(e.status, dict({"error": e.code, "message": str(e)}, **extra))
        self.send(404, "Not found", "text/plain")

    def index(self, name, set_cookie):
        with open(os.path.join(ASSETS, "index.html"), encoding="utf-8") as f:
            html = f.read()
        html = html.replace("{{CSRF_TOKEN}}", "preview").replace("{{VERSION}}", __version__).replace("{{KOLIBRI_ROOT}}", "/")
        links = " ".join(
            '<a style="color:#9cf" href="/?as=%s">%s</a>' % (k, USERS[k].name) for k in USERS if k != name
        )
        html = html.replace("</body>", SWITCHER % {"name": USERS[name].name, "links": links} + "</body>")
        headers = {"Set-Cookie": "kg_as=%s; Path=/; SameSite=Lax" % name} if set_cookie else {}
        self.send(200, html, "text/html; charset=utf-8", headers)

    def asset(self, name):
        types = views_common.ASSET_TYPES
        if name not in types:
            return self.send(404, "Not found", "text/plain")
        with open(os.path.join(ASSETS, name), "rb") as f:
            self.send(200, f.read(), types[name])

    def play(self, rest):
        token, _, file_path = rest.partition("/")
        claims = unsign(token)
        game = registry.get(claims.get("k")) if claims else None
        if game is None or game.manifest is None:
            return self.send(403, "This game link has expired.", "text/plain")
        if file_path == views_common.SDK_PATH:
            with open(os.path.join(ASSETS, "sdk.js"), "rb") as f:
                found = (f.read(), "text/javascript")
        else:
            found = game.source.read(file_path or game.manifest.entry)
        if found is None:
            return self.send(404, "Not found in this game: %s" % file_path, "text/plain")
        data, mimetype = found
        if mimetype.startswith("text/") and "charset" not in mimetype:
            mimetype += "; charset=utf-8"
        self.send(200, data, mimetype, views_common.game_file_headers())

    def game(self, key, playable=True):
        game = registry.get(key)
        if game is None:
            raise PlatformError("That game isn't on this device.", "not_found", 404)
        if playable and game.is_lesson:
            raise PlatformError("This is a Lesson Game. Open it from Learn.", "lesson_game", 409)
        if playable and not game.playable:
            raise PlatformError(" ".join(game.problems), "unplayable", 409)
        return game

    def class_users(self, class_id):
        if not class_id:
            return None
        return [(USERS[k].id, USERS[k].name) for k in CLASS_MEMBERS]

    def api(self, method, parts, query, player):
        if parts == ["games"]:
            games = registry.discover()
            return self.json(200, {
                "me": {"name": player.name, "role": player.role},
                "platform": {"version": __version__, "api": API_VERSION},
                "games": [views_common.card(service, g, player) for g in games if g.manifest is not None or player.is_admin],
            })
        if parts == ["classes"]:
            self.require(player, coach=True)
            return self.json(200, {"classes": [{"id": CLASS_ID, "name": "Class A"}], "whole_facility": True})
        if parts == ["status"]:
            self.require(player, admin=True)
            return self.json(200, {
                "platform": {"version": __version__, "api": API_VERSION},
                "games": [g.describe() for g in registry.discover(refresh=True)],
                "validators": sorted(validators.registry()),
                "data_sources": registry.data_sources(),
                "data_sources_file": registry.data_sources_file(),
                "local_dirs": registry.local_game_dirs(),
            })
        if len(parts) < 2 or parts[0] != "games":
            raise PlatformError("Not found.", "not_found", 404)
        key, rest = parts[1], parts[2:]
        if rest == [] and method == "GET":
            game = self.game(key)
            payload = views_common.session(service, game, player)
            payload["play_url"] = "play/%s/" % sign({"k": game.key, "u": player.id})
            return self.json(200, payload)
        if rest == ["icon"]:
            game = self.game(key, playable=False)
            data, ctype = views_common.icon(game)
            return self.send(200, data, ctype)
        if rest == ["attempts"] and method == "POST":
            data = self.body()
            return self.json(201, service.start(self.game(key), player, resume=bool(data.get("resume", True))))
        if len(rest) == 3 and rest[0] == "attempts" and method == "POST":
            game, attempt_id, action = self.game(key, playable=rest[2] != "abandon"), int(rest[1]), rest[2]
            data = self.body()
            if action == "events":
                return self.json(200, service.event(game, player, attempt_id, data.get("type"), data.get("data")))
            if action == "finish":
                return self.json(200, service.finish(game, player, attempt_id, data))
            if action == "abandon":
                return self.json(200, service.abandon(game, player, attempt_id))
        if rest == ["call"] and method == "POST":
            data = self.body()
            return self.json(200, service.call(self.game(key), player, data.get("method"), data.get("params")))
        if rest == ["leaderboard"]:
            users = self.class_users(query.get("class")) if player.is_coach else None
            ids = {u for u, _ in users} if users else None
            return self.json(200, service.leaderboard(self.game(key, playable=False), player, user_ids=ids))
        if rest == ["scoreboards"]:
            users = self.class_users(query.get("class")) if player.is_coach else None
            ids = {u for u, _ in users} if users else None
            data = service.scoreboards(self.game(key, playable=False), player, user_ids=ids)
            if query.get("format") == "csv":
                self.require(player, coach=True)
                return self.send(200, views_common.scoreboards_csv(data), "text/csv; charset=utf-8",
                                 {"Content-Disposition": 'attachment; filename="scores.csv"'})
            return self.json(200, data)
        if rest == ["mine"]:
            return self.json(200, {"attempts": service.my_attempts(self.game(key, playable=False), player)})
        if rest == ["state"]:
            game = self.game(key)
            if method == "POST":
                return self.json(200, service.set_state(game, player, self.body().get("data")))
            return self.json(200, {"data": service.get_state(game, player)})
        if rest == ["settings"]:
            self.require(player, coach=True)
            game = self.game(key, playable=False)
            if method == "POST":
                data = self.body()
                service.save_settings(game, player.facility_id, data.get("platform"), data.get("game"), player.id)
            p, g = service.settings(game, player.facility_id)
            return self.json(200, {"schema": service.schema(game), "values": {"platform": p, "game": g}})
        if rest == ["results"]:
            self.require(player, coach=True)
            game = self.game(key, playable=False)
            data = service.coach_results(game, player.facility_id, self.class_users(query.get("class")))
            if query.get("format") == "csv":
                return self.send(200, views_common.results_csv(data), "text/csv; charset=utf-8",
                                 {"Content-Disposition": 'attachment; filename="results.csv"'})
            return self.json(200, data)
        if len(rest) == 3 and rest[0] == "results" and rest[2] == "reset" and method == "POST":
            self.require(player, coach=True)
            return self.json(200, service.reset(self.game(key, playable=False), player.facility_id, rest[1]))
        raise PlatformError("Not found.", "not_found", 404)

    @staticmethod
    def require(player, coach=False, admin=False):
        if admin and not player.is_admin:
            raise PlatformError("Only administrators can see this.", "forbidden", 403)
        if coach and not player.is_coach:
            raise PlatformError("Only coaches and administrators can do this.", "forbidden", 403)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Preview Kolibri Games without Kolibri.")
    parser.add_argument("folders", nargs="*", help="Folders containing games (folders or .zim files).")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--lessons", help="JSON file with Lesson Game resources and pretend saved data.")
    args = parser.parse_args(argv)
    if args.folders:
        os.environ["KOLIBRI_GAMES_PATH"] = os.pathsep.join(os.path.abspath(f) for f in args.folders)
    os.environ.setdefault("KOLIBRI_HOME", os.path.join(os.path.expanduser("~"), ".kolibri-games-preview"))
    if args.lessons:
        load_lessons(args.lessons)
    games = registry.discover(refresh=True)
    print("Kolibri Games preview %s" % __version__)
    for g in games:
        print("  %s %s%s" % ("ok" if g.playable else "!!", g.title, "" if g.playable else ": " + " ".join(g.problems)))
    if not games:
        print("  No games found. Pass a folder that contains game folders or .zim files.")
    print("Open http://%s:%d/" % (args.host, args.port))
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
