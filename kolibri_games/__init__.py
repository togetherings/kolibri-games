"""
Kolibri Games: a platform for learning games inside Kolibri, with Kolibri
sign-ins, scoreboards, class challenges and coach tools.

There are two kinds of game. Both are zipped HTML5 apps with a
``kolibri-game.json`` manifest inside:

* Free-play Games are installed into this plugin by a device administrator and
  played on the games page (see install.py).
* Classroom Games are HTML5 apps in Kolibri channels, played in Learn. The
  games page shows scoreboards from the scores they save (see classroom.py).
"""

__version__ = "0.2.0"

#: Version of the messages between a game and the games page (see sdk.js and
#: docs/GAME_FORMAT.md). Games and the page must use the same number.
API_VERSION = 2

#: Version of the manifest format this platform understands.
MANIFEST_FORMAT = 1
