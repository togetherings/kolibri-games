from kolibri.core.hooks import NavigationHook
from kolibri.plugins import KolibriPluginBase
from kolibri.plugins.hooks import register_hook


class KolibriGames(KolibriPluginBase):
    """Kolibri Games: sandboxed games with sign-ins, scoring, leaderboards and coach tools."""

    # Served under Kolibri's language prefix, e.g. /kolibri/en/kolibri_games/
    translated_view_urls = "urls"


@register_hook
class GamesNavItem(NavigationHook):
    """Adds a "Games" link to Kolibri's side menu.

    Kolibri normally builds menu entries with its JavaScript build tools. This
    plugin ships a small hand-written script instead (static/kolibri_games.side_nav/)
    plus the build-info file Kolibri looks for (build/kolibri_games.side_nav_stats.json),
    so no build step is needed. If a future Kolibri changes how menu entries
    work, the script does nothing and the games page still works.
    """

    bundle_id = "side_nav"

    @property
    def plugin_data(self):
        from django.urls import NoReverseMatch, reverse

        try:
            url = reverse("kolibri:kolibri_games:index")
        except NoReverseMatch:
            url = None
        return {"url": url, "label": "Games"}
