"""Qt model wrapping a core :class:`~nervus.core.Diagram`.

All edits from the GUI go through this class, so it can tell the views what changed. The methods are
*primitive* operations without undo; controllers wrap them in undo commands.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QPointF, Signal

from nervus.core import Block, Connection, Diagram, SimulationSettings, Variable
from nervus.core.layout import auto_layout


def block_position(block: Block) -> QPointF:
    x, y = block.meta.get("position", (0.0, 0.0))
    return QPointF(float(x), float(y))


class DiagramModel(QObject):
    blockAdded = Signal(object)  # Block
    blockRemoved = Signal(object)  # Block
    blockMoved = Signal(object)  # Block
    blockRenamed = Signal(object, str)  # Block, old name
    paramsChanged = Signal(object)  # Block (parameters changed; ports may have changed too)
    connectionAdded = Signal(object)  # Connection
    connectionRemoved = Signal(object)  # Connection
    settingsChanged = Signal()
    workspaceChanged = Signal()
    diagramReset = Signal()  # a whole new diagram was loaded
    filePathChanged = Signal(object)  # Path | None
    changed = Signal()  # any structural or parameter change

    def __init__(self, diagram: Diagram | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._diagram = diagram or Diagram()
        self._path: Path | None = None
        for sig in (
            self.blockAdded,
            self.blockRemoved,
            self.blockMoved,
            self.blockRenamed,
            self.paramsChanged,
            self.connectionAdded,
            self.connectionRemoved,
            self.settingsChanged,
            self.workspaceChanged,
            self.diagramReset,
        ):
            sig.connect(self.changed)

    # ------------------------------------------------------------------ access

    @property
    def diagram(self) -> Diagram:
        return self._diagram

    @property
    def file_path(self) -> Path | None:
        return self._path

    @file_path.setter
    def file_path(self, path: Path | None) -> None:
        self._path = path
        self.filePathChanged.emit(path)

    @property
    def title(self) -> str:
        return self._path.name if self._path else f"{self._diagram.name}"

    def set_diagram(self, diagram: Diagram, path: Path | None = None) -> None:
        auto_layout(diagram)  # diagrams built in Python have no positions yet
        self._diagram = diagram
        self.diagramReset.emit()
        self.file_path = path

    # ------------------------------------------------------------------ primitive edits

    def add_block(self, block: Block, position: QPointF | None = None) -> Block:
        if position is not None:
            block.meta["position"] = [round(position.x(), 1), round(position.y(), 1)]
        self._diagram.add(block)
        self.blockAdded.emit(block)
        return block

    def remove_block(self, block: Block) -> list[Connection]:
        """Remove ``block`` and its connections. Returns the removed connections (for undo)."""
        conns = [c for c in self._diagram.connections if c.src is block or c.dst is block]
        for c in conns:
            self.remove_connection(c)
        self._diagram.remove(block)
        self.blockRemoved.emit(block)
        return conns

    def move_block(self, block: Block, position: QPointF) -> None:
        block.meta["position"] = [round(position.x(), 1), round(position.y(), 1)]
        self.blockMoved.emit(block)

    def rename_block(self, block: Block, new_name: str) -> None:
        old = block.name
        self._diagram.rename(block, new_name)
        self.blockRenamed.emit(block, old)

    def set_param(self, block: Block, name: str, value: Any) -> None:
        block.set_param(name, value)
        self.paramsChanged.emit(block)

    def set_params(self, block: Block, params: dict[str, Any]) -> None:
        """Set several parameters at once; all-or-nothing."""
        old = dict(block.params)
        try:
            for k, v in params.items():
                block.set_param(k, v)
        except Exception:
            block.params.clear()
            block.params.update(old)
            raise
        self.paramsChanged.emit(block)

    def add_connection(self, src: Block, src_port: int, dst: Block, dst_port: int) -> Connection:
        conn = self._diagram.connect((src, src_port), (dst, dst_port))
        self.connectionAdded.emit(conn)
        return conn

    def restore_connection(self, conn: Connection) -> Connection:
        return self.add_connection(conn.src, conn.src_port, conn.dst, conn.dst_port)

    def remove_connection(self, conn: Connection) -> None:
        self._diagram.disconnect(conn)
        self.connectionRemoved.emit(conn)

    def find_connection(self, src: Block, src_port: int, dst: Block, dst_port: int) -> Connection | None:
        for c in self._diagram.connections:
            if c.src is src and c.src_port == src_port and c.dst is dst and c.dst_port == dst_port:
                return c
        return None

    # ------------------------------------------------------------------ workspace

    def set_variable(self, old_name: str | None, var: Variable | None, index: int | None = None) -> None:
        """Add (``old_name`` None, optionally at ``index``), replace/rename, or delete (``var`` None) a
        workspace variable."""
        ws = self._diagram.workspace
        if var is None:
            if old_name is not None:
                del ws[old_name]
        elif old_name is not None:
            ws.replace(old_name, var)
        elif index is not None:
            ws.insert(index, var)
        else:
            ws.add(var)
        self._workspace_changed()

    def apply_values(self, values: dict[str, object]) -> None:
        self._diagram.workspace.apply(values)
        self._workspace_changed()

    def _workspace_changed(self) -> None:
        ns = None
        with contextlib.suppress(Exception):
            ns = self._diagram.workspace.namespace()
        for b in self._diagram.blocks:
            if b.expressions:
                if ns is not None:
                    with contextlib.suppress(Exception):
                        b.resolve(ns)
                self.paramsChanged.emit(b)
        self.workspaceChanged.emit()

    def set_settings(self, settings: SimulationSettings) -> None:
        settings.validate()
        self._diagram.settings = settings
        self.settingsChanged.emit()
