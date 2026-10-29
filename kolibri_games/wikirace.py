"""
The rules of a Wikipedia race (Wiki BLAZE: Browsing Links A-to-Z Exploration),
run on the server so results can't be faked. No Django imports.

A learner starts on one article and must reach the goal article by following
links. The server keeps their *chain*: the articles from the start to where
they are now.

* Following a link adds the article to the end of the chain. The server checks
  that the current article really links there.
* Going back to any earlier article in the chain is free: the chain is cut
  back to that article, and the abandoned branch stops counting.
* Following a link to an article that's already in the chain counts as going
  back to it, so going round in circles never makes the chain longer.
* The score is the number of links in the chain when the goal is reached.
  Time breaks ties (see ranking.py), so exploring costs only time.

Everything a learner does is also kept in the attempt's move list, so coaches
can see the whole exploration, not just the final route.
"""
from . import wiki

GO = "go"
BACK = "back"


class RaceError(Exception):
    def __init__(self, message, code="bad_move"):
        super(RaceError, self).__init__(message)
        self.code = code


class Race(object):
    """One Wikipedia file and one set of allowed articles (None means every article)."""

    def __init__(self, source, allowed, allowed_key):
        self.wiki = source
        self.allowed = allowed
        self.allowed_key = allowed_key

    # ------------------------------------------------------------ helpers

    def article(self, path):
        return wiki.clean_article(self.wiki, path, self.allowed, self.allowed_key)

    def page(self, path):
        """What the game shows: the cleaned article (without the server's link list)."""
        a = self.article(path)
        return {"path": a["path"], "title": a["title"], "html": a["html"]}

    def chain_public(self, chain):
        return [{"path": p, "title": self.wiki.title(p)} for p in chain]

    def reply(self, state):
        chain = state["chain"]
        return {
            "page": self.page(chain[-1]),
            "chain": self.chain_public(chain),
            "steps": len(chain) - 1,
            "done": chain[-1] == state["goal"],
        }

    # ------------------------------------------------------------ playing

    def start(self, start, goal):
        """A new race. ``start`` and ``goal`` are article paths (checked when the challenge was saved)."""
        state = {"start": start, "goal": goal, "chain": [start], "pages": 1, "backs": 0}
        public = dict(self.reply(state), start=self.chain_public([start])[0], goal=self.chain_public([goal])[0])
        return state, public

    def resume(self, state):
        return dict(self.reply(state), start=self.chain_public([state["start"]])[0], goal=self.chain_public([state["goal"]])[0])

    def move(self, state, kind, data):
        """(new state, reply for the game, what to keep in the move list)."""
        chain = list(state["chain"])
        data = data if isinstance(data, dict) else {}
        if chain[-1] == state["goal"]:
            raise RaceError("You've already reached the goal.", "finished")
        if kind == GO:
            target = data.get("to")
            if not isinstance(target, str) or target not in self.article(chain[-1])["links"]:
                raise RaceError("That link isn't on this page.")
            if target in chain:
                chain = chain[: chain.index(target) + 1]  # a loop: same as going back
                state["backs"] += 1
            else:
                chain.append(target)
            state["pages"] += 1
            log = {"to": target, "title": self.wiki.title(target), "steps": len(chain) - 1}
        elif kind == BACK:
            step = data.get("step")
            if not isinstance(step, int) or isinstance(step, bool) or not 0 <= step < len(chain) - 1:
                raise RaceError("You can only go back to an article earlier in your chain.")
            chain = chain[: step + 1]
            state["backs"] += 1
            log = {"back_to": chain[-1], "title": self.wiki.title(chain[-1]), "steps": len(chain) - 1}
        else:
            raise RaceError("Wiki BLAZE only understands 'go' and 'back'.")
        state["chain"] = chain
        return state, self.reply(state), log

    def finish(self, state):
        """(score, detail). Only possible once the goal is reached."""
        chain = state["chain"]
        if chain[-1] != state["goal"]:
            raise RaceError("You haven't reached the goal yet.", "not_finished")
        return len(chain) - 1, {
            "route": [self.wiki.title(p) for p in chain],
            "start": self.wiki.title(state["start"]),
            "goal": self.wiki.title(state["goal"]),
            "pages_visited": state["pages"],
            "times_gone_back": state["backs"],
        }


# ---------------------------------------------------------- coach settings


def check_pair(source, allowed, start_text, goal_text):
    """Turn what a coach typed into article paths.

    Returns (start, goal, errors). Both blank means "pick a random pair".
    """
    errors = {}
    start_text, goal_text = (start_text or "").strip(), (goal_text or "").strip()
    if not start_text and not goal_text:
        return None, None, errors
    if not start_text or not goal_text:
        msg = "Give both a start and a goal article, or leave both blank for a random pair."
        errors["start" if not start_text else "goal"] = msg
        return None, None, errors
    found = {}
    for key, text in (("start", start_text), ("goal", goal_text)):
        hit = source.find(text)
        if hit is None:
            errors[key] = "There's no article called \"%s\" in the Wikipedia file on this device." % text
        elif allowed is not None and hit[0] not in allowed:
            errors[key] = "\"%s\" isn't in the chosen article list." % hit[1]
        else:
            found[key] = hit[0]
    if not errors and found["start"] == found["goal"]:
        errors["goal"] = "The goal must be a different article from the start."
    if errors:
        return None, None, errors
    return found["start"], found["goal"], errors
