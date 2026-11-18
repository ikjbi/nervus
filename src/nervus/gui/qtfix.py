"""Work around Qt failing to start when its plugin files carry the macOS "hidden" file flag.

Qt skips hidden files when it looks for plugins, so with the flag set no platform plugin is found and the
application aborts ("Could not find the Qt platform plugin"). Some tools set the flag on everything inside a
``.venv`` folder. This clears it on Qt's plugin folder only. It must run before the QApplication is created.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path


def unhide_qt_plugins() -> int:
    """Clear the hidden flag on Qt plugin files. Returns the number of files changed (0 off macOS)."""
    hidden = getattr(stat, "UF_HIDDEN", 0)
    if sys.platform != "darwin" or not hidden or not hasattr(os, "chflags"):
        return 0
    from PySide6.QtCore import QLibraryInfo

    root = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    changed = 0
    for path in [root, *root.rglob("*")]:
        try:
            flags = os.stat(path, follow_symlinks=False).st_flags
            if flags & hidden:
                os.chflags(path, flags & ~hidden, follow_symlinks=False)
                changed += 1
        except OSError:
            continue
    return changed
