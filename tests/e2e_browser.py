"""
Browser test: plays both sample games through the real page, SDK and sandbox
bridge, using the preview server. Needs Playwright with Chromium.

    python -m tests.e2e_browser [--screenshots DIR]
"""
import argparse
import os
import sys
import threading
import time
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def serve(port):
    os.environ["KOLIBRI_GAMES_PATH"] = os.path.join(ROOT, "games")
    import tempfile

    os.environ["KOLIBRI_HOME"] = tempfile.mkdtemp(prefix="kolibri-games-e2e-")
    os.environ["KOLIBRI_GAMES_DEV_QUIET"] = "1"
    from kolibri_games import devserver, registry

    os.environ["KOLIBRI_GAMES_DATA_WIKIPEDIA"] = os.path.join(ROOT, "examples", "tiny-wiki")
    devserver.load_classroom(os.path.join(ROOT, "examples", "classroom-games", "preview.json"))
    registry.discover(refresh=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), devserver.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


BLAZE = "f-org.togetherings.wiki-blaze"


def make_update_zip():
    """Memory Match with version 9.0.0, as a zip to install on the Setup page."""
    import json
    import tempfile
    import zipfile

    folder = os.path.join(ROOT, "games", "memory-match")
    path = os.path.join(tempfile.mkdtemp(), "memory-match.zip")
    with zipfile.ZipFile(path, "w") as z:
        for name in os.listdir(folder):
            data = open(os.path.join(folder, name), "rb").read()
            if name == "kolibri-game.json":
                manifest = json.loads(data)
                manifest["version"] = "9.0.0"
                data = json.dumps(manifest).encode()
            z.writestr(name, data)
    return path


def binary_search(frame):
    low, high = 1, int(frame.locator("#end-high").inner_text())
    for _ in range(15):
        guess = (low + high) // 2
        frame.locator("#guess").fill(str(guess))
        count = frame.locator("#history li").count()
        frame.locator("#btn-guess").click()
        frame.locator("#history li").nth(count).wait_for(state="attached")
        hint = frame.locator("#history li").nth(count).get_attribute("class")
        if hint == "correct":
            return count + 1
        if hint == "higher":
            low = guess + 1
        else:
            high = guess - 1
    raise AssertionError("binary search didn't finish")


