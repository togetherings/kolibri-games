"""
Integration test inside a real Kolibri. Run from the repository folder with:

    kolibri manage shell -c "exec(open('tests/integration/smoke.py').read())"

Expects the plugin enabled and migrated, the device provisioned (with a super
admin called "admin"), and KOLIBRI_GAMES_PATH pointing at the repository's
games/ folder. KOLIBRI_GAMES_TEST_WIKI can point at a test Wikipedia ZIM
(made with: python -m tests.make_test_zim tiny.zim) to test Wiki BLAZE.
Creates test users in the current Kolibri database, so only use a throwaway one.
"""
import io
import json
import os
import sys
import time
import uuid
import zipfile

from django.test import Client
from django.urls import get_resolver

from kolibri.core.auth.models import Classroom, Facility, FacilityUser
from kolibri_games import registry
from kolibri_games.management.commands.kolibri_games_check import page_routes
from kolibri_games.models import Challenge

FAILURES = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAILURES.append(what)


def jget(client, url):
    r = client.get(url)
    try:
        return r.status_code, json.loads(r.content.decode("utf-8"))
    except ValueError:
        return r.status_code, None


def jpost(client, url, body=None):
    r = client.post(url, data=json.dumps(body or {}), content_type="application/json")
    try:
        return r.status_code, json.loads(r.content.decode("utf-8"))
    except ValueError:
        return r.status_code, None


# ------------------------------------------------------------------ setup

facility = Facility.get_default_facility() or Facility.objects.create(name="Test facility")
suffix = uuid.uuid4().hex[:6]


def make_user(name):
    user = FacilityUser.objects.create(username="%s_%s" % (name, suffix), full_name=name.title() + " Test", facility=facility)
    user.set_password("password")
    user.save()
    return user


amina, ben, cara, coach = make_user("amina"), make_user("ben"), make_user("cara"), make_user("coach")
facility.add_coach(coach)
classroom = Classroom.objects.create(name="Class %s" % suffix, parent=facility)
classroom.add_member(amina)
classroom.add_member(ben)
other_class = Classroom.objects.create(name="Other %s" % suffix, parent=facility)
other_class.add_member(cara)
admin = FacilityUser.objects.filter(username="admin").first()

routes = page_routes(get_resolver().url_patterns)
check(bool(routes), "games page route found: %s" % routes)
base = "/" + routes[0]
NH = "f-org.togetherings.number-hunt"
MM = "f-org.togetherings.memory-match"
BLAZE = "f-org.togetherings.wiki-blaze"

# ------------------------------------------------------------ anonymous

anon = Client()
r = anon.get(base)
check(r.status_code == 200 and b"assets/app.js" in r.content, "games page loads (%s)" % r.status_code)
check(anon.get(base + "assets/sdk.js").status_code == 200, "sdk asset served")
status, data = jget(anon, base + "api/games")
check(status == 401 and data and data["error"] == "signin", "API asks anonymous users to sign in")

# --------------------------------------------------------------- learner

learner = Client()
learner.force_login(amina)
status, data = jget(learner, base + "api/games")
keys = [g["key"] for g in (data or {}).get("games", [])]
check(status == 200 and NH in keys and MM in keys, "learner sees the sample games: %s" % keys)
check(data["me"]["role"] == "learner" and not data["me"]["can_install"], "learner role detected")

status, session = jget(learner, base + "api/games/" + NH)
check(status == 200 and session["play_url"].startswith("play/"), "game session has a play link")
play = base + session["play_url"]
r = learner.get(play)
check(r.status_code == 200 and b"Number Hunt" in r.content, "game page served from play link")
csp = r.get("Content-Security-Policy", "")
check("sandbox allow-scripts" in csp and "allow-same-origin" not in csp, "game files are sandboxed: %s" % csp)
check(learner.get(play + "__kolibri_games__/sdk.js").status_code == 200, "SDK served inside the game")
check(learner.get(play + "../../kolibri-game.json").status_code in (403, 404), "path escape blocked")
check(Client().get(base + "play/bad-token/index.html").status_code == 403, "bad play token rejected")

status, started = jpost(learner, base + "api/games/%s/attempts" % NH)
aid = started["attempt"]["id"]
for value in (50, 25, 37):
    status, _ = jpost(learner, base + "api/games/%s/attempts/%d/moves" % (NH, aid), {"type": "guess", "data": {"value": value}})
check(status == 200, "moves are recorded")
status, result = jpost(learner, base + "api/games/%s/attempts/%d/finish" % (NH, aid), {"score": 3})
check(status == 200 and result["attempt"]["score"] == 3 and result["standing"]["rank"] == 1, "learner's score saved and ranked")
status, bad = jpost(learner, base + "api/games/%s/attempts" % NH, {"resume": False})
status, _ = jpost(learner, base + "api/games/%s/attempts/%d/finish" % (NH, bad["attempt"]["id"]), {"score": 99999})
check(status == 400, "impossible scores are refused")

