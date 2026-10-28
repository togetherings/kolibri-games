"""
Small version helpers, so games can say which platform version they need,
e.g. ``"requires_platform": ">=0.1,<2"``. No third-party dependencies.
"""
import re

_OPS = (">=", "<=", "==", "!=", ">", "<")
_VERSION_RE = re.compile(r"^\d+(\.\d+){0,3}$")


class VersionError(ValueError):
    pass


def parse_version(text):
    """'1.2' -> (1, 2, 0, 0). Pre-release suffixes like '1.2.0rc1' are ignored."""
    text = str(text).strip()
    text = re.split(r"[^0-9.]", text, maxsplit=1)[0].rstrip(".")
    if not _VERSION_RE.match(text):
        raise VersionError("'%s' is not a version number." % text)
    parts = [int(p) for p in text.split(".")]
    return tuple(parts + [0] * (4 - len(parts)))


def parse_spec(spec):
    """'>=0.1,<2' -> [('>=', (0,1,0,0)), ('<', (2,0,0,0))]. Empty means any version."""
    clauses = []
    for raw in str(spec or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        for op in _OPS:
            if raw.startswith(op):
                clauses.append((op, parse_version(raw[len(op):])))
                break
        else:
            clauses.append(("==", parse_version(raw)))
    return clauses


def satisfies(version, spec):
    v = parse_version(version)
    for op, want in parse_spec(spec):
        ok = {
            ">=": v >= want,
            "<=": v <= want,
            "==": v == want,
            "!=": v != want,
            ">": v > want,
            "<": v < want,
        }[op]
        if not ok:
            return False
    return True
