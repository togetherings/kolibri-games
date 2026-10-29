"""
Reading Wikipedia on the device, for games that use the "wikipedia-race"
service (Wiki BLAZE). No Django imports.

The data comes from a Wikipedia .zim file (the same files Kiwix and
Internet-in-a-Box use), read with the ``libzim`` package. For tests and the
preview server, a plain folder of .html files works too (FolderWiki).

What this module does:

* finds articles by title or path, following redirects
* cleans an article's HTML so it can be shown inside a game: scripts, styles
  and forms are removed, links to other allowed articles become
  ``<a data-to="path">``, other links become plain text, and images point at
  the game's ``__wiki__/`` address (served by views.play_file)
* lists the articles an article links to (used to check every move, to make
  random start-and-goal pairs and to work out the shortest route)
* suggests titles while a coach types
* reads article lists (one title per line) and turns them into a set of paths

Everything is kept small for a Raspberry Pi: articles are read only when
needed, a few cleaned articles are kept in memory, and the shortest-route
search has limits on pages, time and memory, and pauses often so the rest of
the server stays responsive.
"""
import bisect
import json
import os
import posixpath
import random
import re
import threading
import time
from collections import OrderedDict
from html import escape, unescape
from html.parser import HTMLParser
from urllib.parse import quote, unquote

from .sources import guess_type

#: Where article images are served inside a game (see views.play_file).
FILE_PREFIX = "__wiki__/"

#: Cleaned articles kept in memory (a class often starts on the same article).
ARTICLE_CACHE_SIZE = 48

#: Limits for the shortest-route search, so it can't take over a busy Pi.
ROUTE_MAX_PAGES = 20000
ROUTE_MAX_SECONDS = 90
ROUTE_MAX_KNOWN = 300000
ROUTE_MAX_STEPS = 8


class WikiError(Exception):
    pass


# ------------------------------------------------------------------ sources


class WikiSource(object):
    """Common code for a Wikipedia ZIM file and a folder of articles."""

    #: Changes when the data changes, so caches never mix two files up.
    stamp = None

    def entry(self, path):
        """(canonical path, title, is_article) after following redirects, or None if missing."""
        raise NotImplementedError

    def html(self, path):
        """The raw HTML of an article (text)."""
        raise NotImplementedError

    def read_file(self, path):
        """(bytes, mimetype) of a non-article file such as an image, or None."""
        raise NotImplementedError

    def random_article(self):
        raise NotImplementedError

    def suggest(self, text, limit=10):
        """Article paths whose titles start with or contain ``text``."""
        raise NotImplementedError

    # ---- shared helpers

    def article(self, path):
        """(canonical path, title) if ``path`` is an article (after redirects), else None."""
        if not path:
            return None
        found = self.entry(path)
        if found is None or not found[2]:
            return None
        return found[0], found[1]

    def candidates(self, text):
        """Paths to try for something a person typed: 'cat', 'Cat', 'Solar system', ..."""
        text = (text or "").strip().replace(" ", "_")
        if not text:
            return []
        out = [text, text[:1].upper() + text[1:]]
        return list(OrderedDict.fromkeys(out))

    def find(self, text):
        """(path, title) for a title or path someone typed, or None."""
        for path in self.candidates(text):
            found = self.article(path)
            if found:
                return found
        return None

    def title(self, path):
        found = self.entry(path)
        return found[1] if found else path.replace("_", " ")