other = Client()
other.force_login(ben)
status, _ = jpost(other, base + "api/games/%s/attempts/%d/moves" % (NH, aid), {"type": "guess", "data": {"value": 3}})
check(status in (404, 409), "another learner can't touch this attempt")
status, board = jget(other, base + "api/games/%s/scoreboard" % NH)
check(status == 200 and board["rows"][0]["name"] == "Amina Test", "scoreboard shows the result")
status, _ = jpost(other, base + "api/games/%s/state" % MM, {"data": {"level": 2}})
status, st = jget(other, base + "api/games/%s/state" % MM)
check(st and st["data"] == {"level": 2}, "saved state round-trips")
status, _ = jget(learner, base + "api/games/%s/results" % NH)
check(status == 403, "learners can't see coach results")

# ----------------------------------------------------------------- coach

c = Client()
c.force_login(coach)
status, data = jget(c, base + "api/games")
check(data["me"]["role"] == "coach", "coach role detected")
status, classes = jget(c, base + "api/classes")
check(status == 200 and any(x["id"] == classroom.id for x in classes["classes"]), "coach sees the class")
status, res = jget(c, base + "api/games/%s/results?class=%s" % (NH, classroom.id))
names = [row["name"] for row in res["rows"]]
check(status == 200 and "Amina Test" in names and "Ben Test" in names, "class results include every member: %s" % names)
r = c.get(base + "api/games/%s/results?format=csv&class=%s" % (NH, classroom.id))
check(r.status_code == 200 and b"Amina Test" in r.content, "CSV export works")
status, s = jpost(c, base + "api/games/%s/settings" % NH, {"platform": {"scoreboard": "initials"}, "game": {"max": 20}})
check(status == 200 and s["values"]["game"]["max"] == 20, "coach saved settings")
status, bad = jpost(c, base + "api/games/%s/settings" % NH, {"platform": {"time_limit": -1}, "game": {}})
check(status == 400 and "time_limit" in bad.get("fields", {}), "invalid settings rejected with field errors")
status, board = jget(other, base + "api/games/%s/scoreboard" % NH)
check(board["rows"][0]["name"] == "A.T.", "learners now see initials")
status, _ = jpost(c, base + "api/games/%s/results/%s/reset" % (NH, amina.id), {})
status, again = jpost(learner, base + "api/games/%s/attempts" % NH, {"resume": False})
check(again["attempt"]["practice"] is False, "reset gives a fresh counted attempt")

# ------------------------------------------------------------- challenges

status, made = jpost(c, base + "api/games/%s/challenges" % MM, {
    "title": "Pairs race", "class_id": classroom.id, "counts": "best", "settings": {"pairs": 6},
})
check(status == 201 and made["state"] == "open", "coach made a challenge: %s" % (made,))
cid = made["id"]
status, data = jget(learner, base + "api/games")
card = [g for g in data["games"] if g["key"] == MM][0]
check([x["title"] for x in card["challenges"]] == ["Pairs race"], "the class sees the challenge on the game card")
cara_client = Client()
cara_client.force_login(cara)
status, data = jget(cara_client, base + "api/games")
check([g for g in data["games"] if g["key"] == MM][0]["challenges"] == [], "another class doesn't see it")
status, _ = jpost(cara_client, base + "api/games/%s/attempts" % MM, {"challenge": cid})
check(status == 403, "another class can't play it")
status, session = jget(learner, base + "api/games/%s?challenge=%d" % (MM, cid))
check(session["settings"]["pairs"] == 6 and session["challenge"]["title"] == "Pairs race", "challenge settings reach the game")
status, started = jpost(learner, base + "api/games/%s/attempts" % MM, {"challenge": cid})
status, result = jpost(learner, base + "api/games/%s/attempts/%d/finish" % (MM, started["attempt"]["id"]), {"score": 7})
status, board = jget(other, base + "api/games/%s/scoreboard?challenge=%d" % (MM, cid))
check([r["score"] for r in board["rows"]] == [7], "the challenge has its own scoreboard")
status, board = jget(other, base + "api/games/%s/scoreboard" % MM)
check(board["rows"] == [], "free play's scoreboard is separate")
status, res = jget(c, base + "api/games/%s/results?challenge=%d" % (MM, cid))
check(status == 200 and len(res["rows"]) == 2, "challenge results list the class")
status, _ = jpost(c, base + "api/games/%s/challenges/%d/delete" % (MM, cid))
check(status == 200 and not Challenge.objects.filter(id=cid).exists(), "coach deleted the challenge")

# ------------------------------------------------------- installing games

