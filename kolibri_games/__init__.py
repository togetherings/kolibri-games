"""
Kolibri Games: a platform for playing sandboxed games inside Kolibri, with
Kolibri sign-ins, server-side scoring, leaderboards and coach tools.

Games are packaged as ZIM files (or plain folders during development) that
contain a ``kolibri-game.json`` manifest.
"""

__version__ = "0.1.1"

#: Version of the game <-> platform message API (see docs/GAME_FORMAT.md).
API_VERSION = 1

#: Version of the manifest format this platform understands.
MANIFEST_FORMAT = 1
