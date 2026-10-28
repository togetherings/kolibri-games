"""
Integration test inside a real Kolibri. Run with:

    kolibri manage shell -c "exec(open('tests/integration/smoke.py').read())"

Expects the plugin enabled and migrated, the device provisioned, and
KOLIBRI_GAMES_PATH pointing at the repository's games/ folder. Optionally
KOLIBRI_GAMES_TEST_ZIM can point at a packed game ZIM to test channel discovery.
Creates test users in the current Kolibri database, so only use a throwaway one.
"""
import json
import os
import shutil
import sys
import uuid

from django.test import Client

from kolibri.core.auth.models import Classroom, Facility, FacilityUser
from kolibri_games import registry
from kolibri_games.management.commands.kolibri_games_check import page_routes
from kolibri_games.models import Attempt
from django.urls import get_resolver

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


amina, ben, coach = make_user("amina"), make_user("ben"), make_user("coach")
facility.add_coach(coach)
classroom = Classroom.objects.create(name="Class %s" % suffix, parent=facility)
classroom.add_member(amina)
classroom.add_member(ben)

routes = page_routes(get_resolver().url_patterns)
check(bool(routes), "games page route found: %s" % routes)
base = "/" + routes[0]
NH = "l-org.togetherings.number-hunt"
MM = "l-org.togetherings.memory-match"

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
check(status == 200 and NH in keys and MM in keys, "learner sees both sample games: %s" % keys)
check(data["me"]["role"] == "learner", "learner role detected")

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
check(status == 201 and "secret" not in json.dumps(started), "attempt started without leaking the secret")
aid = started["attempt"]["id"]
secret = Attempt.objects.get(id=aid).vstate["secret"]
wrong = secret + 1 if secret < started["public"]["high"] else secret - 1
status, reply = jpost(learner, base + "api/games/%s/attempts/%d/events" % (NH, aid), {"type": "guess", "data": {"value": wrong}})
check(status == 200 and reply["hint"] in ("higher", "lower"), "wrong guess gets a hint")
status, reply = jpost(learner, base + "api/games/%s/attempts/%d/events" % (NH, aid), {"type": "guess", "data": {"value": 0}})
check(status == 400, "out-of-range guess rejected")
status, reply = jpost(learner, base + "api/games/%s/attempts/%d/events" % (NH, aid), {"type": "guess", "data": {"value": secret}})
check(status == 200 and reply["hint"] == "correct", "right guess found")
status, result = jpost(learner, base + "api/games/%s/attempts/%d/finish" % (NH, aid), {"score": 1})
check(status == 200 and result["attempt"]["score"] == 2 and result["attempt"]["verified"], "server scored 2 guesses, ignoring the claimed 1")
check(result["standing"]["rank"] == 1, "learner ranked first")

other = Client()
other.force_login(ben)
status, _ = jpost(other, base + "api/games/%s/attempts/%d/events" % (NH, aid), {"type": "guess", "data": {"value": 3}})
check(status in (404, 409), "another learner can't touch this attempt")
status, board = jget(other, base + "api/games/%s/leaderboard" % NH)
check(status == 200 and board["rows"][0]["name"] == "Amina Test", "leaderboard shows the result")

status, mm = jpost(other, base + "api/games/%s/attempts" % MM, {"resume": False})
status, fin = jpost(other, base + "api/games/%s/attempts/%d/finish" % (MM, mm["attempt"]["id"]), {"score": 9, "detail": {"pairs": 8}})
check(status == 200 and fin["attempt"]["verified"] is False, "client-scored game saved as unchecked")
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
r = c.get(base + "api/games/%s/results?format=csv" % NH)
check(r.status_code == 200 and b"Amina Test" in r.content, "CSV export works")
status, s = jpost(c, base + "api/games/%s/settings" % NH, {"platform": {"leaderboard": "initials"}, "game": {"max": 20}})
check(status == 200 and s["values"]["game"]["max"] == 20, "coach saved settings")
status, bad = jpost(c, base + "api/games/%s/settings" % NH, {"platform": {"time_limit": -1}, "game": {}})
check(status == 400 and "time_limit" in bad.get("fields", {}), "invalid settings rejected with field errors")
status, board = jget(other, base + "api/games/%s/leaderboard" % NH)
check(board["rows"][0]["name"] == "A.T.", "learners now see initials")
status, _ = jpost(c, base + "api/games/%s/results/%s/reset" % (NH, amina.id))
status, again = jpost(learner, base + "api/games/%s/attempts" % NH)
check(again["attempt"]["practice"] is False and again["public"]["high"] == 20, "reset gives a fresh counted attempt with new settings")