if admin is not None:
    a = Client()
    a.force_login(admin)
    status, data = jget(a, base + "api/games")
    check(data["me"]["can_install"], "the device's super admin can install games")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in os.listdir("games/memory-match"):
            content = open(os.path.join("games/memory-match", name), "rb").read()
            if name == "kolibri-game.json":
                m = json.loads(content)
                m["id"], m["version"], m["title"] = "org.example.installed", "1.0.0", "Installed Match"
                content = json.dumps(m).encode()
            z.writestr(name, content)
    r = a.post(base + "api/install", data=buf.getvalue(), content_type="application/zip")
    check(r.status_code == 201, "a game zip installs: %s" % r.content[:200])
    status, data = jget(learner, base + "api/games")
    check("f-org.example.installed" in [g["key"] for g in data["games"]], "learners see the installed game")
    r = c.post(base + "api/install", data=buf.getvalue(), content_type="application/zip")
    check(r.status_code == 403, "coaches can't install games")
    status, _ = jpost(a, base + "api/games/f-org.example.installed/remove")
    check(status == 200 and registry.get("f-org.example.installed", refresh=True) is None, "the game is removed")
else:
    check(False, "no super admin called 'admin' to test installing")

# ------------------------------------------------------------ Wiki BLAZE

wiki_zim = os.environ.get("KOLIBRI_GAMES_TEST_WIKI")
if wiki_zim and admin is not None:
    status, _ = jpost(a, base + "api/data-sources", {"name": "wikipedia", "path": wiki_zim})
    check(status == 200, "administrator chose the Wikipedia file")
    status, data = jget(learner, base + "api/games")
    blaze = [g for g in data["games"] if g["key"] == BLAZE]
    check(bool(blaze) and blaze[0]["playable"], "Wiki BLAZE is ready to play: %s" % blaze)
    status, made = jpost(c, base + "api/games/%s/challenges" % BLAZE, {
        "title": "Cat to Moon", "class_id": classroom.id, "settings": {"start": "cat", "goal": "Moon", "list": "all"},
    })
    check(status == 201 and made["start"] == "Cat" and made["goal"] == "Moon", "Wiki BLAZE challenge made: %s" % (made,))
    for _ in range(40):  # the shortest route is worked out in a background thread
        best = Challenge.objects.get(id=made["id"]).best
        if best.get("status"):
            break
        time.sleep(0.5)
    check(best.get("route") == ["Cat", "Mammal", "Whale", "Ocean", "Earth", "Moon"], "shortest route found: %s" % best)
    status, started = jpost(learner, base + "api/games/%s/attempts" % BLAZE, {"challenge": made["id"]})
    check(status == 201 and started["public"]["page"]["title"] == "Cat", "race starts on Cat")
    aid = started["attempt"]["id"]
    status, _ = jpost(learner, base + "api/games/%s/attempts/%d/moves" % (BLAZE, aid), {"type": "go", "data": {"to": "Moon"}})
    check(status == 400, "a link that isn't on the page is refused")
    for target in ("Mammal", "Animal"):
        jpost(learner, base + "api/games/%s/attempts/%d/moves" % (BLAZE, aid), {"type": "go", "data": {"to": target}})
    status, reply = jpost(learner, base + "api/games/%s/attempts/%d/moves" % (BLAZE, aid), {"type": "back", "data": {"step": 1}})
    check(reply["steps"] == 1, "going back is free")
    for target in ("Whale", "Ocean", "Earth", "Moon"):
        status, reply = jpost(learner, base + "api/games/%s/attempts/%d/moves" % (BLAZE, aid), {"type": "go", "data": {"to": target}})
    check(reply["done"], "goal reached")
    status, result = jpost(learner, base + "api/games/%s/attempts/%d/finish" % (BLAZE, aid), {"score": 1})
    check(status == 200 and result["attempt"]["score"] == 5, "the server counted 5 links, ignoring the claimed 1")
    status, session = jget(learner, base + "api/games/" + BLAZE)
    r = learner.get(base + session["play_url"] + "__wiki__/I/cat.png")
    check(r.status_code == 200 and r["Content-Type"] == "image/png", "article pictures are served to the game")
    check(learner.get(base + session["play_url"] + "__wiki__/Cat").status_code == 404, "articles aren't served directly")
    status, saved = jpost(c, base + "api/article-lists", {"name": "Space", "titles": "Earth\nMoon\nSun\nMars"})
    status, info = jget(c, base + "api/article-lists/%d?game=%s" % (saved["id"], BLAZE))
    check(info.get("found") == 3 and info.get("missing") == ["Mars"], "article list checked against Wikipedia: %s" % info)
else:
    print("skip Wiki BLAZE test (KOLIBRI_GAMES_TEST_WIKI not set)")

