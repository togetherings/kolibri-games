"""
Browser test against a running Kolibri (used in CI). Checks that:

1. Opening the games page while signed out leads to Kolibri's sign-in, and
   signing in comes straight back to the game that was opened.
2. The "Games" link appears in Kolibri's own side menu.

    python -m tests.integration.live_browser http://127.0.0.1:8080/ USERNAME PASSWORD
"""
import sys

from playwright.sync_api import sync_playwright

GAME = "l-org.togetherings.number-hunt"


def main(base, username, password):
    failures = []
    errors = []

    def check(cond, what):
        print(("ok   " if cond else "FAIL ") + what, flush=True)
        if not cond:
            failures.append(what)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        page.on("console", lambda m: m.type in ("error", "warning") and "Kolibri Games" in m.text and errors.append(m.text))

        # 1. Signed out -> sign in -> back to the game
        page.goto(base + "en/kolibri_games/#/play/" + GAME)
        page.get_by_role("link", name="Sign in").click()
        page.locator("#username").wait_for(timeout=60000)
        check("next=" in page.url, "sign-in page received the return address: %s" % page.url)
        page.locator("#username").fill(username)
        page.locator("button.login-btn, .login-btn button, .login-btn").first.click()
        page.locator("#password").wait_for(timeout=30000)
        page.locator("#password").fill(password)
        page.locator("#password").press("Enter")
        page.wait_for_url("**/kolibri_games/**", timeout=60000)
        check("#/play/" + GAME in page.url, "came back to the game after signing in: %s" % page.url)
        page.locator("iframe.game-frame").wait_for(timeout=30000)
        frame = page.frame_locator("iframe.game-frame")
        frame.locator("#btn-start").wait_for(timeout=30000)
        check(True, "game loaded inside Kolibri")

        # 2. Side menu link
        page.goto(base + "en/learn/")
        page.wait_for_function(
            "() => window.kolibriCoreAppGlobal && window.kolibriCoreAppGlobal['kolibri/composables/useNav']",
            timeout=60000,
        )
        page.wait_for_timeout(3000)
        items = page.evaluate(
            """() => window.kolibriCoreAppGlobal['kolibri/composables/useNav'].navItems.value
                     .map(i => ({label: i.label, url: i.url}))"""
        )
        labels = [i["label"] for i in items]
        print("menu items: %s" % items, flush=True)
        games = [i for i in items if i["label"] == "Games"]
        check(bool(games), "'Games' is in Kolibri's side menu")
        if games:
            check(games[0]["url"].rstrip("/").endswith("kolibri_games"), "menu link points at the games page")
        check(not errors, "no errors from the menu script: %s" % errors)
        browser.close()

    print()
    if failures:
        print("%d check(s) failed" % len(failures))
        sys.exit(1)
    print("LIVE BROWSER OK (menu: %s)" % ", ".join(labels))


if __name__ == "__main__":
    main(*sys.argv[1:4])
