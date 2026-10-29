"""
HTTP layer inside Kolibri: the games page, its JSON API, and the game file
server. The rules themselves live in service.py; devserver.py serves the same
API without Kolibri, so change both together.

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

from . import API_VERSION, __version__, install, registry
from .service import FREE_PLAY, GameService, PlatformError, Player
from .store_django import DjangoStore
from .views_common import (
    ASSET_TYPES,
    SDK_PATH,
    WIKI_PREFIX,
    card,
    csv_response_headers,
    game_file_headers,
    icon as icon_for,
    results_csv,
    scoreboards_csv,
    session,
    wiki_file,
)

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


def _learner_classes(user):
    """Ids of the classes the user is a member of."""
    try:
        from kolibri.core.auth.models import Membership

        return {
            str(c) for c in Membership.objects.filter(user_id=user.id, collection__kind="classroom")
            .values_list("collection_id", flat=True)
        }
    except Exception:
        return set()


def player_for(user):
    facility_id = str(getattr(user, "facility_id", "") or "")
    roles = _roles(user)
    is_admin = bool(getattr(user, "is_superuser", False)) or ("admin", facility_id) in roles
    is_coach = any(kind in COACH_KINDS for kind, _ in roles)
    if is_admin or any(kind in COACH_KINDS and coll == facility_id for kind, coll in roles):
        coach_classes = None  # every class in the facility
    else:
        coach_classes = {coll for kind, coll in roles if kind in COACH_KINDS}
    name = getattr(user, "full_name", "") or getattr(user, "username", "") or "Player"
    return Player(
        str(user.id), name, facility_id, is_coach=is_coach, is_admin=is_admin,
        class_ids=_learner_classes(user), coach_class_ids=coach_classes,
    )


def can_install(user):
    """Only device administrators (Kolibri's "super admins" or people who manage content) install games."""
    return bool(getattr(user, "is_superuser", False) or getattr(user, "can_manage_content", False))


def api(view=None, coach=False, admin=False, device_admin=False):
    """Signed-in users only; maps PlatformError to JSON; optional role checks."""

    def decorate(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.user.is_anonymous:
                return _error("Sign in to Kolibri to play.", 401, "signin")
            player = player_for(request.user)
            if device_admin and not can_install(request.user):
                return _error("Only device administrators can do this.", 403, "forbidden")
            if admin and not player.is_admin:
                return _error("Only administrators can see this.", 403, "forbidden")
            if coach and not player.is_coach:
                return _error("Only coaches and administrators can do this.", 403, "forbidden")
            # No surrounding transaction on purpose: some errors (like "time's up")
            # are raised after saving a change that must be kept.
            try:
                return view(request, player, *args, **kwargs)
            except PlatformError as e:
                extra = {"fields": e.fields} if e.fields else {}
                return _error(str(e), e.status, e.code, **extra)
            except install.InstallError as e:
                return _error(str(e), 400, "install_failed")

        return wrapper

    return decorate(view) if view is not None else decorate


def _game(key, playable=True):
    game = registry.get(key)
    if game is None or game.manifest is None:
        raise PlatformError("That game isn't on this device.", "not_found", 404)
    if playable and game.is_classroom:
        raise PlatformError("This is a Classroom Game. Open it from Learn.", "classroom_game", 409)
    if playable and not game.playable:
        raise PlatformError(" ".join(game.problems) or "This game can't be played.", "unplayable", 409)
    return game


def _challenge_id(value):
    """A challenge id from a query string or request body; None means free play."""
    if value in (None, "", "free"):
        return FREE_PLAY
    try:
        return int(value)
    except (TypeError, ValueError):
        raise PlatformError("That challenge doesn't exist.", "not_found", 404)


def play_token(game, player):
    return signing.dumps({"k": game.key, "u": player.id}, salt=TOKEN_SALT, compress=True)


def _kolibri_root():
    try:
        from kolibri.utils.conf import OPTIONS

        return OPTIONS["Deployment"]["URL_PATH_PREFIX"] or "/"
    except Exception:
        return "/"


def _classes_for(player):
    """{class id: name} for the classes this coach can set challenges for."""
    from kolibri.core.auth.models import Classroom

    qs = Classroom.objects.filter(parent_id=player.facility_id)
    if player.coach_class_ids is not None:
        qs = qs.filter(id__in=player.coach_class_ids)
    return {str(c.id): c.name for c in qs.order_by("name")}


def _users_in_class(player, class_id):
    """[(user_id, name)] for a class the coach can see, or None for 'everyone who played'."""
    if not class_id:
        return None
    if not player.can_manage(class_id):
        raise PlatformError("You don't coach that class.", "forbidden", 403)
    from kolibri.core.auth.models import FacilityUser, Membership

    ids = list(Membership.objects.filter(collection_id=class_id).values_list("user_id", flat=True))
    users = FacilityUser.objects.filter(id__in=ids, facility_id=player.facility_id).values("id", "full_name", "username")
    return sorted([(str(u["id"]), u["full_name"] or u["username"]) for u in users], key=lambda u: u[1].lower())


def _csv(text, game, what):
    response = HttpResponse(text, content_type="text/csv; charset=utf-8")
    for header, value in csv_response_headers(game, what).items():
        response[header] = value
    return response


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
    if game is None or game.manifest is None or game.is_classroom:
        return HttpResponse(status=404)
    if path == SDK_PATH:
        with open(os.path.join(ASSETS, "sdk.js"), "rb") as f:
            found = (f.read(), "text/javascript")
    elif path.startswith(WIKI_PREFIX):
        found = wiki_file(service, game, path[len(WIKI_PREFIX):])
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


# ------------------------------------------------------------- games list


@require_GET
@api
def games(request, player):
    found = registry.discover()
    return JsonResponse(
        {
            "me": {"name": player.name, "role": player.role, "can_install": can_install(request.user)},
            "platform": {"version": __version__, "api": API_VERSION},
            "games": [card(service, g, player) for g in found if g.manifest is not None or player.is_admin],
        }
    )


@require_GET
@api
def icon(request, player, key):
    game = registry.get(key)
    if game is None or game.manifest is None:
        return HttpResponse(status=404)
    data, ctype = icon_for(game)
    response = HttpResponse(data, content_type=ctype)
    response["Cache-Control"] = "private, max-age=3600"
    response["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"
    return response


# ------------------------------------------------------------------ playing


@require_GET
@api
def game_session(request, player, key):
    game = _game(key)
    payload = session(service, game, player, _challenge_id(request.GET.get("challenge")))
    payload["play_url"] = "play/%s/" % play_token(game, player)
    return JsonResponse(payload)


@require_POST
@api
def start(request, player, key):
    data = _body(request)
    result = service.start(_game(key), player, _challenge_id(data.get("challenge")), resume=bool(data.get("resume", True)))
    return JsonResponse(result, status=201)


@require_POST
@api
def move(request, player, key, attempt_id):
    data = _body(request)
    return JsonResponse(service.move(_game(key), player, int(attempt_id), data.get("type"), data.get("data")))


@require_POST
@api
def finish(request, player, key, attempt_id):
    return JsonResponse(service.finish(_game(key), player, int(attempt_id), _body(request)))


@require_POST
@api
def abandon(request, player, key, attempt_id):
    return JsonResponse(service.abandon(_game(key, playable=False), player, int(attempt_id)))


@require_http_methods(["GET", "POST"])
@api
def state(request, player, key):
    game = _game(key)
    if request.method == "POST":
        return JsonResponse(service.set_state(game, player, _body(request).get("data")))
    return JsonResponse({"data": service.get_state(game, player)})


# ------------------------------------------------------------------ results


@require_GET
@api
def scoreboard(request, player, key):
    game = _game(key, playable=False)
    user_ids = None
    class_id = request.GET.get("class")
    if class_id and player.is_coach:
        user_ids = {u for u, _ in _users_in_class(player, class_id)}
    return JsonResponse(service.scoreboard(game, player, _challenge_id(request.GET.get("challenge")), user_ids=user_ids))


@require_GET
@api
def mine(request, player, key):
    game = _game(key, playable=False)
    return JsonResponse({"attempts": service.my_attempts(game, player, _challenge_id(request.GET.get("challenge")))})


@require_GET
@api(coach=True)
def results(request, player, key):
    game = _game(key, playable=False)
    challenge_id = _challenge_id(request.GET.get("challenge"))
    class_id = request.GET.get("class") or ""
    if challenge_id is not FREE_PLAY:
        c = service.store.challenge_get(challenge_id)
        class_id = c.class_id if c is not None else class_id  # a challenge's results are its class
    elif player.coach_class_ids is not None and not class_id:
        raise PlatformError("Choose one of your classes.", "choose_class", 400)
    data = service.coach_results(game, player, challenge_id, _users_in_class(player, class_id))
    if request.GET.get("format") == "csv":
        return _csv(results_csv(data), game, "results")
    return JsonResponse(data)


@require_POST
@api(coach=True)
def reset(request, player, key, user_id):
    game = _game(key, playable=False)
    challenge_id = _challenge_id(_body(request).get("challenge"))
    if player.coach_class_ids is not None:
        from kolibri.core.auth.models import Membership

        if not Membership.objects.filter(user_id=user_id, collection_id__in=player.coach_class_ids).exists():
            raise PlatformError("That learner isn't in one of your classes.", "forbidden", 403)
    return JsonResponse(service.reset(game, player.facility_id, user_id, challenge_id))


@require_GET
@api
def classroom_boards(request, player, key):
    """Scoreboards of a Classroom Game."""
    game = _game(key, playable=False)
    user_ids = None
    class_id = request.GET.get("class")
    if class_id and player.is_coach:
        user_ids = {u for u, _ in _users_in_class(player, class_id)}
    data = service.classroom_scoreboards(game, player, user_ids=user_ids)
    if request.GET.get("format") == "csv":
        if not player.is_coach:
            raise PlatformError("Only coaches and administrators can do this.", "forbidden", 403)
        return _csv(scoreboards_csv(data), game, "scores")
    return JsonResponse(data)


# ------------------------------------------------------- settings, challenges


@require_http_methods(["GET", "POST"])
@api(coach=True)
def settings(request, player, key):
    game = _game(key, playable=False)
    if request.method == "POST":
        data = _body(request)
        service.save_settings(game, player.facility_id, data.get("platform"), data.get("game"), player.id)
    platform_values, game_values = service.settings(game, player.facility_id)
    return JsonResponse({"schema": service.schema(game, player.facility_id), "values": {"platform": platform_values, "game": game_values}})


@require_http_methods(["GET", "POST"])
@api(coach=True)
def challenges(request, player, key):
    game = _game(key, playable=False)
    if request.method == "POST":
        return JsonResponse(service.save_challenge(game, player, _body(request), _classes_for(player)), status=201)
    return JsonResponse({
        "challenges": [c for c in service.challenges_for(game, player, include_old=True) if c["can_manage"]],
        "schema": service.schema(game, player.facility_id)["game"],
        "classes": [{"id": k, "name": v} for k, v in _classes_for(player).items()],
    })


@require_POST
@api(coach=True)
def challenge(request, player, key, challenge_id):
    game = _game(key, playable=False)
    return JsonResponse(service.save_challenge(game, player, _body(request), _classes_for(player), int(challenge_id)))


@require_POST
@api(coach=True)
def challenge_delete(request, player, key, challenge_id):
    return JsonResponse(service.delete_challenge(_game(key, playable=False), player, int(challenge_id)))


@require_GET
@api(coach=True)
def articles(request, player, key):
    """Article suggestions while a coach types a start or goal."""
    game = _game(key, playable=False)
    found = service.suggest_articles(game, player.facility_id, request.GET.get("q", "")[:100], request.GET.get("list"))
    return JsonResponse({"articles": found})


# ------------------------------------------------------------ article lists


@require_http_methods(["GET", "POST"])
@api(coach=True)
def article_lists(request, player):
    if request.method == "POST":
        return JsonResponse(service.save_article_list(player, _body(request)), status=201)
    return JsonResponse({"lists": service.article_lists(player.facility_id)})


@require_http_methods(["GET", "POST"])
@api(coach=True)
def article_list(request, player, list_id):
    if request.method == "POST":
        return JsonResponse(service.save_article_list(player, _body(request), int(list_id)))
    game = registry.get(request.GET.get("game")) if request.GET.get("game") else None
    return JsonResponse(service.article_list(player.facility_id, int(list_id), game))


@require_POST
@api(coach=True)
def article_list_delete(request, player, list_id):
    return JsonResponse(service.delete_article_list(player, int(list_id)))


# -------------------------------------------------------------------- setup


@require_GET
@api(coach=True)
def classes(request, player):
    return JsonResponse({
        "classes": [{"id": k, "name": v} for k, v in _classes_for(player).items()],
        "whole_facility": player.coach_class_ids is None,
    })


@require_GET
@api(admin=True)
def status(request, player):
    games_found = []
    for g in registry.discover(refresh=True):
        info = g.describe()
        if g.manifest is not None and g.origin == "installed":
            info["previous_version"] = install.previous_version(g.manifest.id)
            info["removable"] = True
        games_found.append(info)
    return JsonResponse({
        "platform": {"version": __version__, "api": API_VERSION},
        "can_install": can_install(request.user),
        "games": games_found,
        "data_sources": registry.data_sources(),
        "data_sources_file": registry.data_sources_file(),
        "zim_files": registry.zim_candidates(),
        "games_dir": registry.games_dir(),
        "local_dirs": registry.local_game_dirs(),
        "max_upload_mb": install.MAX_UPLOAD_BYTES // (1024 * 1024),
    })


@require_POST
@api(device_admin=True)
def install_game(request, player):
    """The body is the game's .zip itself (not a form), read in pieces so big files don't fill the memory."""

    def chunks():
        while True:
            chunk = request.read(install.CHUNK)
            if not chunk:
                break
            yield chunk

    path = install.save_upload(chunks())
    return JsonResponse(install.install(path), status=201)


@require_POST
@api(device_admin=True)
def remove_game(request, player, key):
    game = _game(key, playable=False)
    return JsonResponse(install.remove(game.manifest.id))


@require_POST
@api(device_admin=True)
def restore_game(request, player, key):
    game = _game(key, playable=False)
    return JsonResponse(install.restore_previous(game.manifest.id))


@require_POST
@api(device_admin=True)
def data_source(request, player):
    data = _body(request)
    name, path = data.get("name"), (data.get("path") or "").strip()
    if name != "wikipedia":
        raise PlatformError("Unknown data source.", "bad_request")
    if path and not (os.path.isfile(path) and path.lower().endswith(".zim")) and not os.path.isdir(path):
        raise PlatformError("There's no .zim file at %s." % path, "not_found", 400, fields={"path": "File not found."})
    registry.set_data_source(name, path or None)
    return JsonResponse({"data_sources": registry.data_sources()})
