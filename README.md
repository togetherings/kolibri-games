# Kolibri Games

A [Kolibri](https://learningequality.org/kolibri/) plugin that turns Kolibri into a home for
offline learning games, built with [Internet-in-a-Box](https://internet-in-a-box.org/) in mind.

- **Games are content, not code in the plugin.** Every game is a zip of web files, so adding a
  game never means changing the plugin.
- **Three kinds of game.**
  - *Saved Games* keep each learner's progress.
  - *Scored Games* also keep scores: one score, or several (like accuracy and speed), with a
    scoreboard for each level or lesson and one for the whole game.
  - *Server Games*, like Wiki BLAZE and BeaconHunt, need this plugin's server to run their rules.
- **Saved and Scored Games are added through Kolibri Studio**, as ordinary HTML5 apps in a
  channel. Learners open them from Learn (also offline in the Kolibri app), coaches assign them
  in lessons, and the games page shows Scored Games' scoreboards from the scores they save. Make
  them with [EduGame Kit](https://github.com/togetherings/edugame-kit).
- **Server Games are installed on the games page**, because they can't go through Studio.
- **Challenges.** Coaches set a game up for a class, with its own settings, dates and scoreboard.
- **Learners sign in with Kolibri.** Results are saved to their account.
- **Coaches stay in control.** They can see every learner's attempts and moves, export results
  as CSV, choose which attempt counts (first, best, latest, or all of them added up), hide or
  anonymise scoreboards, set time limits, change each game's options, and give a learner a
  fresh start.
- **Light enough for a Raspberry Pi**, and works fully offline.

## Games

| Game | Kind | What it is | Where to get it |
|---|---|---|---|
| **Wiki BLAZE** (Browsing Links A-to-Z Exploration) | Server Game | Race from one Wikipedia article to another by following links, using the Wikipedia file already on the device. See [docs/WIKI_BLAZE.md](docs/WIKI_BLAZE.md). | Attached to each [release](https://github.com/togetherings/kolibri-games/releases) here |
| **[BeaconHunt](https://github.com/togetherings/beacon-hunt)** | Server Game | Guess where in the world a street photo was taken. | Its releases |
| **[Lessons In Typing](https://github.com/togetherings/lit)** (LIT) | Scored Game | Touch-typing lessons in several languages and keyboard layouts, scored by accuracy and speed. | Its releases, through Kolibri Studio |
| **[Studies In Geography](https://github.com/togetherings/singe)** (SINGE) | Scored Game | Find regions, capitals and flags on maps. | Its releases, through Kolibri Studio |
| **[Sparkle](https://github.com/togetherings/sparkle)** | Scored Game | Guess the hidden word from letter clues: a new word every day, plus practice words. | Its releases |
| **[BoBo Na Mi](https://github.com/togetherings/bobo-na-mi)** | Saved Game | Push words to change the rules and solve puzzles. | Coming soon |
| **[Number Hunt and Memory Match](https://github.com/togetherings/edugame-kit/tree/main/examples)** | Scored Games | Small example games. | EduGame Kit |

**[EduGame Kit](https://github.com/togetherings/edugame-kit)** is how Saved and Scored Games are
made: one zip that works in Kolibri channels, the Kolibri Games scoreboards, Moodle and other
learning systems, RACHEL, Sugarizer and Kiwix.

Example manifests for Lessons In Typing and Studies In Geography, which keep their scores their
own way, are in [examples/channel-games](examples/channel-games).

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

- **Saved and Scored Games: through Kolibri Studio.** Upload the game's zip to a channel in
  [Kolibri Studio](https://studio.learningequality.org/) (**Add > Upload files**), publish the
  channel, and import it on the device. Learners find the games in Learn, and Scored Games appear
  on the games page with their scoreboards. See [docs/CHANNEL_GAMES.md](docs/CHANNEL_GAMES.md).
- **Server Games: on the games page.** Open **Setup**, choose the game's `.zip` file and click
  **Install**. Installing a newer version keeps the old one, so you can go back. (Copying the
  zip into `<KOLIBRI_HOME>/kolibri_games/games/` works too; on IIAB that's
  `/library/kolibri/kolibri_games/games/`.) Only device administrators can install games.
- **Wiki BLAZE** also needs a Wikipedia `.zim` file, and **BeaconHunt** a photo pack: choose them
  on the Setup page.

Administrators can see why a game can't be played on the Setup page, or with:

```bash
sudo -u kolibri KOLIBRI_HOME=/library/kolibri kolibri manage kolibri_games_check
```

## Making games

- **Saved and Scored Games:** start with [EduGame Kit](https://github.com/togetherings/edugame-kit).
  To show scoreboards for an existing HTML5 app that saves scores its own way in SCORM
  `cmi.suspend_data`, add a `kolibri-game.json` that says how to read them: see
  **[docs/CHANNEL_GAMES.md](docs/CHANNEL_GAMES.md)**.
- **Server Games:** a zip with a `kolibri-game.json` manifest and ordinary web files, using the
  plugin's JavaScript SDK and one of its services. See **[docs/GAME_FORMAT.md](docs/GAME_FORMAT.md)**,
  and **[docs/SCORING.md](docs/SCORING.md)** for how scores are described and ranked.

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
3. GitHub Actions then runs the tests and attaches the plugin, the offline bundle, the Wiki BLAZE
   zip and checksums to the release (a few minutes). If the release notes are empty, they're filled in
   from the changelog.

## License

MIT. See [LICENSE](LICENSE).
