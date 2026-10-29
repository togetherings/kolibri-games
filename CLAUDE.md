# Notes for working on this repository

- Python package: `kolibri_games/`. Kolibri plugin name: `kolibri_games`.
- Keep `service.py`, `ranking.py`, `lessons.py`, `manifest.py`, `registry.py`, `sources.py`, `views_common.py`,
  `validators/` free of Django imports; Django code lives in `models.py`, `store_django.py`,
  `views.py`, `urls.py`, `management/`.
- `devserver.py` mirrors the API in `views.py` with the memory store. Change both together.
- Tests: `python -m pytest` (unit), `python -m tests.e2e_browser` (Playwright, preview server),
  `tests/integration/smoke.py` (inside a real Kolibri; see .github/workflows/ci.yml).
- Bump `__version__` in `kolibri_games/__init__.py` and add a CHANGELOG entry before a release.
  Releases are published by a person in GitHub's Releases page (tag `vX.Y.Z`); the Release
  workflow then builds and attaches the files. Claude sessions can't create tags or releases.
- Writing style for anything users see: plain words, sentence case, active voice.
