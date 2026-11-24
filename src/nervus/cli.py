"""The ``nervus`` command: starts the desktop editor, or says how to install it."""

from __future__ import annotations

import sys

GUI_MISSING = """\
Nervus: the desktop editor needs PySide6, which is not installed in this environment.

Install the editor's packages (the "gui" extra) and start it again:

    uv sync --extra gui
    uv run nervus

or in one step:  uv run --extra gui nervus
(with pip:  pip install -e ".[gui]")
"""


def main(argv: list[str] | None = None) -> int:
    try:
        import PySide6  # noqa: F401
    except ImportError:
        print(GUI_MISSING, file=sys.stderr)
        return 1
    from nervus.gui.app import main as gui_main

    return gui_main(argv)
