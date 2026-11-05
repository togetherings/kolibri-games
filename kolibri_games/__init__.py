"""
Kolibri Games: a platform for learning games inside Kolibri, with Kolibri
sign-ins, scoreboards, class challenges and coach tools.

There are three kinds of game, all zipped HTML5 apps with a
``kolibri-game.json`` manifest inside (see manifest.py):

* Saved Games keep each learner's progress.
* Scored Games also report a score for scoreboards.
* Server Games need this plugin's server to play (Wiki BLAZE, BeaconHunt).

Any of them can be installed by a device administrator and played on the
games page (see install.py). Saved and Scored Games can also go in Kolibri
channels and be played in Learn, including offline in the Kolibri app; the
games page shows Scored Games' scoreboards from the scores they save (see
channel.py). Saved and Scored Games are made with edugame-kit
(github.com/togetherings/edugame-kit), which also packs them for other systems.
"""

__version__ = "0.2.0"

#: Version of the messages between a game and the games page (see sdk.js and
#: docs/GAME_FORMAT.md). Games and the page must use the same number.
API_VERSION = 2

#: Version of the manifest format this platform understands.
MANIFEST_FORMAT = 1
