from kolibri.plugins import KolibriPluginBase


class KolibriGames(KolibriPluginBase):
    """Kolibri Games: sandboxed games with sign-ins, scoring, leaderboards and coach tools."""

    # Served under Kolibri's language prefix, e.g. /kolibri/en/kolibri_games/
    translated_view_urls = "urls"
