"""Editing operations on the diagram, all undoable."""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QObject, QPointF, Signal
from PySide6.QtGui import QUndoStack

from nervus.blocks import create_block, get_block_class
from nervus.core import Block, Connection, NervusError, SimulationSettings
from nervus.gui.controllers.commands import (
    AddBlockCommand,
    Command,
    ConnectCommand,
    MoveBlocksCommand,
    RemoveCommand,
    RenameCommand,
    SetParamsCommand,
    SetSettingsCommand,
)
from nervus.gui.models.diagram_model import DiagramModel, block_position

CLIPBOARD_MIME = "application/x-nervus-blocks"


class EditorController(QObject):
    errorOccurred = Signal(str)
    editingEnabledChanged = Signal(bool)

    def __init__(self, model: DiagramModel, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.model = model
        self.undo_stack = QUndoStack(self)
        self._editing_enabled = True
        model.diagramReset.connect(self.undo_stack.clear)

    # ------------------------------------------------------------------ state

    @property
    def editing_enabled(self) -> bool:
        return self._editing_enabled

    def set_editing_enabled(self, enabled: bool) -> None:
        """Editing is disabled while a simulation runs."""
        if enabled != self._editing_enabled:
            self._editing_enabled = enabled
            self.editingEnabledChanged.emit(enabled)

    def _push(self, cmd: Command) -> bool:
        if not self._editing_enabled:
            self.errorOccurred.emit("The diagram cannot be edited while a simulation is running.")
            return False
        self.undo_stack.push(cmd)  # an obsolete (failed) command is dropped by Qt
        if cmd.error is not None:
            self.errorOccurred.emit(str(cmd.error))
            return False
        return True

    # ------------------------------------------------------------------ operations

    def add_block(self, type_id: str, position: QPointF, **params: Any) -> Block | None:
        try:
            block = create_block(type_id, **params)
        except (NervusError, KeyError) as exc:
            self.errorOccurred.emit(str(exc))
            return None
        return block if self._push(AddBlockCommand(self.model, block, position)) else None

    def delete(self, blocks: list[Block], connections: list[Connection]) -> None:
        if blocks or connections:
            self._push(RemoveCommand(self.model, blocks, connections))

    def move_blocks(self, moves: list[tuple[Block, QPointF, QPointF]]) -> None:
        moves = [(b, o, n) for b, o, n in moves if o != n]
        if moves:
            self._push(MoveBlocksCommand(self.model, moves))

    def set_params(self, block: Block, params: dict[str, Any]) -> bool:
        changed = {k: v for k, v in params.items() if not _same(block.params.get(k), v)}
        if not changed:
            return True
        try:  # validate on a scratch copy first, so a bad value never reaches the undo stack
            probe = type(block)(**{**block.params, **changed})
            del probe
        except (NervusError, ValueError, TypeError) as exc:
            self.errorOccurred.emit(f"{block.name}: {exc}")
            return False
        return self._push(SetParamsCommand(self.model, block, changed))

    def rename(self, block: Block, new_name: str) -> bool:
        new_name = new_name.strip()
        if new_name == block.name:
            return True
        if not new_name:
            self.errorOccurred.emit("Block names cannot be empty.")
            return False
        if new_name in self.model.diagram:
            self.errorOccurred.emit(f"A block named '{new_name}' already exists.")
            return False
        return self._push(RenameCommand(self.model, block, new_name))

    def connect_ports(self, src: Block, src_port: int, dst: Block, dst_port: int) -> bool:
        if self.model.find_connection(src, src_port, dst, dst_port):
            return True
        return self._push(ConnectCommand(self.model, src, src_port, dst, dst_port))

    def set_settings(self, settings: SimulationSettings) -> bool:
        try:
            settings.validate()
        except ValueError as exc:
            self.errorOccurred.emit(str(exc))
            return False
        return self._push(SetSettingsCommand(self.model, settings))

    # ------------------------------------------------------------------ clipboard

    def copy_to_text(self, blocks: list[Block]) -> str:
        names = {b.name for b in blocks}
        data = {
            "blocks": [
                {"name": b.name, "type": b.type_id, "params": b.params_jsonable(), "meta": dict(b.meta)} for b in blocks
            ],
            "connections": [
                {"src": c.src.name, "src_port": c.src_port, "dst": c.dst.name, "dst_port": c.dst_port}
                for c in self.model.diagram.connections
                if c.src.name in names and c.dst.name in names
            ],
        }
        return json.dumps(data)

    def paste_from_text(self, text: str, offset: QPointF | None = None) -> list[Block]:
        offset = offset if offset is not None else QPointF(30, 30)
        try:
            data = json.loads(text)
            entries = data["blocks"]
        except (ValueError, KeyError, TypeError):
            return []
        if not self._editing_enabled:
            self.errorOccurred.emit("The diagram cannot be edited while a simulation is running.")
            return []
        created: dict[str, Block] = {}
        self.undo_stack.beginMacro("Paste")
        try:
            for e in entries:
                try:
                    block = get_block_class(e["type"])(**e.get("params", {}))
                except (NervusError, KeyError) as exc:
                    self.errorOccurred.emit(str(exc))
                    continue
                block.name = self.model.diagram.unique_name(e.get("name") or block.label)
                block.meta = dict(e.get("meta", {}))
                pos = block_position(block) + offset
                self.undo_stack.push(AddBlockCommand(self.model, block, pos))
                created[e.get("name", "")] = block
            for c in data.get("connections", []):
                src, dst = created.get(c["src"]), created.get(c["dst"])
                if src and dst:
                    self.undo_stack.push(ConnectCommand(self.model, src, c["src_port"], dst, c["dst_port"]))
        finally:
            self.undo_stack.endMacro()
        return list(created.values())


def _same(a: Any, b: Any) -> bool:
    try:
        import numpy as np

        return bool(np.array_equal(np.asarray(a), np.asarray(b))) if a is not None else False
    except (TypeError, ValueError):
        return a == b
