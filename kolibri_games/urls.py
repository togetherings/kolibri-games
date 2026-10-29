"""
All routes live under the plugin's own prefix (e.g. /kolibri/en/kolibri_games/),
so the page can use relative URLs and never needs to know where Kolibri put it.
devserver.py answers the same addresses without Kolibri.
"""
from django.urls import re_path

from . import views

app_name = "kolibri_games"

KEY = r"(?P<key>[a-z]-[a-z0-9._-]{1,100})"
ATTEMPT = r"(?P<attempt_id>\d+)"
CHALLENGE = r"(?P<challenge_id>\d+)"
LIST = r"(?P<list_id>\d+)"
GAME = r"^api/games/%s" % KEY

urlpatterns = [
    re_path(r"^$", views.index, name="index"),
    re_path(r"^assets/(?P<name>[a-z]+\.(?:js|css))$", views.asset, name="asset"),
    re_path(r"^play/(?P<token>[A-Za-z0-9_\-:.]+)/(?P<path>.*)$", views.play_file, name="play_file"),
    # everyone
    re_path(r"^api/games$", views.games, name="games"),
    re_path(GAME + r"$", views.game_session, name="game"),
    re_path(GAME + r"/icon$", views.icon, name="icon"),
    re_path(GAME + r"/attempts$", views.start, name="start"),
    re_path(GAME + r"/attempts/%s/moves$" % ATTEMPT, views.move, name="move"),
    re_path(GAME + r"/attempts/%s/finish$" % ATTEMPT, views.finish, name="finish"),
    re_path(GAME + r"/attempts/%s/abandon$" % ATTEMPT, views.abandon, name="abandon"),
    re_path(GAME + r"/state$", views.state, name="state"),
    re_path(GAME + r"/scoreboard$", views.scoreboard, name="scoreboard"),
    re_path(GAME + r"/mine$", views.mine, name="mine"),
    re_path(GAME + r"/boards$", views.classroom_boards, name="classroom_boards"),
    # coaches
    re_path(r"^api/classes$", views.classes, name="classes"),
    re_path(GAME + r"/settings$", views.settings, name="settings"),
    re_path(GAME + r"/results$", views.results, name="results"),
    re_path(GAME + r"/results/(?P<user_id>[0-9a-f]{32})/reset$", views.reset, name="reset"),
    re_path(GAME + r"/challenges$", views.challenges, name="challenges"),
    re_path(GAME + r"/challenges/%s$" % CHALLENGE, views.challenge, name="challenge"),
    re_path(GAME + r"/challenges/%s/delete$" % CHALLENGE, views.challenge_delete, name="challenge_delete"),
    re_path(GAME + r"/articles$", views.articles, name="articles"),
    re_path(r"^api/article-lists$", views.article_lists, name="article_lists"),
    re_path(r"^api/article-lists/%s$" % LIST, views.article_list, name="article_list"),
    re_path(r"^api/article-lists/%s/delete$" % LIST, views.article_list_delete, name="article_list_delete"),
    # administrators
    re_path(r"^api/status$", views.status, name="status"),
    re_path(r"^api/install$", views.install_game, name="install"),
    re_path(r"^api/data-sources$", views.data_source, name="data_source"),
    re_path(GAME + r"/remove$", views.remove_game, name="remove"),
    re_path(GAME + r"/restore$", views.restore_game, name="restore"),
]
