# Kolibri Games

A [Kolibri](https://learningequality.org/kolibri/) plugin that turns Kolibri into a home for
offline learning games, built with [Internet-in-a-Box](https://internet-in-a-box.org/) in mind.

- **Games are content, not code in the plugin.** Each game is a small ZIM file, so it can be
  shared through a Kolibri channel or copied onto a device.
- **Learners sign in with Kolibri.** Results are saved to their account, with leaderboards per
  facility or class.
- **Scores can be trusted.** Games run in a locked-down sandbox, and a game can have a *rule
  checker* on the server that keeps secrets and works out the score itself.
- **Coaches stay in control.** They can see every learner's attempts and moves, export results
  as CSV, choose whether the first or best attempt counts, hide or anonymise leaderboards, set
  time limits, change each game's options, and give a learner a fresh start.

Version 0.1.0 comes with two sample games: **Number Hunt** (scores checked by the server) and
**Memory Match** (scores reported by the game).

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
Run the same command again to update; add `--version 0.1.0` to install a particular release, or
`--uninstall` to remove the plugin.

Then open **`http://<your server>/kolibri/en/kolibri_games/`** (on IIAB, usually
`http://box.lan/kolibri/en/kolibri_games/`). Learners sign in with their Kolibri account.

### Adding games

- **From a channel:** import a Kolibri channel that contains game ZIMs. Every game in an
  imported channel appears on the games page automatically.
- **From a file:** copy a game's `.zim` file into `<KOLIBRI_HOME>/kolibri_games/games/`
  (on IIAB: `/library/kolibri/kolibri_games/games/`).

The sample games are attached to each [release](https://github.com/togetherings/kolibri-games/releases)
as `.zim` files. Administrators can see where games are loaded from, and why a game can't be
played, under **Setup** on the games page or with:

```bash
sudo -u kolibri KOLIBRI_HOME=/library/kolibri kolibri manage kolibri_games_check
```

## Making games

A game is a folder with a `kolibri-game.json` manifest and ordinary web files (HTML, JavaScript,
CSS, images), using a small JavaScript SDK to start attempts, report moves and finish with a
score. See **[docs/GAME_FORMAT.md](docs/GAME_FORMAT.md)**.

```bash
pip install kolibri-games        # or: pip install -e . in this repository
kolibri-games-preview games/     # try games in a browser without Kolibri
kolibri-games-pack games/my-game # package as dist/<id>_<version>.zim
```

## How it works

See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** for the design, including the sandbox, the
rule checkers, how results are stored, and what's planned next.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e . pytest
python -m pytest                 # unit tests (no Kolibri needed)
python -m tests.e2e_browser      # plays both games in Chromium (needs playwright)
```

With Kolibri installed in the same environment:

```bash
kolibri plugin enable kolibri_games
kolibri manage migrate
KOLIBRI_GAMES_PATH=$PWD/games kolibri start --foreground
```

GitHub Actions runs the unit tests, the browser test, an integration test inside a real
Kolibri, and the installer on an IIAB-like system for every pull request. Pushing a tag like
`v0.1.0` builds and publishes a release.

## License

MIT. See [LICENSE](LICENSE).
