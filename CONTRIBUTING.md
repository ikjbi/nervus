# Contributing to Nervus

## Setup

```bash
uv sync --extra gui
uv run pre-commit install
```

## Workflow

1. Pick an item from [`plan.md`](plan.md), or open an issue.
2. Write the code **and** its tests **and** its documentation, both in the app and on GitHub:
   - block docstrings (shown in the in-app help and the generated reference), with LaTeX equations,
   - in-app guide pages in `src/nervus/gui/resources/help/`,
   - user docs in `docs/`, with pictures where they help:
     `uv run python scripts/gen_figures.py` (block figures) and
     `QT_QPA_PLATFORM=offscreen uv run python scripts/screenshots.py` (editor screenshots),
   - then `uv run python scripts/gen_block_reference.py`.
3. Run the checks:
   ```bash
   uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
   ```
4. Tick the item off in `plan.md` and add an entry to `CHANGELOG.md` under *Unreleased*.
5. Commit with a descriptive message.

## Architecture rules

- `nervus.core`, `nervus.sim`, `nervus.solvers`, `nervus.blocks` and `nervus.io` **must never import Qt**.
- The GUI (`nervus.gui`) follows Model–View–Controller:
  - *models* wrap the core diagram and emit Qt signals when it changes,
  - *views* render and forward user input, with no business logic,
  - *controllers* change the model through undoable commands.
- Every block must be verified by tests, against analytical solutions where possible.

## Writing a block

See [docs/developer/custom-blocks.md](docs/developer/custom-blocks.md).

## Releasing

Releases go to PyPI from GitHub Actions (`.github/workflows/release.yml`), with
[trusted publishing](https://docs.pypi.org/trusted-publishers/): no password or token is stored.

One-time setup:

1. On pypi.org, log in and open *Your account → Publishing → Add a new pending publisher*: PyPI project name
   `nervus`, owner `ikjbi`, repository `nervus`, workflow `release.yml`, environment `pypi`.
2. On GitHub, *Settings → Environments → New environment* `pypi` (optionally with a required reviewer, so every
   release waits for a click).

Each release:

1. Set `__version__` in `src/nervus/__init__.py` (e.g. `0.1.0`), and in `CHANGELOG.md` rename *Unreleased* to the
   version with the date.
2. Commit, then tag and push: `git tag v0.1.0 && git push origin v0.1.0`.
3. The workflow checks that the tag matches the version, runs the tests, builds the wheel and the source package,
   checks them with `twine check`, and publishes them.

Try a package before releasing: `uv build`, then `pip install "dist/nervus-<version>-py3-none-any.whl[gui]"` in a
fresh environment, and `nervus --copy-examples /tmp/ex`.
