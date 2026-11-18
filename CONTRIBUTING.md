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