# ------------------------------------------------- channel ZIM discovery

zim = os.environ.get("KOLIBRI_GAMES_TEST_ZIM")
if zim:
    try:
        from kolibri.core.content.models import ContentNode, File, LocalFile
        from kolibri.core.content.utils.paths import get_content_storage_file_path

        checksum = uuid.uuid4().hex
        target = get_content_storage_file_path("%s.zim" % checksum)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy(zim, target)
        local = LocalFile.objects.create(id=checksum, extension="zim", available=True, file_size=os.path.getsize(zim))
        channel_id = uuid.uuid4().hex
        node = ContentNode.objects.create(
            id=channel_id, content_id=uuid.uuid4().hex, channel_id=channel_id, title="Number Hunt (channel)",
            kind="zim", available=True,
        )
        File.objects.create(id=uuid.uuid4().hex, local_file=local, contentnode=node, preset="zim")
        games = registry.discover(refresh=True)
        found = [g for g in games if g.key == "c-" + node.content_id]
        check(bool(found) and found[0].playable, "game ZIM in a channel is discovered and playable")
        status, data = jget(learner, base + "api/games")
        check("c-" + node.content_id in [g["key"] for g in data["games"]], "channel game listed for learners")
    except Exception as e:  # noqa: BLE001
        check(False, "channel discovery test crashed: %r" % e)
else:
    print("skip channel discovery test (KOLIBRI_GAMES_TEST_ZIM not set)")

# ------------------------------------------------------------ Lesson Games

try:
    import zipfile

    from django.utils import timezone
    from kolibri.core.content.models import ContentNode, File, LocalFile
    from kolibri.core.content.utils.paths import get_content_storage_file_path
    from kolibri.core.logger.models import ContentSummaryLog

    LIT = os.path.join(os.getcwd(), "examples", "lesson-games", "lit")  # run from the repository folder

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
    LIT_KEY = "g-org.togetherings.lit"
    games = {g.key: g for g in registry.discover(refresh=True)}
    check(LIT_KEY in games and len(games[LIT_KEY].resources) == 2, "HTML5 apps with a Lesson Game manifest form one game")
    check("c-" + plain.content_id not in games, "ordinary HTML5 apps are left alone")
    status, data = jget(learner, base + "api/games")
    card = [g for g in data["games"] if g["key"] == LIT_KEY]
    check(bool(card) and card[0]["summary"]["boards"] == 1, "Lesson Game card shows the learner's progress: %s" % card)
    status, scores = jget(learner, base + "api/games/%s/scoreboards" % LIT_KEY)
    board = scores["boards"][0] if status == 200 and scores["boards"] else {}
    rows = [(r["rank"], r["name"], r["values"]) for r in board.get("rows", [])]
    check(rows == [(1, "Amina Test", {"acc": 99, "wpm": 9}), (2, "Ben Test", {"acc": 97, "wpm": 20})],
          "scoreboard read from Kolibri's saved data, best of both copies: %s" % rows)
    check(board.get("name") in ("Lesson 1: Left-hand home keys", "Lesson 1 again"), "board named after its resource")
    status, _ = jget(learner, base + "api/games/%s" % LIT_KEY)
    check(status == 409, "Lesson Games can't be opened on the games page (%s)" % status)
    status, s = jpost(c, base + "api/games/%s/settings" % LIT_KEY, {"platform": {"leaderboard": "initials"}})
    check(status == 200, "coach changed the Lesson Game's scoreboard setting")
    status, scores = jget(other, base + "api/games/%s/scoreboards" % LIT_KEY)
    check([r["name"] for r in scores["boards"][0]["rows"]] == ["A.T.", "Ben Test"], "learners now see initials")
    r = c.get(base + "api/games/%s/scoreboards?format=csv&class=%s" % (LIT_KEY, classroom.id))
    check(r.status_code == 200 and b"Amina Test" in r.content, "coach downloads scoreboards as CSV")
except Exception as e:  # noqa: BLE001
    import traceback

    traceback.print_exc()
    check(False, "Lesson Games test crashed: %r" % e)

print()
if FAILURES:
    print("%d check(s) failed" % len(FAILURES))
    sys.exit(1)
print("SMOKE OK")
