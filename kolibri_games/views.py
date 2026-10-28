"""
HTTP layer: the games page, its JSON API, and the game file server.

Game files are served under ``play/<token>/`` where the token is signed by the
server and names the game and the player. Games run in a sandboxed iframe with
an opaque origin, so they never get the learner's Kolibri session; they talk to
the trusted page around them with postMessage (see assets/app.js), and that
page calls this API.
"""
import json
import os
from functools import wraps
from html import escape

from django.core import signing
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import API_VERSION, __version__, registry, validators
from .service import GameService, PlatformError, Player
from .store_django import DjangoStore
from .views_common import ASSET_TYPES, SDK_PATH, card, game_file_headers, icon as icon_for, results_csv, session

ASSETS = os.path.join(os.path.dirname(__file__), "assets")
TOKEN_SALT = "kolibri_games.play"
TOKEN_MAX_AGE = 12 * 3600
COACH_KINDS = ("coach", "classroom assignable coach", "admin")

service = GameService(DjangoStore())


# ------------------------------------------------------------------ helpers


def _error(message, status=400, code="error", **extra):
    payload = {"error": code, "message": message}
    payload.update(extra)
    return JsonResponse(payload, status=status)


def _body(request):
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except ValueError:
        raise PlatformError("The request wasn't valid JSON.", "bad_request")
    if not isinstance(data, dict):
        raise PlatformError("The request wasn't a JSON object.", "bad_request")
    return data


def _roles(user):
    """Set of (kind, collection_id) for the user's Kolibri roles."""
    try:
        from kolibri.core.auth.models import Role

        return {(kind, str(coll)) for kind, coll in Role.objects.filter(user_id=user.id).values_list("kind", "collection_id")}
    except Exception:
        return set()


def player_for(user):
    facility_id = str(getattr(user, "facility_id", "") or "")
    roles = _roles(user)
    is_admin = bool(getattr(user, "is_superuser", False)) or ("admin", facility_id) in roles
    is_coach = any(kind in COACH_KINDS for kind, _ in roles)
    name = getattr(user, "full_name", "") or getattr(user, "username", "") or "Player"
    return Player(str(user.id), name, facility_id, is_coach=is_coach, is_admin=is_admin)


def coach_class_scope(user, player):
    """None if the coach can see the whole facility, else the set of classroom ids they coach."""
    if player.is_admin:
        return None
    roles = _roles(user)
    if any(kind in COACH_KINDS and coll == player.facility_id for kind, coll in roles):
        return None
    return {coll for kind, coll in roles if kind in COACH_KINDS}


