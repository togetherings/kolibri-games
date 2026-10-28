"""
kolibri manage kolibri_games_check

Prints the plugin version, where it looks for games, which games it found
(and why any can't be played), installed rule checkers, data sources and the
address of the games page. Exits with status 1 if the page route is missing.
"""
import sys

from django.core.management.base import BaseCommand
from django.urls import get_resolver

from kolibri_games import API_VERSION, __version__, registry, validators, views


def page_routes(patterns, prefix=""):
    found = []
    for p in patterns:
        if hasattr(p, "url_patterns"):
            found += page_routes(p.url_patterns, prefix + str(p.pattern))
        elif getattr(p, "callback", None) is views.index:
            found.append(prefix + str(p.pattern))
    return [r.replace("^", "").replace("$", "") for r in found]


class Command(BaseCommand):
    help = "Check the Kolibri Games setup."

    def handle(self, *args, **options):
        out = self.stdout.write
        out("Kolibri Games %s (game API %d)" % (__version__, API_VERSION))
        out("Local game folders:")
        for d in registry.local_game_dirs():
            out("  %s" % d)
        out("Rule checkers: %s" % (", ".join(sorted(validators.registry())) or "none"))
        sources = registry.data_sources()
        out("Data sources (%s):" % registry.data_sources_file())
        for name, path in sorted(sources.items()):
            out("  %s = %s" % (name, path))
        if not sources:
            out("  none")
        games = registry.discover(refresh=True)
        out("Games found: %d" % len(games))
        for g in games:
            d = g.describe()
            out("  [%s] %s %s (%s, %s) key=%s" % ("ok" if d["playable"] else "!!", d["title"], d["version"] or "",
                                                  d["origin"], d["kind"], d["key"]))
            out("       %s" % d["location"])
            for problem in d["problems"]:
                out("       - %s" % problem)
        routes = page_routes(get_resolver().url_patterns)
        out("Games page:")
        for r in routes:
            out("  /%s" % r)
        if not routes:
            out("  NOT FOUND - is the plugin enabled? (kolibri plugin enable kolibri_games)")
            sys.exit(1)
