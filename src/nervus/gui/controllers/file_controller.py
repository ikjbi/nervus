"""New / open / save, and the recent-files list."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Signal

from nervus.core import Diagram, NervusError
from nervus.gui.controllers.editor_controller import EditorController
from nervus.gui.models.diagram_model import DiagramModel
from nervus.io import FILE_EXTENSION, load, save

MAX_RECENT = 10


class FileController(QObject):
    errorOccurred = Signal(str)
    recentFilesChanged = Signal(list)
    saved = Signal(object)  # Path

    def __init__(
        self,
        model: DiagramModel,
        editor: EditorController,
        settings: QSettings | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.model = model
        self.editor = editor
        self.settings = settings or QSettings("Nervus", "Nervus")

    @property
    def is_modified(self) -> bool:
        return not self.editor.undo_stack.isClean()

    def new(self) -> None:
        self.model.set_diagram(Diagram("untitled"), None)
        self.editor.undo_stack.setClean()

    def open(self, path: str | Path) -> bool:
        p = Path(path)
        try:
            diagram = load(p)
        except (OSError, NervusError) as exc:
            self.errorOccurred.emit(f"Could not open {p.name}:\n{exc}")
            return False
        self.model.set_diagram(diagram, p)
        self.editor.undo_stack.setClean()
        self._add_recent(p)
        return True

    def save(self) -> bool:
        """Save to the current path. Returns False if there is no path yet (the view should ask for one)."""
        if self.model.file_path is None:
            return False
        return self.save_as(self.model.file_path)

    def save_as(self, path: str | Path) -> bool:
        p = Path(path)
        if not p.suffix:
            p = p.with_suffix(FILE_EXTENSION)
        if self.model.root.name in ("", "untitled"):
            self.model.root.name = p.stem
        try:
            p = save(self.model.root, p)
        except OSError as exc:
            self.errorOccurred.emit(f"Could not save {p.name}:\n{exc}")
            return False
        self.model.file_path = p
        self.editor.undo_stack.setClean()
        self._add_recent(p)
        self.saved.emit(p)
        return True

    # ------------------------------------------------------------------ recent files

    def recent_files(self) -> list[Path]:
        raw = self.settings.value("recentFiles", [])
        items: list[str] = [raw] if isinstance(raw, str) else [str(x) for x in raw] if isinstance(raw, list) else []
        return [Path(x) for x in items if Path(x).exists()]

    def _add_recent(self, path: Path) -> None:
        files = [str(path.resolve())] + [str(p) for p in self.recent_files() if p.resolve() != path.resolve()]
        self.settings.setValue("recentFiles", files[:MAX_RECENT])
        self.recentFilesChanged.emit(self.recent_files())

    def clear_recent(self) -> None:
        self.settings.setValue("recentFiles", [])
        self.recentFilesChanged.emit([])
