"""
Validator for the sample game Number Hunt: the server picks a secret number
and answers each guess with "higher", "lower" or "correct". The secret never
reaches the browser, so the score (number of guesses) can't be faked.
"""
from .base import Validator, ValidatorError


class NumberHuntValidator(Validator):
    name = "number-hunt"

    def _range(self, ctx):
        return 1, int(ctx.settings.get("max", 100))

    def start(self, ctx):
        low, high = self._range(ctx)
        secret = ctx.rng.randint(low, high)
        return {
            "state": {"secret": secret, "low": low, "high": high, "guesses": [], "found": False},
            "public": {"low": low, "high": high, "guesses": []},
        }

    def resume(self, ctx, state, public):
        return {
            "low": state["low"],
            "high": state["high"],
            "guesses": [{"value": g, "hint": self._hint(state["secret"], g)} for g in state["guesses"]],
            "found": state["found"],
        }

    @staticmethod
    def _hint(secret, value):
        if value < secret:
            return "higher"
        if value > secret:
            return "lower"
        return "correct"

    def event(self, ctx, state, type, data):
        if type != "guess":
            raise ValidatorError("Number Hunt only understands guesses.", "unknown_event")
        if state["found"]:
            raise ValidatorError("You already found the number.", "finished")
        value = (data or {}).get("value")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidatorError("Guess a whole number.", "bad_guess")
        if not state["low"] <= value <= state["high"]:
            raise ValidatorError(
                "Guess a number from %d to %d." % (state["low"], state["high"]), "bad_guess"
            )
        state = dict(state, guesses=state["guesses"] + [value])
        hint = self._hint(state["secret"], value)
        if hint == "correct":
            state["found"] = True
        return state, {"hint": hint, "guesses": len(state["guesses"])}

    def finish(self, ctx, state, claimed):
        if not state["found"]:
            raise ValidatorError("Find the number first.", "not_finished")
        return {
            "score": len(state["guesses"]),
            "detail": {"secret": state["secret"], "guesses": state["guesses"], "high": state["high"]},
        }
