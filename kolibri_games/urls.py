"""
All routes live under the plugin's own prefix (e.g. /kolibri/en/kolibri_games/),
so the page can use relative URLs and never needs to know where Kolibri put it.
"""
from django.urls import re_path

from . import views

app_name = "kolibri_games"

KEY = r"(?P<key>[a-z]-[a-z0-9._-]{1,100})"
ATTEMPT = r"(?P<attempt_id>\d+)"

urlpatterns = [
    re_path(r"^$", views.index, name="index"),
    re_path(r"^assets/(?P<name>[a-z]+\.(?:js|css))$", views.asset, name="asset"),
    re_path(r"^play/(?P<token>[A-Za-z0-9_\-:.]+)/(?P<path>.*)$", views.play_file, name="play_file"),
    re_path(r"^api/games$", views.games, name="games"),
    re_path(r"^api/classes$", views.classes, name="classes"),
    re_path(r"^api/status$", views.status, name="status"),
    re_path(r"^api/games/%s$" % KEY, views.game_session, name="game"),
    re_path(r"^api/games/%s/icon$" % KEY, views.icon, name="icon"),
    re_path(r"^api/games/%s/attempts$" % KEY, views.start, name="start"),
    re_path(r"^api/games/%s/attempts/%s/events$" % (KEY, ATTEMPT), views.event, name="event"),
    re_path(r"^api/games/%s/attempts/%s/finish$" % (KEY, ATTEMPT), views.finish, name="finish"),
    re_path(r"^api/games/%s/attempts/%s/abandon$" % (KEY, ATTEMPT), views.abandon, name="abandon"),
    re_path(r"^api/games/%s/call$" % KEY, views.call, name="call"),
    re_path(r"^api/games/%s/leaderboard$" % KEY, views.leaderboard, name="leaderboard"),
    re_path(r"^api/games/%s/scoreboards$" % KEY, views.scoreboards, name="scoreboards"),
    re_path(r"^api/games/%s/mine$" % KEY, views.mine, name="mine"),
    re_path(r"^api/games/%s/state$" % KEY, views.state, name="state"),
    re_path(r"^api/games/%s/settings$" % KEY, views.settings, name="settings"),
    re_path(r"^api/games/%s/results$" % KEY, views.results, name="results"),
    re_path(r"^api/games/%s/results/(?P<user_id>[0-9a-f]{32})/reset$" % KEY, views.reset, name="reset"),
]