class ZimWiki(WikiSource):
    """A Wikipedia .zim file, read with libzim."""

    def __init__(self, path):
        try:
            from libzim.reader import Archive
        except ImportError:
            raise WikiError(
                "Reading Wikipedia needs the libzim package. Run the Kolibri Games installer again, "
                "or install it with: pip install libzim"
            )
        try:
            self.archive = Archive(path)
        except Exception as e:
            raise WikiError("Can't open the Wikipedia file %s: %s" % (path, e))
        self.path = path
        self.stamp = (path, os.path.getmtime(path), os.path.getsize(path))
        self.new_scheme = bool(getattr(self.archive, "has_new_namespace_scheme", True))
        self.lock = threading.Lock()  # libzim objects are used from one thread at a time

    def candidates(self, text):
        found = super(ZimWiki, self).candidates(text)
        if not self.new_scheme:  # older ZIM files keep articles under "A/"
            found = [p if p.startswith("A/") else "A/" + p for p in found]
        return found

    def entry(self, path):
        with self.lock:
            try:
                if not self.archive.has_entry_by_path(path):
                    return None
                e = self.archive.get_entry_by_path(path)
                hops = 0
                while e.is_redirect and hops < 5:
                    e = e.get_redirect_entry()
                    hops += 1
                if e.is_redirect:
                    return None
                item = e.get_item()
                return e.path, e.title, item.mimetype.startswith("text/html")
            except Exception:
                return None

    def html(self, path):
        with self.lock:
            item = self.archive.get_entry_by_path(path).get_item()
            return bytes(item.content).decode("utf-8", "replace")

    def read_file(self, path):
        with self.lock:
            try:
                if not self.archive.has_entry_by_path(path):
                    return None
                e = self.archive.get_entry_by_path(path)
                if e.is_redirect:
                    e = e.get_redirect_entry()
                item = e.get_item()
                return bytes(item.content), item.mimetype
            except Exception:
                return None

    def random_article(self):
        with self.lock:
            for _ in range(20):
                e = self.archive.get_random_entry()
                if not e.is_redirect and e.get_item().mimetype.startswith("text/html"):
                    return e.path
        raise WikiError("Couldn't find a random article in the Wikipedia file.")

    def suggest(self, text, limit=10):
        with self.lock:
            try:
                from libzim.suggestion import SuggestionSearcher

                results = SuggestionSearcher(self.archive).suggest(text)
                return list(results.getResults(0, limit))
            except Exception:
                return []


class FolderWiki(WikiSource):
    """A folder of articles named <path>.html, for tests and the preview server.

    Redirects can be listed in _redirects.json ({"Cats": "Cat"}). Other files
    in the folder (like images) are served as they are.
    """

    def __init__(self, folder):
        self.folder = os.path.abspath(folder)
        self.stamp = (self.folder, os.path.getmtime(self.folder))
        try:
            with open(os.path.join(self.folder, "_redirects.json")) as f:
                self.redirects = json.load(f)
        except (OSError, ValueError):
            self.redirects = {}
        self.titles = {}
        for name in sorted(os.listdir(self.folder)):
            if name.endswith(".html"):
                path = name[:-5]
                with open(os.path.join(self.folder, name), encoding="utf-8") as f:
                    m = re.search(r"<title>(.*?)</title>", f.read(4096), re.S | re.I)
                self.titles[path] = unescape(m.group(1).strip()) if m else path.replace("_", " ")

    def entry(self, path):
        path = self.redirects.get(path, path)
        if path in self.titles:
            return path, self.titles[path], True
        if self.read_file(path):
            return path, path, False
        return None

    def html(self, path):
        with open(os.path.join(self.folder, path + ".html"), encoding="utf-8") as f:
            return f.read()

    def read_file(self, path):
        full = os.path.realpath(os.path.join(self.folder, path))
        if not full.startswith(os.path.realpath(self.folder) + os.sep) or not os.path.isfile(full):
            return None
        if full.endswith(".html"):
            return None
        with open(full, "rb") as f:
            return f.read(), guess_type(full)

    def random_article(self):
        return random.choice(sorted(self.titles))

    def suggest(self, text, limit=10):
        text = (text or "").lower().replace("_", " ")
        starts = [p for p, t in self.titles.items() if t.lower().startswith(text)]
        inside = [p for p, t in self.titles.items() if text in t.lower() and p not in starts]
        return (sorted(starts) + sorted(inside))[:limit]


