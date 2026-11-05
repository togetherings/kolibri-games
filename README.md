# Kolibri Games

A [Kolibri](https://learningequality.org/kolibri/) plugin that turns Kolibri into a home for
offline learning games, built with [Internet-in-a-Box](https://internet-in-a-box.org/) in mind.

- **Games are content, not code in the plugin.** Every game is a zip of web files, so adding a
  game never means changing the plugin.
- **Three kinds of game.** *Saved Games* keep each learner's progress. *Scored Games* also keep a
  score, for scoreboards and challenges. *Server Games*, like Wiki BLAZE, need this plugin's server
  to run their rules. Any of them can be installed on the games page. Saved and Scored Games can
  also be ordinary HTML5 apps in Kolibri channels, which learners open from Learn and coaches
  assign in lessons; the games page shows scoreboards from the scores they save.
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
More games:

- **[BeaconHunt](https://github.com/togetherings/beacon-hunt)**: guess where a street photo was
  taken (a Server Game).
- Saved and Scored Games made with **[EduGame Kit](https://github.com/togetherings/edugame-kit)**,
  which also work in Moodle, RACHEL, Sugarizer and Kiwix.

Example manifests for Scored Games in channels (Lessons In Typing and Studies In Geography) are
in [examples/channel-games](examples/channel-games).

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

- **On the games page:** open **Setup**, choose the game's `.zip` file and click
  **Install**. Installing a newer version keeps the old one, so you can go back. (Copying the
  zip into `<KOLIBRI_HOME>/kolibri_games/games/` works too; on IIAB that's
  `/library/kolibri/kolibri_games/games/`.) Only device administrators can install games.
- **In a channel:** import a Kolibri channel that contains Saved or Scored Games. Learners find
  them in Learn, and Scored Games appear on the games page automatically.
- **Wiki BLAZE** also needs a Wikipedia `.zim` file: choose it on the Setup page.

The games are attached to each [release](https://github.com/togetherings/kolibri-games/releases)
as `.zip` files. Administrators can see why a game can't be played on the Setup page, or with:

```bash
sudo -u kolibri KOLIBRI_HOME=/library/kolibri kolibri manage kolibri_games_check
```

## Making games

A game is a zip with a `kolibri-game.json` manifest and ordinary web files (HTML, JavaScript,
CSS, images). On the games page it uses a small JavaScript SDK to save progress, start attempts,
report moves and finish with a score. See **[docs/GAME_FORMAT.md](docs/GAME_FORMAT.md)**.

To make a Saved or Scored Game, start with [EduGame Kit](https://github.com/togetherings/edugame-kit).
To show scoreboards for an existing HTML5 app that saves scores in SCORM `cmi.suspend_data`, add a
`kolibri-game.json` that says how to read them. See **[docs/CHANNEL_GAMES.md](docs/CHANNEL_GAMES.md)**.

```bash
pip install -e ".[wikipedia]"    # in this repository
kolibri-games-preview games/ --wikipedia examples/tiny-wiki     # try games without Kolibri
kolibri-games-preview games/ --channel examples/channel-games/preview.json  # with games in channels
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
