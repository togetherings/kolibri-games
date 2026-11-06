# Notes for working on this repository

- Python package: `kolibri_games/`. Kolibri plugin name: `kolibri_games`.
- Keep `service.py`, `ranking.py`, `channel.py`, `wiki.py`, `wikirace.py`, `photos.py`, `photoguess.py`, `install.py`, `manifest.py`,
  `registry.py`, `sources.py`, `views_common.py` free of Django imports; Django code lives in `models.py`, `store_django.py`,
  `views.py`, `urls.py`, `management/`.
- `devserver.py` mirrors the API in `views.py` with the memory store. Change both together.
- Keep it light for a Raspberry Pi running other services: no heavy dependencies, cache with limits,
  and give slow work limits and pauses (see wiki.shortest_route).
- Tests: `python -m pytest` (unit), `python -m tests.e2e_browser` (Playwright, preview server),
  `tests/integration/smoke.py` (inside a real Kolibri; see .github/workflows/ci.yml).
- Bump `__version__` in `kolibri_games/__init__.py` and add a CHANGELOG entry before a release.
  Releases are published by a person in GitHub's Releases page (tag `vX.Y.Z`); the Release
  workflow then builds and attaches the files. Claude sessions can't create tags or releases.
- Three kinds of game (manifest `type`): Saved, Scored and Server Games. Saved and Scored Games are
  made with edugame-kit (github.com/togetherings/edugame-kit) and reach Kolibri through Kolibri Studio
  (channels); Server Games use a service here and are installed on the games page. Docs should send
  Saved and Scored Games through Studio, not the Setup page.
- Scores: `scoring.py` (the one `scoring` spec: fields, rank_by, counts, boards, saved_data) and
  `ranking.py` (ranking for attempts and channel saves). The kit writes this spec and saves boards as
  lists in field order, "_" keys for its own save: change both repos together.
- Never send scores to Kolibri itself (SCORM score.raw is read as completion); games set `passed`.
- Games we keep working: LIT, SINGE (channels, their own save formats; examples/channel-games),
  Sparkle (games page, scoring short form, counts "best" on a running total), BeaconHunt and Wiki
  BLAZE (Server Games). BoBo Na Mi will be a Saved Game.
- Writing style for anything users see: plain words, sentence case, active voice.
- BeaconHunt (github.com/togetherings/beacon-hunt) uses the photo-guess service; the photo-pack
  format in docs/PHOTO_PACKS.md is shared with its pack tool, so change both together.
