"""
Kolibri Games: a platform for learning games inside Kolibri, with Kolibri
sign-ins, scoreboards, class challenges and coach tools.

There are three kinds of game, all zipped HTML5 apps with a
``kolibri-game.json`` manifest inside (see manifest.py):

* Saved Games keep each learner's progress.
* Scored Games also report scores for scoreboards (see scoring.py).
* Server Games need this plugin's server to play (Wiki BLAZE, BeaconHunt).

Saved and Scored Games are made with EduGame Kit
(github.com/togetherings/edugame-kit) and added to Kolibri through Kolibri
Studio, in channels; learners play them in Learn, also offline in the Kolibri
app, and the games page shows Scored Games' scoreboards from the scores they
save (see channel.py). Server Games, which can't go through Studio, are
installed by a device administrator on the games page (see install.py).
"""

__version__ = "0.2.0"

#: Version of the messages between a game and the games page (see sdk.js and
#: docs/GAME_FORMAT.md). Games and the page must use the same number.
API_VERSION = 2

#: Version of the manifest format this platform understands.
MANIFEST_FORMAT = 1