_open = {}
_open_lock = threading.Lock()


def open_wiki(path):
    """The WikiSource for a data source path (kept open between requests)."""
    if not path or not os.path.exists(path):
        raise WikiError("The Wikipedia file isn't on this device any more: %s" % path)
    key = (path, os.path.getmtime(path))
    with _open_lock:
        if key not in _open:
            for old in [k for k in _open if k[0] == path]:
                del _open[old]
            _open[key] = FolderWiki(path) if os.path.isdir(path) else ZimWiki(path)
        return _open[key]


# -------------------------------------------------------------------- links

_HREF_RE = re.compile(r"""<a\s[^>]*?href\s*=\s*["']([^"'#]*)""", re.I)
_SKIP_SCHEMES = ("http:", "https:", "//", "mailto:", "javascript:", "data:", "ftp:", "tel:")


def resolve_href(current_path, href):
    """The path an href in ``current_path`` points to inside the ZIM, or None for outside links."""
    href = unescape(href or "").strip()
    if not href or href.startswith("#") or href.lower().startswith(_SKIP_SCHEMES):
        return None
    href = href.split("#", 1)[0].split("?", 1)[0]
    if not href:
        return None
    if href.startswith("/"):
        return None  # links in Wikipedia ZIM files are always relative
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(current_path), unquote(href)))
    if joined.startswith("../") or joined in (".", ".."):
        return None
    return joined


class _Links(object):
    """Turns hrefs into allowed article paths, remembering answers for one article."""

    def __init__(self, wiki, allowed):
        self.wiki = wiki
        self.allowed = allowed  # a set of paths, or None for every article
        self.memo = {}

    def target(self, current_path, href):
        path = resolve_href(current_path, href)
        if path is None:
            return None
        if path not in self.memo:
            found = self.wiki.article(path)
            ok = found is not None and (self.allowed is None or found[0] in self.allowed)
            self.memo[path] = found[0] if ok else None
        return self.memo[path]


def links_fast(wiki, path, allowed):
    """Allowed article paths linked from an article, in page order (no cleaning; for searches)."""
    try:
        html = wiki.html(path)
    except Exception:
        return []
    resolver = _Links(wiki, allowed)
    seen = OrderedDict()
    for href in _HREF_RE.findall(html):
        target = resolver.target(path, href)
        if target and target != path:
            seen[target] = True
    return list(seen)


# ---------------------------------------------------------------- cleaning

ALLOWED_TAGS = {
    "a", "abbr", "b", "blockquote", "br", "caption", "cite", "code", "dd", "details", "div", "dl", "dt",
    "em", "figcaption", "figure", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img", "li", "ol", "p",
    "pre", "q", "s", "section", "small", "span", "strong", "sub", "summary", "sup", "table", "tbody", "td",
    "tfoot", "th", "thead", "tr", "u", "ul",
}
#: Tags that never have an end tag in HTML.
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
#: Removed together with everything inside them.
DROP_TAGS = {
    "script", "style", "noscript", "iframe", "object", "embed", "svg", "math", "video", "audio", "form",
    "button", "input", "select", "textarea", "template", "head", "title", "link", "meta", "map", "canvas",
}
#: Parts of Wikipedia pages that don't help a reader here (edit links, citation markers, notices).
DROP_CLASSES = {"mw-editsection", "reference", "noprint", "mw-jump-link", "ambox", "mbox-small", "metadata"}
KEEP_ATTRS = {"colspan", "rowspan", "alt", "width", "height", "class"}
_CLASS_RE = re.compile(r"[^A-Za-z0-9_ -]")