def solve_memory(page, frame):
    cards = frame.locator(".card")
    n = cards.count()
    labels = {}
    for i in range(n):
        if "matched" in (cards.nth(i).get_attribute("class") or ""):
            continue
        cards.nth(i).click()
        labels[i] = cards.nth(i).get_attribute("aria-label").split(", ")[-1]
        if frame.locator(".card.up:not(.matched)").count() == 2:
            page.wait_for_timeout(950)
    pairs = {}
    for i, sym in labels.items():
        pairs.setdefault(sym, []).append(i)
    for idx in pairs.values():
        if len(idx) == 2 and "matched" not in (cards.nth(idx[0]).get_attribute("class") or ""):
            cards.nth(idx[0]).click()
            cards.nth(idx[1]).click()
            page.wait_for_timeout(60)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshots", default=None)
    parser.add_argument("--port", type=int, default=8799)
    args = parser.parse_args()
    from playwright.sync_api import sync_playwright

    shots = args.screenshots
    if shots:
        os.makedirs(shots, exist_ok=True)
    server = serve(args.port)
    base = "http://127.0.0.1:%d/" % args.port
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1200, "height": 860})
            page.on("pageerror", lambda e: errors.append("page: %s" % e))
            page.on("console", lambda m: m.type == "error" and errors.append("console: %s" % m.text))
            page.on("dialog", lambda d: d.accept())

            # Lobby as Amina
            page.goto(base + "?as=amina")
            page.locator(".game").first.wait_for()
            assert page.locator("#free-play .game").count() == 3, "expected three Free-play Games"
            assert page.locator("#classroom .game").count() == 2, "expected two Classroom Games"
            sections = page.locator(".shelf-section .shelf-title").all_inner_texts()
            assert sections == ["Free-play Games", "Classroom Games"], sections
            if shots:
                page.screenshot(path=os.path.join(shots, "1-lobby.png"), full_page=True)

            # Number Hunt: the game scores itself; the first attempt counts
            page.goto(base + "#/play/f-org.togetherings.number-hunt")
            frame = page.frame_locator("iframe.game-frame")
            frame.locator("#btn-start").click()
            frame.locator("#play:not([hidden])").wait_for()
            if shots:
                frame.locator("#guess").fill("50")
                frame.locator("#btn-guess").click()
                frame.locator("#history li").first.wait_for()
                page.screenshot(path=os.path.join(shots, "2-number-hunt.png"))
            guesses = binary_search(frame)
            frame.locator("#done:not([hidden])").wait_for()
            summary = frame.locator("#done-summary").inner_text()
            assert "guess" in summary, summary
            frame.locator("#board tbody tr").first.wait_for()
            assert page.locator(".chip").first.inner_text() in ("This attempt counts", "Practice")
            frame.locator("#btn-again").click()
            frame.locator("#play:not([hidden])").wait_for()
            binary_search(frame)
            frame.locator("#done:not([hidden])").wait_for()
            assert "practice" in frame.locator("#done-standing").inner_text().lower()
            frame.locator("#btn-exit").click()
            page.locator("#free-play .shelf").wait_for()

            # Memory Match
            page.goto(base + "#/play/f-org.togetherings.memory-match")
            frame = page.frame_locator("iframe.game-frame")
            frame.locator(".card").first.wait_for()
            solve_memory(page, frame)
            frame.locator("#done:not([hidden])").wait_for(timeout=15000)

            # The sandbox: the game can't reach the parent page or the API with the session.
            sandbox = page.evaluate(
                """() => { const f = document.querySelector('iframe.game-frame');
                   try { return f.contentWindow.document ? 'reachable' : 'blocked'; } catch (e) { return 'blocked'; } }"""
            )
            assert sandbox == "blocked", sandbox

            # Coach makes a Wiki BLAZE challenge for Class A: Cat to Moon
            page.goto(base + "?as=coach#/challenges/" + BLAZE + "/new")
            page.locator("#c-title").fill("Cat to Moon")
            page.select_option("#f-g-list", label="Every article in the Wikipedia file")
            page.locator("#f-g-start").fill("cat")
            page.locator("#f-g-goal").fill("Moon")
            page.locator("button:has-text('Make challenge')").click()
            page.locator(".challenge-panel").first.wait_for()
            # The shortest route is worked out in the background; the page checks again by itself.
            page.locator(".challenge-panel:has-text('5 links')").wait_for(timeout=30000)
            assert "Cat \u2192 Mammal \u2192 Whale" in page.locator(".challenge-panel").inner_text()
            if shots:
                page.screenshot(path=os.path.join(shots, "3-challenges.png"), full_page=True)
            # A goal that isn't an article is refused, next to the field
            page.goto(base + "#/challenges/" + BLAZE + "/new")
            page.locator("#c-title").fill("Broken")
            page.select_option("#f-g-list", label="Every article in the Wikipedia file")
            page.locator("#f-g-start").fill("Cat")
            page.locator("#f-g-goal").fill("Unicorn")
            page.locator("button:has-text('Make challenge')").click()
            page.locator(".err:not([hidden])").wait_for()
            assert "no article called" in page.locator(".err:not([hidden])").inner_text()

            # Amina plays the challenge from her game card
            page.goto(base + "?as=amina#/")
            card = page.locator(".game", has_text="Wiki BLAZE")
            card.locator(".challenge a:has-text('Play')").click()
            frame = page.frame_locator("iframe.game-frame")
            frame.locator("#intro-pair:not([hidden])").wait_for()
            assert "Cat" in frame.locator("#intro-start").inner_text()
            frame.locator("#btn-start").click()
            frame.locator("#page h1:has-text('Cat')").wait_for()

            def follow(title):
                frame.locator("#page a[data-to='%s']" % title).first.click()
                frame.locator("#page h1:has-text('%s')" % title.replace("_", " ")).wait_for()

            follow("Mammal")
            follow("Animal")  # a dead end...
            frame.locator("#chain button:has-text('Mammal')").click()  # ...so go back, for free
            frame.locator("#page h1:has-text('Mammal')").wait_for()
            assert frame.locator("#hud-links").inner_text() == "1 link"
            follow("Whale")
            follow("Ocean")
            if shots:
                page.screenshot(path=os.path.join(shots, "4-wiki-blaze.png"))
            follow("Earth")
            assert frame.locator("#page a.goal-link").count() >= 1  # the goal stands out
            frame.locator("#page a[data-to='Moon']").first.click()
            frame.locator("#done:not([hidden])").wait_for()
            assert "5 links" in frame.locator("#done-summary").inner_text()
            assert frame.locator("#done-route li").count() == 6
            frame.locator("#board tbody tr").first.wait_for()
            if shots:
                page.screenshot(path=os.path.join(shots, "5-wiki-blaze-done.png"))

            # Challenge scoreboard and the coach's view of every step
            page.goto(base + "#/")
            page.locator(".game", has_text="Wiki BLAZE").locator(".challenge a:has-text('Scoreboard')").click()
            page.locator("table tbody tr").first.wait_for()
            assert "5 links" in page.locator("table").inner_text()
            page.goto(base + "?as=coach#/challenges/" + BLAZE)
            page.locator(".challenge-panel a:has-text('Results')").click()
            page.locator("button:has-text('History')").first.click()
            page.locator("summary:has-text('Every step')").click()
            assert "Went back to Mammal" in page.locator("ol.moves").inner_text()
            if shots:
                page.screenshot(path=os.path.join(shots, "6-coach-results.png"), full_page=True)

            # Coach: free-play settings; learners then see initials
            page.goto(base + "#/settings/f-org.togetherings.number-hunt")
            page.locator("form fieldset").first.wait_for()
            page.select_option("#f-g-max", index=0)
            page.select_option("#f-p-scoreboard", index=1)
            page.locator("button:has-text('Save settings')").click()
            page.locator("#toast:not([hidden])").wait_for()
            assert "saved" in page.locator("#toast").inner_text().lower()
            page.goto(base + "?as=ben#/board/f-org.togetherings.number-hunt")
            page.locator("table").wait_for()
            assert "A.L." in page.locator("table").inner_text()

            # Coach: an article list, checked against the Wikipedia file
            page.goto(base + "?as=coach#/lists/new")
            page.locator("#l-name").fill("Space")
            page.locator("#l-titles").fill("Earth\nMoon\nSun\nMars")
            page.locator("button:has-text('Save list')").click()
            page.locator(".notice:has-text('3 articles found')").wait_for()
            assert "Mars" in page.locator(".notice").inner_text()

            # Administrator: install an update of Memory Match from a zip, then remove it
            page.goto(base + "?as=admin#/status")
            page.locator("h1:has-text('Setup')").wait_for()
            page.set_input_files("#install-file", make_update_zip())
            page.locator("button:has-text('Install')").click()
            page.locator("#toast:has-text('Installed Memory Match 9.0.0')").wait_for()
            row = page.locator("tr", has_text="Memory Match").filter(has_text="9.0.0")
            row.wait_for()
            assert "ready" in row.inner_text(), row.inner_text()  # a second copy elsewhere is only a note
            if shots:
                page.screenshot(path=os.path.join(shots, "7-setup.png"), full_page=True)
            row.locator("button:has-text('Remove')").click()
            page.locator("#toast:has-text('Removed')").wait_for()
            assert page.locator("#wiki-pick").count() == 1

            # Classroom Games: scoreboards read from (pretend) saved data in Learn
            page.goto(base + "?as=amina#/")
            card = page.locator(".game", has_text="Studies In Geography")
            assert "scores on 3 maps" in card.inner_text(), card.inner_text()
            card.locator("text=Scoreboard").click()
            page.locator(".scores").wait_for()
            page.locator(".board-link", has_text="Sierra Leone: regions").click()
            page.locator(".panel.board h2:has-text('Sierra Leone: regions')").wait_for()
            first = page.locator(".panel.board tbody tr").nth(0).inner_text()
            assert "Amina Learner (you)" in first and "100%" in first and "5:00" in first and "6" in first, first

            # Phone width and dark mode
            phone = browser.new_page(viewport={"width": 390, "height": 800}, is_mobile=True, color_scheme="dark")
            phone.goto(base + "?as=amina")
            phone.locator(".game").first.wait_for()
            width = phone.evaluate("document.documentElement.scrollWidth")
            assert width <= 390, "horizontal scroll on phones: %s" % width
            if shots:
                phone.screenshot(path=os.path.join(shots, "8-phone-dark.png"), full_page=True)
            browser.close()
    finally:
        server.shutdown()
    real_errors = [e for e in errors if "status of 4" not in e]
    if real_errors:
        print("Browser errors:\n  " + "\n  ".join(real_errors))
        sys.exit(1)
    print("Browser test passed (first Number Hunt took %d guesses)." % guesses)


if __name__ == "__main__":
    main()
