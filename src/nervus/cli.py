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


USAGE = """\
usage: nervus [model.nervus]          start the editor (and open a model)
       nervus --copy-examples DIR     copy the example models and scripts to DIR, to run and change them
       nervus --version
"""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv[1:])
    if args[:1] in (["-h"], ["--help"]):
        print(USAGE)
        return 0
    if args[:1] == ["--version"]:
        from nervus import __version__

        print(f"nervus {__version__}")
        return 0
    if args[:1] == ["--copy-examples"]:
        from nervus.examples import copy_examples

        if len(args) != 2:
            print(USAGE, file=sys.stderr)
            return 2
        try:
            out = copy_examples(args[1])
        except FileExistsError as exc:
            print(f"nervus: {exc}", file=sys.stderr)
            return 1
        print(f"Copied the examples to {out}. Open one with: nervus {out / 'cruise_control.nervus'}")
        return 0
    try:
        import PySide6  # noqa: F401
    except ImportError:
        print(GUI_MISSING, file=sys.stderr)
        return 1
    from nervus.gui.app import main as gui_main

    return gui_main(argv)