class _Cleaner(HTMLParser):
    def __init__(self, wiki, path, allowed):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.wiki = wiki
        self.path = path
        self.links = _Links(wiki, allowed)
        self.out = []
        self.stack = []  # (tag, written) for each open tag, so end tags match up
        self.skip = 0  # >0 while inside a dropped element
        self.found = OrderedDict()
        self.in_body = False
        self.saw_body = False

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.in_body = self.saw_body = True
            return
        a = dict(attrs)
        classes = set((a.get("class") or "").split())
        if self.skip:
            if tag not in VOID_TAGS:
                self.skip += 1
            return
        if tag in DROP_TAGS or classes & DROP_CLASSES:
            if tag not in VOID_TAGS:
                self.skip = 1
            return
        if tag not in ALLOWED_TAGS:
            if tag not in VOID_TAGS:
                self.stack.append((tag, False))  # leave the tag out but keep its text
            return
        kept = []
        if tag == "a":
            target = self.links.target(self.path, a.get("href"))
            if not target or target == self.path:
                self.stack.append(("a", False))  # not a usable link: keep its text only
                return
            self.found[target] = True
            kept.append(("data-to", target))
        elif tag == "img":
            src = resolve_href(self.path, a.get("src"))
            if not src:
                return
            kept.append(("src", FILE_PREFIX + quote(src)))
            kept.append(("loading", "lazy"))
        for name, value in attrs:
            if name in KEEP_ATTRS and value is not None:
                if name == "class":
                    value = _CLASS_RE.sub("", value)[:200]
                kept.append((name, value))
        text = "".join(' %s="%s"' % (n, escape(v, quote=True)) for n, v in kept)
        self.out.append("<%s%s>" % (tag, text))
        if tag not in VOID_TAGS:
            self.stack.append((tag, True))

    def handle_startendtag(self, tag, attrs):
        # A tag written like <span/>: open it and close it straight away.
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "body":
            self.in_body = False
            return
        if self.skip:
            if tag not in VOID_TAGS:
                self.skip -= 1
            return
        if tag in VOID_TAGS or not any(t == tag for t, _ in self.stack):
            return
        # Close back to the matching tag (this also closes tags left open by mistake).
        while self.stack:
            top, written = self.stack.pop()
            if written:
                self.out.append("</%s>" % top)
            if top == tag:
                break

    def handle_data(self, data):
        if not self.skip and (self.in_body or not self.saw_body):
            self.out.append(escape(data, quote=False))

    def result(self):
        while self.stack:
            top, written = self.stack.pop()
            if written:
                self.out.append("</%s>" % top)
        return "".join(self.out).strip()


_article_cache = OrderedDict()
_article_lock = threading.Lock()


def clean_article(wiki, path, allowed, allowed_key="all"):
    """{"path", "title", "html", "links"} for an article. ``links`` are the allowed articles it links to."""
    key = (wiki.stamp, path, allowed_key)
    with _article_lock:
        if key in _article_cache:
            _article_cache.move_to_end(key)
            return _article_cache[key]
    found = wiki.article(path)
    if found is None:
        raise WikiError("There's no article called %s." % path.replace("_", " "))
    path, title = found
    cleaner = _Cleaner(wiki, path, allowed)
    cleaner.feed(wiki.html(path))
    cleaner.close()
    article = {"path": path, "title": title, "html": cleaner.result(), "links": list(cleaner.found)}
    with _article_lock:
        _article_cache[key] = article
        while len(_article_cache) > ARTICLE_CACHE_SIZE:
            _article_cache.popitem(last=False)
    return article


# ------------------------------------------------------------ article lists


def parse_list(text):
    """Titles from a list: one per line; blank lines and lines starting with # are ignored."""
    titles = []
    for line in (text or "").splitlines():
        line = line.strip().lstrip("﻿")
        if line and not line.startswith("#"):
            titles.append(line.replace(" ", "_"))
    return list(OrderedDict.fromkeys(titles))


_list_cache = {}
_list_lock = threading.Lock()


