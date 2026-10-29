# Kolibri Games

A [Kolibri](https://learningequality.org/kolibri/) plugin that turns Kolibri into a home for
offline learning games, built with [Internet-in-a-Box](https://internet-in-a-box.org/) in mind.

- **Games are content, not code in the plugin.** Every game is a zip of web files, so adding a
  game never means changing the plugin.
- **Two kinds of game.** *Free-play Games* are installed on the games page's Setup page and played
  there, anytime or in a class challenge. *Classroom Games* are ordinary HTML5 apps in Kolibri
  channels that learners open from Learn and coaches assign in lessons; the games page shows
  scoreboards from the scores they save.
- **Challenges.** Coaches set a game up for a class, with its own settings, dates and scoreboard.
- **Learners sign in with Kolibri.** Results are saved to their account.
- **Coaches stay in control.** They can see every learner's attempts and moves, export results
  as CSV, choose whether the first or best attempt counts, hide or anonymise scoreboards, set
  time limits, change each game's options, and give a learner a fresh start.
- **Light enough for a Raspberry Pi**, and works fully offline.

Games attached to each release:

- **Wiki BLAZE** (Browsing Links A-to-Z Exploration): race from one Wikipedia article to another
  by following links, using the Wikipedia file already on the device. See
  [docs/WIKI_BLAZE.md](docs/WIKI_BLAZE.md).
- **Number Hunt** and **Memory Match**, two small sample games.

Example Classroom Game manifests for Lessons In Typing and Studies In Geography are in
[examples/classroom-games](examples/classroom-games).

## Install

Kolibri Games needs Kolibri on Linux, such as Internet-in-a-Box on a Raspberry Pi.

**With internet**, run this on the Kolibri server:

```bash
curl -fsSL https://raw.githubusercontent.com/togetherings/kolibri-games/main/install.sh | sudo bash
```

**Without internet**, download `kolibri-games-<version>-offline.tar.gz` from the
[latest release](https://github.com/togetherings/kolibri-games/releases/latest) on another
computer and copy it over. Then, on the server:

```bash
tar xzf kolibri-games-*-offline.tar.gz
cd kolibri-games-*-offline
sudo ./install.sh
```

The installer finds Kolibri and the user it runs as, installs the plugin into Kolibri's Python,
updates the database and restarts Kolibri. On an update it backs up Kolibri's database first.
Run the same command again to update; add `--version 0.2.0` to install a particular release, or
`--uninstall` to remove the plugin.

Then open **Games** in Kolibri's side menu, or go to **`http://<your server>/kolibri/en/kolibri_games/`**
(on IIAB, usually `http://box.lan/kolibri/en/kolibri_games/`). Learners sign in with their Kolibri
account, and come straight back to the games page afterwards.

### Adding games

- **Free-play Games:** on the games page, open **Setup**, choose the game's `.zip` file and click
  **Install**. Installing a newer version keeps the old one, so you can go back. (Copying the
  zip into `<KOLIBRI_HOME>/kolibri_games/games/` works too; on IIAB that's
  `/library/kolibri/kolibri_games/games/`.) Only device administrators can install games.
- **Classroom Games:** import a Kolibri channel that contains them. They appear on the games page
  automatically.
- **Wiki BLAZE** also needs a Wikipedia `.zim` file: choose it on the Setup page.

The games are attached to each [release](https://github.com/togetherings/kolibri-games/releases)
as `.zip` files. Administrators can see why a game can't be played on the Setup page, or with:

```bash
sudo -u kolibri KOLIBRI_HOME=/library/kolibri kolibri manage kolibri_games_check
```

## Making games

A Free-play Game is a zip with a `kolibri-game.json` manifest and ordinary web files (HTML,
JavaScript, CSS, images), using a small JavaScript SDK to start attempts, report moves and finish
with a score. See **[docs/GAME_FORMAT.md](docs/GAME_FORMAT.md)**.

A Classroom Game is any Kolibri HTML5 app that saves its scores in SCORM `cmi.suspend_data`, plus a
`kolibri-game.json` that says how to read them. See **[docs/CLASSROOM_GAMES.md](docs/CLASSROOM_GAMES.md)**.

```bash
pip install -e ".[wikipedia]"    # in this repository
kolibri-games-preview games/ --wikipedia examples/tiny-wiki     # try games without Kolibri
kolibri-games-preview games/ --classroom examples/classroom-games/preview.json  # with Classroom Games
kolibri-games-pack games/my-game # package as dist/<id>-<version>.zip
```

## How it works

See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** for the design, including the sandbox, how
results are stored, how Wiki BLAZE reads Wikipedia, and what's planned next.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[wikipedia]" pytest
python -m pytest                 # unit tests (no Kolibri needed)
python -m tests.e2e_browser      # plays the games in Chromium (needs playwright)
```

With Kolibri installed in the same environment:

```bash
kolibri plugin enable kolibri_games
kolibri manage migrate
KOLIBRI_GAMES_PATH=$PWD/games KOLIBRI_GAMES_DATA_WIKIPEDIA=$PWD/examples/tiny-wiki kolibri start --foreground
```

GitHub Actions runs the unit tests, the browser test, an integration test inside a real
Kolibri, and the installer on an IIAB-like system for every pull request.

### Making a release

1. Update `__version__` in `kolibri_games/__init__.py` and add a section to `CHANGELOG.md`
   (through a pull request).
2. On GitHub, go to **Releases > Draft a new release**, type the tag (for example `v0.2.0`),
   choose **Create new tag on publish** with target `main`, give it a title and click
   **Publish release**.
3. GitHub Actions then runs the tests and attaches the plugin, the offline bundle, the game zips
   and checksums to the release (a few minutes). If the release notes are empty, they're filled in
   from the changelog.

## License

MIT. See [LICENSE](LICENSE).
