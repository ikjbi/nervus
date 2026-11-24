"""The example models and scripts that come with Nervus.

From a source checkout they are in ``examples/`` of the repository; an installed Nervus (``pip install nervus``) has
them in the package. The example scripts write files next to themselves (results, generated code), so to run them,
copy them to a folder of your own first: ``nervus --copy-examples ~/nervus-examples``.
"""

from __future__ import annotations

import shutil
from pathlib import Path


def examples_dir() -> Path:
    """Where the examples are: the repository's ``examples/`` folder, or the installed package's copy."""
    here = Path(__file__).resolve().parent
    checkout = here.parent.parent / "examples"  # src/nervus/ -> the repository
    if (checkout / "cruise_control.nervus").exists():
        return checkout
    return here / "examples"


def copy_examples(target: str | Path) -> Path:
    """Copy the examples to ``target`` (a new or empty folder), to run and change them there."""
    out = Path(target).expanduser()
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"{out} is not empty; choose a new folder")
    shutil.copytree(examples_dir(), out, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.fmu"))  # fmt: skip
    return out