def resolve_list(wiki, titles, cache_key):
    """{"paths": set of article paths found, "missing": [titles not found], "sorted": [(lower title, path)]}.

    Done once per list and Wikipedia file, then kept (a 10,000-title list takes
    about a second on a Raspberry Pi).
    """
    key = (wiki.stamp, cache_key)
    with _list_lock:
        if key in _list_cache:
            return _list_cache[key]
    paths, missing, titled = set(), [], []
    for t in titles:
        found = wiki.find(t)
        if found:
            if found[0] not in paths:
                titled.append((found[1].lower(), found[0]))
            paths.add(found[0])
        else:
            missing.append(t.replace("_", " "))
    titled.sort()
    result = {"paths": paths, "missing": missing, "sorted": titled}
    with _list_lock:
        if len(_list_cache) > 20:
            _list_cache.clear()
        _list_cache[key] = result
    return result


def suggest(wiki, text, resolved=None, limit=10):
    """[{"path", "title"}] for a coach typing a start or goal article."""
    text = (text or "").strip()
    if not text:
        return []
    if resolved is not None:
        # Search the list itself, so suggestions are always allowed articles.
        low = text.lower().replace("_", " ")
        items = resolved["sorted"]
        i = bisect.bisect_left(items, (low, ""))
        out = []
        while i < len(items) and items[i][0].startswith(low) and len(out) < limit:
            out.append(items[i][1])
            i += 1
        if len(out) < limit:
            out += [p for t, p in items if low in t and p not in out][: limit - len(out)]
        paths = out
    else:
        paths = wiki.suggest(text, limit)
    result = []
    for p in paths:
        found = wiki.article(p)
        if found:
            result.append({"path": found[0], "title": found[1]})
    return result


# --------------------------------------------------- pairs and best routes


def random_article(wiki, allowed):
    if allowed is not None:
        if not allowed:
            raise WikiError("None of the articles in this list are in the Wikipedia file on this device.")
        return random.choice(sorted(allowed))
    return wiki.random_article()


def random_pair(wiki, allowed, min_steps=3, max_steps=6, tries=25):
    """(start, goal) where the goal is reachable from the start by following links.

    Made with a random walk, so the goal is at most ``steps`` links away. The
    goal is never linked straight from the start.
    """
    for _ in range(tries):
        start = random_article(wiki, allowed)
        steps = random.randint(min_steps, max_steps)
        chain = [start]
        for _ in range(steps):
            options = [p for p in links_fast(wiki, chain[-1], allowed) if p not in chain]
            if not options:
                break
            chain.append(random.choice(options))
        if len(chain) - 1 >= min_steps and chain[-1] not in links_fast(wiki, start, allowed):
            return start, chain[-1]
    raise WikiError("Couldn't find a start and goal that are connected. Try another article list.")


_route_lock = threading.Lock()


def shortest_route(wiki, start, goal, allowed, max_pages=ROUTE_MAX_PAGES, max_seconds=ROUTE_MAX_SECONDS):
    """{"status": "found", "route": [paths]} or {"status": "not_found" | "too_far"}.

    A breadth-first search from the start: it reads each article's links,
    nearest articles first, until it meets the goal. Only one search runs at a
    time, and it pauses briefly every few pages so other requests still get
    answered quickly.
    """
    with _route_lock:
        began = time.time()
        parent = {start: None}
        frontier = [start]
        pages = 0
        for _depth in range(ROUTE_MAX_STEPS):
            next_frontier = []
            for page in frontier:
                for target in links_fast(wiki, page, allowed):
                    if target in parent:
                        continue
                    parent[target] = page
                    if target == goal:
                        route = [goal]
                        while parent[route[-1]] is not None:
                            route.append(parent[route[-1]])
                        return {"status": "found", "route": route[::-1]}
                    next_frontier.append(target)
                pages += 1
                if pages % 25 == 0:
                    time.sleep(0.01)  # let the web server answer other requests
                if pages >= max_pages or time.time() - began > max_seconds or len(parent) > ROUTE_MAX_KNOWN:
                    return {"status": "too_far"}
            if not next_frontier:
                return {"status": "not_found"}
            frontier = next_frontier
        return {"status": "too_far"}
