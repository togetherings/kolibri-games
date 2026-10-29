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
    os.environ.setdefault("KOLIBRI_HOME", os.path.join(ROOT, ".e2e-home"))
    os.environ["KOLIBRI_GAMES_DEV_QUIET"] = "1"
    from kolibri_games import devserver, registry

    devserver.load_classroom(os.path.join(ROOT, "examples", "classroom-games", "preview.json"))
    registry.discover(refresh=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), devserver.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


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
            assert page.locator(".game").count() == 4, "expected two Free-play Games and two Classroom Games"
            if shots:
                page.screenshot(path=os.path.join(shots, "1-lobby.png"), full_page=True)

            # Number Hunt: first attempt counts
            page.goto(base + "#/play/l-org.togetherings.number-hunt")
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
            if shots:
                page.screenshot(path=os.path.join(shots, "3-number-hunt-done.png"))
            assert page.locator(".chip").first.inner_text() in ("This attempt counts", "Practice")

            # Play again is practice
            frame.locator("#btn-again").click()
            frame.locator("#play:not([hidden])").wait_for()
            binary_search(frame)
            frame.locator("#done:not([hidden])").wait_for()
            assert "practice" in frame.locator("#done-standing").inner_text().lower()

            # Exit button returns to the lobby
            frame.locator("#btn-exit").click()
            page.locator("#free-play .shelf").wait_for()
            # Free-play Games come first, then Classroom Games
            sections = page.locator(".shelf-section .shelf-title").all_inner_texts()
            assert sections == ["Free-play Games", "Classroom Games"], sections
            assert page.locator("#classroom .game h3").all_inner_texts() == ["Lessons In Typing", "Studies In Geography"]

            # Memory Match: client-scored
            page.goto(base + "#/play/l-org.togetherings.memory-match")
            frame = page.frame_locator("iframe.game-frame")
            frame.locator(".card").first.wait_for()
            solve_memory(page, frame)
            frame.locator("#done:not([hidden])").wait_for(timeout=15000)
            if shots:
                page.screenshot(path=os.path.join(shots, "4-memory-done.png"))

            # The sandbox: the game can't reach the parent page or the API with the session.
            sandbox = page.evaluate(
                """() => { const f = document.querySelector('iframe.game-frame');
                   try { return f.contentWindow.document ? 'reachable' : 'blocked'; } catch (e) { return 'blocked'; } }"""
            )
            assert sandbox == "blocked", sandbox

            # Coach: results, settings, reset
            page.goto(base + "?as=coach#/results/l-org.togetherings.number-hunt")
            page.locator("table tbody tr").first.wait_for()
            assert "Amina Learner" in page.locator("table").inner_text()
            page.locator("button:has-text('History')").first.click()
            if shots:
                page.screenshot(path=os.path.join(shots, "5-coach-results.png"), full_page=True)
            page.goto(base + "#/settings/l-org.togetherings.number-hunt")
            page.locator("form fieldset").first.wait_for()
            page.select_option("#f-g-max", index=0)
            page.select_option("#f-p-leaderboard", index=1)
            page.locator("button:has-text('Save settings')").click()
            page.locator("#toast:not([hidden])").wait_for()
            assert "saved" in page.locator("#toast").inner_text().lower()
            if shots:
                page.screenshot(path=os.path.join(shots, "6-settings.png"), full_page=True)

            # Ben sees initials and the new range
            page.goto(base + "?as=ben#/board/l-org.togetherings.number-hunt")
            page.locator("table").wait_for()
            assert "A.L." in page.locator("table").inner_text()
            page.goto(base + "#/play/l-org.togetherings.number-hunt")
            frame = page.frame_locator("iframe.game-frame")
            frame.locator("#intro-high").wait_for()
            assert frame.locator("#intro-high").inner_text() == "20"

            # Classroom Games: scoreboards read from (pretend) saved data in Learn
            page.goto(base + "?as=amina#/")
            card = page.locator(".game", has_text="Studies In Geography")
            assert "scores on 3 maps" in card.inner_text(), card.inner_text()
            card.locator("text=Scoreboard").click()
            page.locator(".scores").wait_for()
            page.locator(".board-link", has_text="Sierra Leone: regions").click()
            page.locator(".panel.board h2:has-text('Sierra Leone: regions')").wait_for()
            rows = page.locator(".panel.board tbody tr")
            first = rows.nth(0).inner_text()
            # Amina's two saves of this map (in two resources) are merged: best accuracy, plays added up.
            assert "Amina Learner (you)" in first and "100%" in first and "5:00" in first and "6" in first, first
            assert "Maps of the world" in page.locator(".panel.board").inner_text()
            if shots:
                page.screenshot(path=os.path.join(shots, "9-classroom-scoreboards.png"), full_page=True)
            # LIT: unfinished lessons ("done": 0) don't count; board names come from the resource.
            page.goto(base + "#/scores/g-org.togetherings.lit")
            page.locator(".board-link").first.wait_for()
            names = page.locator(".board-link .board-name").all_inner_texts()
            assert names == ["Lesson 1: Left-hand home keys", "Lesson 2: Right-hand home keys"], names
            assert "1st" not in page.locator(".board-link").nth(1).inner_text()
            # Ben ranks first on lesson 1 (higher accuracy, even though Amina typed faster)
            assert "Ben Learner" in page.locator(".panel.board tbody tr").nth(0).inner_text()
            # The coach hides names; learners then see initials
            page.goto(base + "?as=coach#/settings/g-org.togetherings.lit")
            page.locator("#f-p-leaderboard").wait_for()
            page.select_option("#f-p-leaderboard", index=1)
            page.locator("button:has-text('Save settings')").click()
            page.locator("#toast:not([hidden])").wait_for()
            page.goto(base + "?as=amina#/scores/g-org.togetherings.lit")
            page.locator(".panel.board tbody tr").first.wait_for()
            top = page.locator(".panel.board tbody tr").nth(0).inner_text()
            assert "B.L." in top and "Ben" not in top, top

            # Admin setup page
            page.goto(base + "?as=admin#/status")
            page.locator("h1:has-text('Setup')").wait_for()
            if shots:
                page.screenshot(path=os.path.join(shots, "7-setup.png"), full_page=True)

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
