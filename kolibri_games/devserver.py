"""
Preview server for game authors: runs the real games page, SDK and game rules
without Kolibri, with pretend users and everything kept in memory. Only uses
the standard library. It answers the same addresses as views.py, so change
both together.

    kolibri-games-preview path/to/games-folder [--port 8765]
        [--wikipedia examples/tiny-wiki]            (or a Wikipedia .zim file)
        [--classroom examples/classroom-games/preview.json]

Then open http://127.0.0.1:8765/ and switch between pretend learners, a coach
and an administrator with the bar at the bottom of the page.

* Game folders (or .zip files) in the folders you name are Free-play Games.
* ``--wikipedia`` chooses the Wikipedia data for Wiki BLAZE.
* ``--classroom`` adds Classroom Games with pretend saved data, as if learners
  had played them in Learn.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import tempfile
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import API_VERSION, __version__, install, registry, views_common
from .service import FREE_PLAY, GameService, MemoryStore, PlatformError, Player
from .sources import open_source

FACILITY = "f" * 32
CLASS_ID = "e" * 32
CLASSES = {CLASS_ID: "Class A"}
USERS = {
    "amina": Player("a" * 32, "Amina Learner", FACILITY, class_ids={CLASS_ID}),
    "ben": Player("b" * 32, "Ben Learner", FACILITY, class_ids={CLASS_ID}),
    "coach": Player("c" * 32, "Ms Coach", FACILITY, is_coach=True, coach_class_ids={CLASS_ID}),
    "admin": Player("d" * 32, "Device Admin", FACILITY, is_admin=True, coach_class_ids=None),
}
CLASS_MEMBERS = ["amina", "ben"]
SECRET = secrets.token_bytes(32)
ASSETS = os.path.join(os.path.dirname(__file__), "assets")

store = MemoryStore()
service = GameService(store)


def load_classroom(path):
    """Add the Classroom Game resources and pretend saved data described in a JSON file."""
    with open(path, encoding="utf-8") as f:
        spec = json.load(f)
    base = os.path.dirname(os.path.abspath(path))
    for r in spec.get("resources", []):
        content = {k: r[k] for k in ("content_id", "node_id", "title")}
        content["channel_id"] = r.get("channel_id", "0" * 32)
        registry.PREVIEW_CLASSROOM.append((open_source(os.path.join(base, r["source"])), content))
    for save in spec.get("saves", []):
        data = save["suspend_data"]
        state = {"SCORM": {"cmi": {"suspend_data": data if isinstance(data, str) else json.dumps(data)}}}
        store.add_classroom_save(USERS[save["user"]], save["content_id"], state)


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


def challenge_id(value):
    if value in (None, "", "free"):
        return FREE_PLAY
    try:
        return int(value)
    except (TypeError, ValueError):
        raise PlatformError("That challenge doesn't exist.", "not_found", 404)


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

    def chunks(self):
        left = int(self.headers.get("Content-Length") or 0)
        while left > 0:
            chunk = self.rfile.read(min(install.CHUNK, left))
            if not chunk:
                break
            left -= len(chunk)
            yield chunk

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
                return self.api(method, path[len("/api/"):], query, player, name)
        except PlatformError as e:
            extra = {"fields": e.fields} if e.fields else {}
            return self.json(e.status, dict({"error": e.code, "message": str(e)}, **extra))
        except install.InstallError as e:
            return self.json(400, {"error": "install_failed", "message": str(e)})
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
        if game is None or game.manifest is None or game.is_classroom:
            return self.send(403, "This game link has expired.", "text/plain")
        if file_path == views_common.SDK_PATH:
            with open(os.path.join(ASSETS, "sdk.js"), "rb") as f:
                found = (f.read(), "text/javascript")
        elif file_path.startswith(views_common.WIKI_PREFIX):
            found = views_common.wiki_file(service, game, file_path[len(views_common.WIKI_PREFIX):])
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
        if game is None or game.manifest is None:
            raise PlatformError("That game isn't on this device.", "not_found", 404)
        if playable and game.is_classroom:
            raise PlatformError("This is a Classroom Game. Open it from Learn.", "classroom_game", 409)
        if playable and not game.playable:
            raise PlatformError(" ".join(game.problems), "unplayable", 409)
        return game

    def class_users(self, player, class_id):
        if not class_id:
            return None
        if not player.can_manage(class_id):
            raise PlatformError("You don't coach that class.", "forbidden", 403)
        return [(USERS[k].id, USERS[k].name) for k in CLASS_MEMBERS]

    def csv(self, text):
        self.send(200, text, "text/csv; charset=utf-8", {"Content-Disposition": 'attachment; filename="results.csv"'})

    @staticmethod
    def require(player, coach=False, admin=False, device_admin=False, name=None):
        if device_admin and name != "admin":
            raise PlatformError("Only device administrators can do this.", "forbidden", 403)
        if admin and not player.is_admin:
            raise PlatformError("Only administrators can see this.", "forbidden", 403)
        if coach and not player.is_coach:
            raise PlatformError("Only coaches and administrators can do this.", "forbidden", 403)

    def api(self, method, path, query, player, name):
        get, post = method == "GET", method == "POST"

        # ---- not about one game
        if path == "games" and get:
            return self.json(200, {
                "me": {"name": player.name, "role": player.role, "can_install": name == "admin"},
                "platform": {"version": __version__, "api": API_VERSION},
                "games": [views_common.card(service, g, player) for g in registry.discover()
                          if g.manifest is not None or player.is_admin],
            })
        if path == "classes" and get:
            self.require(player, coach=True)
            classes = {k: v for k, v in CLASSES.items() if player.can_manage(k)}
            return self.json(200, {"classes": [{"id": k, "name": v} for k, v in classes.items()],
                                   "whole_facility": player.coach_class_ids is None})
        if path == "status" and get:
            self.require(player, admin=True)
            found = []
            for g in registry.discover(refresh=True):
                info = g.describe()
                if g.manifest is not None and g.origin == "installed":
                    info["previous_version"] = install.previous_version(g.manifest.id)
                    info["removable"] = True
                found.append(info)
            return self.json(200, {
                "platform": {"version": __version__, "api": API_VERSION}, "can_install": name == "admin",
                "games": found, "data_sources": registry.data_sources(),
                "data_sources_file": registry.data_sources_file(), "zim_files": registry.zim_candidates(),
                "games_dir": registry.games_dir(), "local_dirs": registry.local_game_dirs(),
                "max_upload_mb": install.MAX_UPLOAD_BYTES // (1024 * 1024),
            })
        if path == "install" and post:
            self.require(player, device_admin=True, name=name)
            return self.json(201, install.install(install.save_upload(self.chunks())))
        if path == "data-sources" and post:
            self.require(player, device_admin=True, name=name)
            data = self.body()
            value = (data.get("path") or "").strip()
            if data.get("name") != "wikipedia":
                raise PlatformError("Unknown data source.", "bad_request")
            if value and not os.path.exists(value):
                raise PlatformError("There's no .zim file at %s." % value, "not_found", 400, fields={"path": "File not found."})
            registry.set_data_source("wikipedia", value or None)
            return self.json(200, {"data_sources": registry.data_sources()})
        if path == "article-lists":
            self.require(player, coach=True)
            if post:
                return self.json(201, service.save_article_list(player, self.body()))
            return self.json(200, {"lists": service.article_lists(player.facility_id)})
        m = re.match(r"^article-lists/(\d+)(/delete)?$", path)
        if m:
            self.require(player, coach=True)
            list_id = int(m.group(1))
            if m.group(2) and post:
                return self.json(200, service.delete_article_list(player, list_id))
            if post:
                return self.json(200, service.save_article_list(player, self.body(), list_id))
            game = registry.get(query["game"]) if query.get("game") else None
            return self.json(200, service.article_list(player.facility_id, list_id, game))

        # ---- one game
        m = re.match(r"^games/([a-z]-[a-z0-9._-]{1,100})(/.*)?$", path)
        if not m:
            raise PlatformError("Not found.", "not_found", 404)
        key, rest = m.group(1), (m.group(2) or "")
        cid = challenge_id(query.get("challenge"))
        if rest == "" and get:
            game = self.game(key)
            payload = views_common.session(service, game, player, cid)
            payload["play_url"] = "play/%s/" % sign({"k": game.key, "u": player.id})
            return self.json(200, payload)
        if rest == "/icon":
            data, ctype = views_common.icon(self.game(key, playable=False))
            return self.send(200, data, ctype)
        if rest == "/attempts" and post:
            data = self.body()
            return self.json(201, service.start(self.game(key), player, challenge_id(data.get("challenge")),
                                                resume=bool(data.get("resume", True))))
        m = re.match(r"^/attempts/(\d+)/(moves|finish|abandon)$", rest)
        if m and post:
            attempt_id, action = int(m.group(1)), m.group(2)
            game, data = self.game(key, playable=action != "abandon"), self.body()
            if action == "moves":
                return self.json(200, service.move(game, player, attempt_id, data.get("type"), data.get("data")))
            if action == "finish":
                return self.json(200, service.finish(game, player, attempt_id, data))
            return self.json(200, service.abandon(game, player, attempt_id))
        if rest == "/state":
            game = self.game(key)
            if post:
                return self.json(200, service.set_state(game, player, self.body().get("data")))
            return self.json(200, {"data": service.get_state(game, player)})
        if rest == "/scoreboard" and get:
            users = self.class_users(player, query.get("class")) if player.is_coach else None
            ids = {u for u, _ in users} if users else None
            return self.json(200, service.scoreboard(self.game(key, playable=False), player, cid, user_ids=ids))
        if rest == "/mine" and get:
            return self.json(200, {"attempts": service.my_attempts(self.game(key, playable=False), player, cid)})
        if rest == "/boards" and get:
            users = self.class_users(player, query.get("class")) if player.is_coach else None
            ids = {u for u, _ in users} if users else None
            data = service.classroom_scoreboards(self.game(key, playable=False), player, user_ids=ids)
            if query.get("format") == "csv":
                self.require(player, coach=True)
                return self.csv(views_common.scoreboards_csv(data))
            return self.json(200, data)

        # ---- coaches
        self.require(player, coach=True)
        game = self.game(key, playable=False)
        if rest == "/settings":
            if post:
                data = self.body()
                service.save_settings(game, player.facility_id, data.get("platform"), data.get("game"), player.id)
            p, g = service.settings(game, player.facility_id)
            return self.json(200, {"schema": service.schema(game, player.facility_id), "values": {"platform": p, "game": g}})
        if rest == "/results" and get:
            class_id = query.get("class")
            if cid is not FREE_PLAY:
                c = store.challenge_get(cid)
                class_id = c.class_id if c else class_id
            data = service.coach_results(game, player, cid, self.class_users(player, class_id))
            if query.get("format") == "csv":
                return self.csv(views_common.results_csv(data))
            return self.json(200, data)
        m = re.match(r"^/results/([0-9a-f]{32})/reset$", rest)
        if m and post:
            return self.json(200, service.reset(game, player.facility_id, m.group(1), challenge_id(self.body().get("challenge"))))
        classes = {k: v for k, v in CLASSES.items() if player.can_manage(k)}
        if rest == "/challenges":
            if post:
                return self.json(201, service.save_challenge(game, player, self.body(), classes))
            return self.json(200, {
                "challenges": [c for c in service.challenges_for(game, player, include_old=True) if c["can_manage"]],
                "schema": service.schema(game, player.facility_id)["game"],
                "classes": [{"id": k, "name": v} for k, v in classes.items()],
            })
        m = re.match(r"^/challenges/(\d+)(/delete)?$", rest)
        if m and post:
            if m.group(2):
                return self.json(200, service.delete_challenge(game, player, int(m.group(1))))
            return self.json(200, service.save_challenge(game, player, self.body(), classes, int(m.group(1))))
        if rest == "/articles" and get:
            found = service.suggest_articles(game, player.facility_id, query.get("q", "")[:100], query.get("list"))
            return self.json(200, {"articles": found})

        # ---- device administrators
        if rest in ("/remove", "/restore") and post:
            self.require(player, device_admin=True, name=name)
            if rest == "/remove":
                return self.json(200, install.remove(game.manifest.id))
            return self.json(200, install.restore_previous(game.manifest.id))
        raise PlatformError("Not found.", "not_found", 404)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Preview Kolibri Games without Kolibri.")
    parser.add_argument("folders", nargs="*", help="Folders containing games (game folders or .zip files).")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--wikipedia", help="A Wikipedia .zim file (or a folder like examples/tiny-wiki) for Wiki BLAZE.")
    parser.add_argument("--classroom", help="JSON file with Classroom Game resources and pretend saved data.")
    args = parser.parse_args(argv)
    if args.folders:
        os.environ["KOLIBRI_GAMES_PATH"] = os.pathsep.join(os.path.abspath(f) for f in args.folders)
    # Games installed through the Setup page go into a temporary folder.
    os.environ.setdefault("KOLIBRI_HOME", tempfile.mkdtemp(prefix="kolibri-games-preview-"))
    if args.wikipedia:
        os.environ["KOLIBRI_GAMES_DATA_WIKIPEDIA"] = os.path.abspath(args.wikipedia)
    if args.classroom:
        load_classroom(args.classroom)
    games = registry.discover(refresh=True)
    print("Kolibri Games preview %s" % __version__)
    for g in games:
        print("  %s %s%s" % ("ok" if g.playable else "!!", g.title, "" if g.playable else ": " + " ".join(g.problems)))
    if not games:
        print("  No games found. Pass a folder that contains game folders or .zip files.")
    print("Open http://%s:%d/" % (args.host, args.port))
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