def api(view=None, coach=False, admin=False):
    """Signed-in users only; maps PlatformError to JSON; optional role checks."""

    def decorate(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.user.is_anonymous:
                return _error("Sign in to Kolibri to play.", 401, "signin")
            player = player_for(request.user)
            if admin and not player.is_admin:
                return _error("Only administrators can see this.", 403, "forbidden")
            if coach and not player.is_coach:
                return _error("Only coaches and administrators can do this.", 403, "forbidden")
            # No surrounding transaction on purpose: some errors (like "time's up")
            # are raised after saving a change that must be kept.
            try:
                return view(request, player, *args, **kwargs)
            except PlatformError as e:
                extra = {"fields": e.fields} if getattr(e, "fields", None) else {}
                return _error(str(e), e.status, e.code, **extra)

        return wrapper

    return decorate(view) if view is not None else decorate


def _game(key, playable=True):
    game = registry.get(key)
    if game is None or game.manifest is None:
        raise PlatformError("That game isn't on this device.", "not_found", 404)
    if playable and not game.playable:
        raise PlatformError(" ".join(game.problems) or "This game can't be played.", "unplayable", 409)
    return game


def play_token(game, player):
    return signing.dumps({"k": game.key, "u": player.id}, salt=TOKEN_SALT, compress=True)


def _kolibri_root():
    try:
        from kolibri.utils.conf import OPTIONS

        return OPTIONS["Deployment"]["URL_PATH_PREFIX"] or "/"
    except Exception:
        return "/"


def _users_in_scope(player, scope, class_id):
    """[(user_id, name)] for the chosen class, or None for 'everyone who played'."""
    if not class_id:
        return None
    if scope is not None and class_id not in scope:
        raise PlatformError("You don't coach that class.", "forbidden", 403)
    from kolibri.core.auth.models import FacilityUser, Membership

    ids = list(Membership.objects.filter(collection_id=class_id).values_list("user_id", flat=True))
    users = FacilityUser.objects.filter(id__in=ids, facility_id=player.facility_id).values("id", "full_name", "username")
    return sorted([(str(u["id"]), u["full_name"] or u["username"]) for u in users], key=lambda u: u[1].lower())


# -------------------------------------------------------------------- pages


@require_GET
def index(request):
    with open(os.path.join(ASSETS, "index.html"), encoding="utf-8") as f:
        html = f.read()
    html = (
        html.replace("{{CSRF_TOKEN}}", escape(get_token(request)))
        .replace("{{VERSION}}", __version__)
        .replace("{{KOLIBRI_ROOT}}", escape(_kolibri_root()))
    )
    response = HttpResponse(html, content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-cache"
    return response


@require_GET
def asset(request, name):
    if name not in ASSET_TYPES:
        return HttpResponse(status=404)
    with open(os.path.join(ASSETS, name), "rb") as f:
        response = HttpResponse(f.read(), content_type=ASSET_TYPES[name])
    response["Cache-Control"] = "no-cache"
    return response


@require_GET
@xframe_options_sameorigin
def play_file(request, token, path=""):
    try:
        claims = signing.loads(token, salt=TOKEN_SALT, max_age=TOKEN_MAX_AGE)
    except signing.BadSignature:
        return HttpResponse(
            "This game link has expired. Go back and open the game again.", status=403, content_type="text/plain"
        )
    game = registry.get(claims.get("k"))
    if game is None or game.manifest is None:
        return HttpResponse(status=404)
    if path == SDK_PATH:
        with open(os.path.join(ASSETS, "sdk.js"), "rb") as f:
            data, mimetype = f.read(), "text/javascript"
    else:
        found = game.source.read(path or game.manifest.entry)
        if found is None:
            return HttpResponse("Not found in this game: %s" % path, status=404, content_type="text/plain")
        data, mimetype = found
    if mimetype.startswith("text/") and "charset" not in mimetype:
        mimetype += "; charset=utf-8"
    response = HttpResponse(data, content_type=mimetype)
    for header, value in game_file_headers().items():
        response[header] = value
    response["Cache-Control"] = "private, max-age=300"
    return response


# ---------------------------------------------------------------------- api


@require_GET
@api
def games(request, player):
    found = registry.discover()
    return JsonResponse(
        {
            "me": {"name": player.name, "role": player.role},
            "platform": {"version": __version__, "api": API_VERSION},
            "games": [card(service, g, player) for g in found if g.manifest is not None or player.is_admin],
        }
    )


@require_GET
@api
def game_session(request, player, key):
    game = _game(key)
    payload = session(service, game, player)
    payload["play_url"] = "play/%s/" % play_token(game, player)
    return JsonResponse(payload)


@require_GET
def icon(request, key):
    if request.user.is_anonymous:
        return HttpResponse(status=401)
    game = registry.get(key)
    if game is None or game.manifest is None:
        return HttpResponse(status=404)
    data, ctype = icon_for(game)
    response = HttpResponse(data, content_type=ctype)
    response["Cache-Control"] = "private, max-age=3600"
    response["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"
    return response


@require_POST
@api
def start(request, player, key):
    data = _body(request)
    return JsonResponse(service.start(_game(key), player, resume=bool(data.get("resume", True))), status=201)


@require_POST
@api
def event(request, player, key, attempt_id):
    data = _body(request)
    return JsonResponse(service.event(_game(key), player, int(attempt_id), data.get("type"), data.get("data")))


@require_POST
@api
def finish(request, player, key, attempt_id):
    return JsonResponse(service.finish(_game(key), player, int(attempt_id), _body(request)))


@require_POST
@api
def abandon(request, player, key, attempt_id):
    return JsonResponse(service.abandon(_game(key, playable=False), player, int(attempt_id)))


@require_POST
@api
def call(request, player, key):
    data = _body(request)
    return JsonResponse(service.call(_game(key), player, data.get("method"), data.get("params")))


@require_GET
@api
def leaderboard(request, player, key):
    game = _game(key, playable=False)
    user_ids = None
    class_id = request.GET.get("class")
    if class_id and player.is_coach:
        users = _users_in_scope(player, coach_class_scope(request.user, player), class_id)
        user_ids = {u for u, _ in users}
    return JsonResponse(service.leaderboard(game, player, limit=50 if player.is_coach else 20, user_ids=user_ids))


@require_GET
@api
def mine(request, player, key):
    return JsonResponse({"attempts": service.my_attempts(_game(key, playable=False), player)})


@require_http_methods(["GET", "POST"])
@api
def state(request, player, key):
    game = _game(key)
    if request.method == "POST":
        return JsonResponse(service.set_state(game, player, _body(request).get("data")))
    return JsonResponse({"data": service.get_state(game, player)})


@require_http_methods(["GET", "POST"])
@api(coach=True)
def settings(request, player, key):
    game = _game(key, playable=False)
    if request.method == "POST":
        data = _body(request)
        service.save_settings(game, player.facility_id, data.get("platform"), data.get("game"), player.id)
    platform_values, game_values = service.settings(game, player.facility_id)
    return JsonResponse({"schema": service.schema(game), "values": {"platform": platform_values, "game": game_values}})


@require_GET
@api(coach=True)
def results(request, player, key):
    game = _game(key, playable=False)
    scope = coach_class_scope(request.user, player)
    class_id = request.GET.get("class") or ""
    if scope is not None and not class_id:
        raise PlatformError("Choose one of your classes.", "choose_class", 400)
    data = service.coach_results(game, player.facility_id, _users_in_scope(player, scope, class_id))
    if request.GET.get("format") == "csv":
        response = HttpResponse(results_csv(data), content_type="text/csv; charset=utf-8")
        safe = "".join(c if c.isalnum() else "-" for c in game.title.lower()).strip("-")
        response["Content-Disposition"] = 'attachment; filename="%s-results.csv"' % (safe or "game")
        return response
    return JsonResponse(data)


@require_POST
@api(coach=True)
def reset(request, player, key, user_id):
    game = _game(key, playable=False)
    scope = coach_class_scope(request.user, player)
    if scope is not None:
        from kolibri.core.auth.models import Membership

        if not Membership.objects.filter(user_id=user_id, collection_id__in=scope).exists():
            raise PlatformError("That learner isn't in one of your classes.", "forbidden", 403)
    return JsonResponse(service.reset(game, player.facility_id, user_id))


@require_GET
@api(coach=True)
def classes(request, player):
    from kolibri.core.auth.models import Classroom

    scope = coach_class_scope(request.user, player)
    qs = Classroom.objects.filter(parent_id=player.facility_id)
    if scope is not None:
        qs = qs.filter(id__in=scope)
    return JsonResponse(
        {"classes": [{"id": str(c.id), "name": c.name} for c in qs.order_by("name")], "whole_facility": scope is None}
    )


@require_GET
@api(admin=True)
def status(request, player):
    return JsonResponse(
        {
            "platform": {"version": __version__, "api": API_VERSION},
            "games": [g.describe() for g in registry.discover(refresh=True)],
            "validators": sorted(validators.registry()),
            "data_sources": registry.data_sources(),
            "data_sources_file": registry.data_sources_file(),
            "local_dirs": registry.local_game_dirs(),
        }
    )