# ------------------------------------------------------------ Classroom Games

try:
    import zipfile

    from django.utils import timezone
    from kolibri.core.content.models import ContentNode, File, LocalFile
    from kolibri.core.content.utils.paths import get_content_storage_file_path
    from kolibri.core.logger.models import ContentSummaryLog

    LIT = os.path.join(os.getcwd(), "examples", "classroom-games", "lit")  # run from the repository folder

    def html5_resource(title, with_manifest=True):
        checksum = uuid.uuid4().hex
        target = get_content_storage_file_path("%s.zip" % checksum)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with zipfile.ZipFile(target, "w") as z:
            z.writestr("index.html", "<p>%s</p>" % title)
            if with_manifest:
                z.write(os.path.join(LIT, "kolibri-game.json"), "kolibri-game.json")
        local = LocalFile.objects.create(id=checksum, extension="zip", available=True, file_size=os.path.getsize(target))
        channel_id = uuid.uuid4().hex
        node = ContentNode.objects.create(
            id=channel_id, content_id=uuid.uuid4().hex, channel_id=channel_id, title=title, kind="html5", available=True,
        )
        File.objects.create(id=uuid.uuid4().hex, local_file=local, contentnode=node, preset="html5_zip")
        return node

    def played(user, node, suspend_data):
        now = timezone.now()
        ContentSummaryLog.objects.create(
            user=user, content_id=node.content_id, channel_id=node.channel_id, kind="html5",
            start_timestamp=now, end_timestamp=now, progress=1, time_spent=60,
            extra_fields={"contentState": {"SCORM": {"cmi": {"suspend_data": json.dumps(suspend_data),
                                                              "core": {"lesson_status": "passed"}}}}},
        )

    lesson1 = html5_resource("Lesson 1: Left-hand home keys")
    lesson1_copy = html5_resource("Lesson 1 again")
    plain = html5_resource("An ordinary HTML5 app", with_manifest=False)
    played(amina, lesson1, {"en-01": {"done": 1, "acc": 96, "wpm": 14}})
    played(amina, lesson1_copy, {"en-01": {"done": 1, "acc": 99, "wpm": 9}})
    played(ben, lesson1, {"en-01": {"done": 1, "acc": 97, "wpm": 20}})
    LIT_KEY = "c-org.togetherings.lit"
    games = {g.key: g for g in registry.discover(refresh=True)}
    check(LIT_KEY in games and len(games[LIT_KEY].resources) == 2, "HTML5 apps with a Classroom Game manifest form one game")
    check("c-" + plain.content_id not in games, "ordinary HTML5 apps are left alone")
    status, data = jget(learner, base + "api/games")
    card = [g for g in data["games"] if g["key"] == LIT_KEY]
    check(bool(card) and card[0]["summary"]["boards"] == 1, "Classroom Game card shows the learner's progress: %s" % card)
    status, scores = jget(learner, base + "api/games/%s/boards" % LIT_KEY)
    board = scores["boards"][0] if status == 200 and scores["boards"] else {}
    rows = [(r["rank"], r["name"], r["values"]) for r in board.get("rows", [])]
    check(rows == [(1, "Amina Test", {"acc": 99, "wpm": 9}), (2, "Ben Test", {"acc": 97, "wpm": 20})],
          "scoreboard read from Kolibri's saved data, best of both copies: %s" % rows)
    check(board.get("name") in ("Lesson 1: Left-hand home keys", "Lesson 1 again"), "board named after its resource")
    status, _ = jget(learner, base + "api/games/%s" % LIT_KEY)
    check(status == 409, "Classroom Games can't be opened on the games page (%s)" % status)
    status, s = jpost(c, base + "api/games/%s/settings" % LIT_KEY, {"platform": {"scoreboard": "initials"}})
    check(status == 200, "coach changed the Classroom Game's scoreboard setting")
    status, scores = jget(other, base + "api/games/%s/boards" % LIT_KEY)
    check([r["name"] for r in scores["boards"][0]["rows"]] == ["A.T.", "Ben Test"], "learners now see initials")
    r = c.get(base + "api/games/%s/boards?format=csv&class=%s" % (LIT_KEY, classroom.id))
    check(r.status_code == 200 and b"Amina Test" in r.content, "coach downloads scoreboards as CSV")
except Exception as e:  # noqa: BLE001
    import traceback

    traceback.print_exc()
    check(False, "Classroom Games test crashed: %r" % e)

print()
if FAILURES:
    print("%d check(s) failed" % len(FAILURES))
    sys.exit(1)
tested = "with Wiki BLAZE" if os.environ.get("KOLIBRI_GAMES_TEST_WIKI") else "WITHOUT Wiki BLAZE"
print("::notice title=Integration test::SMOKE OK %s" % tested)
print("SMOKE OK")
