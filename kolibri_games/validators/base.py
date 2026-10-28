import random


class ValidatorError(Exception):
    """Raised to reject a move or request. The message is shown to the player."""

    def __init__(self, message, code="rejected"):
        super(ValidatorError, self).__init__(message)
        self.code = code


class ValidatorContext(object):
    """What a validator gets to work with.

    settings     the game's settings for this facility (already validated)
    attempt      attempt number for this player (1 = first)
    rng          a random.Random to use for anything secret
    data         name -> filesystem path for the game's data sources
    elapsed      seconds since the attempt started (server clock)
    """

    def __init__(self, settings=None, attempt=1, rng=None, data=None, elapsed=0.0):
        self.settings = settings or {}
        self.attempt = attempt
        self.rng = rng or random.SystemRandom()
        self.data = data or {}
        self.elapsed = elapsed


class Validator(object):
    """Base class. Override what your game needs.

    ``state`` is a JSON-serialisable dict kept on the server and never sent to
    the browser. Anything the game needs to know goes in the returned
    ``public`` / ``reply`` dicts instead.
    """

    #: Name games use in their manifest.
    name = None

    def start(self, ctx):
        """Begin an attempt. Return {"state": {...}, "public": {...}}."""
        return {"state": {}, "public": {}}

    def resume(self, ctx, state, public):
        """The player reloaded mid-attempt. Return the public data the game needs to continue."""
        return public

    def event(self, ctx, state, type, data):
        """Check one move. Return (new_state, reply). Raise ValidatorError to reject it."""
        return state, {}

    def finish(self, ctx, state, claimed):
        """End the attempt. Return {"score": number or None, "detail": {...}}.

        ``claimed`` is what the browser reported. Validators should compute the
        score from ``state`` instead of trusting it.
        """
        raise ValidatorError("This game can't be finished yet.", "not_finished")

    def call(self, ctx, method, params):
        """Answer a request that isn't part of an attempt (e.g. a search). Return a dict."""
        raise ValidatorError("Unknown request '%s'." % method, "unknown_method")
