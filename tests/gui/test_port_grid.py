"""Ports sit on the grid, so the ports of any two blocks can be lined up and the wire drawn straight."""

from PySide6.QtCore import QPointF

from nervus.blocks.registry import _REGISTRY
from nervus.gui.views.items import GRID


def _on_grid(v: float) -> bool:
    return abs(v / GRID - round(v / GRID)) < 1e-6


def test_ports_of_every_block_are_on_the_grid(window) -> None:  # type: ignore[no-untyped-def]
    bad, checked = [], 0
    for type_id in sorted(_REGISTRY):
        try:
            block = window.editor.add_block(type_id, QPointF(30, 50))
        except Exception:  # blocks that need a file or a parent model to exist
            continue
        if block is None:
            continue
        item = window.scene.blocks[id(block)]
        for meta in ({}, {"vertical": True}):
            block.meta.update(meta)
            item.refresh()
            for port in item.in_ports + item.out_ports + item.phys_ports:
                local, p = port.pos(), port.scenePos()
                on_side = local.x() <= 0 or local.x() >= item._w  # left/right edge: the wire leaves horizontally
                across = p.y() if on_side else p.x()  # the coordinate that must match the other block's port
                checked += 1
                if not _on_grid(across):
                    bad.append(f"{type_id} {meta}: port at {p.x()}, {p.y()}")
    assert checked > 200 and bad == []
