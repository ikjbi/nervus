"""Undoable edit commands. Every change the user makes to a diagram is one of these."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPointF
from PySide6.QtGui import QUndoCommand

from nervus.core import Block, Connection, SimulationSettings
from nervus.gui.models.diagram_model import DiagramModel, block_position


class Command(QUndoCommand):
    """Base class. Subclasses implement ``do``/``revert``.

    Exceptions raised from Python inside ``redo()`` do not reach the caller of ``QUndoStack.push``, so they are
    caught here: the command stores the error and marks itself obsolete, which makes Qt drop it from the stack.
    """

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.error: Exception | None = None

    def redo(self) -> None:
        self.error = None
        try:
            self.do()
        except Exception as exc:
            self.error = exc
            self.setObsolete(True)

    def undo(self) -> None:
        self.revert()

    def do(self) -> None:
        raise NotImplementedError

    def revert(self) -> None:
        raise NotImplementedError


class AddBlockCommand(Command):
    def __init__(self, model: DiagramModel, block: Block, position: QPointF) -> None:
        super().__init__(f"Add {block.label}")
        self.model, self.block, self.position = model, block, position

    def do(self) -> None:
        self.model.add_block(self.block, self.position)

    def revert(self) -> None:
        self.model.remove_block(self.block)


class RemoveCommand(Command):
    """Remove blocks and/or connections."""

    def __init__(self, model: DiagramModel, blocks: list[Block], connections: list[Connection]) -> None:
        n = len(blocks) + len(connections)
        super().__init__(f"Delete {n} item{'s' if n != 1 else ''}")
        self.model = model
        self.blocks = list(blocks)
        block_set = {id(b) for b in blocks}
        # Connections removed together with their blocks are handled by remove_block.
        self.connections = [c for c in connections if id(c.src) not in block_set and id(c.dst) not in block_set]
        self._removed: list[Connection] = []
        self._positions: list[QPointF] = []

    def do(self) -> None:
        self._removed = []
        for c in self.connections:
            self.model.remove_connection(c)
            self._removed.append(c)
        self._positions = [block_position(b) for b in self.blocks]
        for b in self.blocks:
            self._removed.extend(self.model.remove_block(b))

    def revert(self) -> None:
        for b, pos in zip(self.blocks, self._positions, strict=True):
            self.model.add_block(b, pos)
        restored = []
        for c in self._removed:
            restored.append(self.model.restore_connection(c))
        # The diagram holds new Connection objects now; keep ours in sync for the next redo.
        mapping = dict(zip(map(id, self._removed), restored, strict=True))
        self.connections = [mapping.get(id(c), c) for c in self.connections]


class MoveBlocksCommand(Command):
    def __init__(self, model: DiagramModel, moves: list[tuple[Block, QPointF, QPointF]]) -> None:
        super().__init__(f"Move {len(moves)} block{'s' if len(moves) != 1 else ''}")
        self.model, self.moves = model, moves

    def do(self) -> None:
        for b, _old, new in self.moves:
            self.model.move_block(b, new)

    def revert(self) -> None:
        for b, old, _new in self.moves:
            self.model.move_block(b, old)


class SetParamsCommand(Command):
    """Change block parameters. Connections to ports that disappear (e.g. fewer Sum inputs) are removed."""

    def __init__(self, model: DiagramModel, block: Block, params: dict[str, Any]) -> None:
        super().__init__(f"Change {block.name}")
        self.model, self.block = model, block
        self.new = dict(params)
        self.old = {k: block.params[k] for k in params}
        self._dropped: list[Connection] = []

    def do(self) -> None:
        self.model.set_params(self.block, self.new)
        b = self.block
        self._dropped = [
            c
            for c in self.model.diagram.connections
            if (c.dst is b and c.dst_port >= b.num_inputs()) or (c.src is b and c.src_port >= b.num_outputs())
        ]
        for c in self._dropped:
            self.model.remove_connection(c)

    def revert(self) -> None:
        self.model.set_params(self.block, self.old)
        self._dropped = [self.model.restore_connection(c) for c in self._dropped]


class RenameCommand(Command):
    def __init__(self, model: DiagramModel, block: Block, new_name: str) -> None:
        super().__init__(f"Rename {block.name} to {new_name}")
        self.model, self.block, self.old, self.new = model, block, block.name, new_name

    def do(self) -> None:
        self.model.rename_block(self.block, self.new)

    def revert(self) -> None:
        self.model.rename_block(self.block, self.old)


class ConnectCommand(Command):
    """Connect two ports. If the input is already driven, the old line is replaced."""

    def __init__(self, model: DiagramModel, src: Block, src_port: int, dst: Block, dst_port: int) -> None:
        super().__init__(f"Connect {src.name} to {dst.name}")
        self.model = model
        self.args = (src, src_port, dst, dst_port)
        self._conn: Connection | None = None
        self._replaced: Connection | None = None

    def do(self) -> None:
        src, sp, dst, dp = self.args
        self._replaced = self.model.diagram.driver(dst, dp)
        if self._replaced is not None:
            self.model.remove_connection(self._replaced)
        self._conn = self.model.add_connection(src, sp, dst, dp)

    def revert(self) -> None:
        assert self._conn is not None
        self.model.remove_connection(self._conn)
        if self._replaced is not None:
            self._replaced = self.model.restore_connection(self._replaced)


class SetSettingsCommand(Command):
    def __init__(self, model: DiagramModel, settings: SimulationSettings) -> None:
        super().__init__("Change simulation settings")
        self.model, self.new, self.old = model, settings, model.diagram.settings

    def do(self) -> None:
        self.model.set_settings(self.new)

    def revert(self) -> None:
        self.model.set_settings(self.old)
