"""
Trusted rule checkers ("validators").

Game code runs in the learner's browser and can't be trusted to report its
own score. A validator is Python code, installed by the device admin, that
runs on the server: it can keep secrets (like the answer), check each move,
and work out the final score itself. A game names its validator in its
manifest (``"validator": "number-hunt"``).

Validators ship with this plugin, or with any Python package that registers
one under the ``kolibri_games.validators`` entry point group::

    [project.entry-points."kolibri_games.validators"]
    my-game = "my_package.validators:MyGameValidator"
"""
import logging

from .base import Validator, ValidatorContext, ValidatorError  # noqa: F401
from .number_hunt import NumberHuntValidator

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "kolibri_games.validators"

BUILTIN = {
    NumberHuntValidator.name: NumberHuntValidator,
}

_registry = None


def _entry_points():
    try:
        from importlib.metadata import entry_points
    except ImportError:  # Python < 3.8
        return []
    try:
        eps = entry_points()
        if hasattr(eps, "select"):
            return list(eps.select(group=ENTRY_POINT_GROUP))
        return list(eps.get(ENTRY_POINT_GROUP, []))
    except Exception:
        logger.exception("Kolibri Games: could not read validator entry points")
        return []


def registry():
    """name -> Validator class, built-ins plus installed extensions."""
    global _registry
    if _registry is None:
        found = dict(BUILTIN)
        for ep in _entry_points():
            try:
                cls = ep.load()
            except Exception:
                logger.exception("Kolibri Games: could not load validator %s", ep.name)
                continue
            if not (isinstance(cls, type) and issubclass(cls, Validator)):
                logger.warning("Kolibri Games: %s is not a Validator subclass", ep.name)
                continue
            found[ep.name] = cls
        _registry = found
    return _registry


def get(name):
    cls = registry().get(name)
    return cls() if cls else None
