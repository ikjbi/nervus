"""Automatic left-to-right layout for diagrams that have no block positions (e.g. built in Python)."""

from __future__ import annotations

from collections.abc import Callable

from nervus.core.block import Block
from nervus.core.diagram import Diagram

COLUMN_GAP = 90.0
ROW_HEIGHT = 110.0
DEFAULT_WIDTH = 70.0

Direction = tuple[int, int]
ORIENTATIONS: dict[str, Direction] = {"right": (1, 0), "down": (0, 1), "left": (-1, 0), "up": (0, -1)}
"""Signal flow direction through a block, from its inputs to its outputs."""


def orientation_of(block: Block) -> str:
    """``right`` (default), ``down``, ``left`` or ``up``. Stored as ``meta["vertical"]`` (rotated a quarter turn)
    and ``meta["flipped"]`` (mirrored), so models from before rotation existed keep their flipped blocks."""
    vertical, flipped = bool(block.meta.get("vertical")), bool(block.meta.get("flipped"))
    return ("up" if flipped else "down") if vertical else ("left" if flipped else "right")


def rotated_meta(orientation: str) -> dict[str, bool]:
    """The ``vertical``/``flipped`` meta entries for one orientation."""
    return {"vertical": orientation in ("down", "up"), "flipped": orientation in ("left", "up")}


ROTATE_CLOCKWISE = {"right": "down", "down": "left", "left": "up", "up": "right"}


def _feedback_edges(diagram: Diagram) -> set[tuple[int, int]]:
    """Edges that close a cycle when walking from the sources (found with a depth-first search)."""
    blocks = diagram.blocks
    succ: dict[int, list[int]] = {id(b): [] for b in blocks}
    for c in diagram.connections:
        succ[id(c.src)].append(id(c.dst))
    state: dict[int, int] = {}  # 1 = on the stack, 2 = done
    back: set[tuple[int, int]] = set()
    roots = [b for b in blocks if b.num_inputs() == 0] + blocks

    for root in roots:
        if id(root) in state:
            continue
        stack: list[tuple[int, int]] = [(id(root), 0)]
        state[id(root)] = 1
        while stack:
            node, i = stack[-1]
            if i < len(succ[node]):
                stack[-1] = (node, i + 1)
                nxt = succ[node][i]
                if state.get(nxt) == 1:
                    back.add((node, nxt))
                elif nxt not in state:
                    state[nxt] = 1
                    stack.append((nxt, 0))
            else:
                state[node] = 2
                stack.pop()
    return back


def auto_layout(diagram: Diagram, only_missing: bool = True, width_of: Callable[[Block], float] | None = None) -> int:
    """Place blocks in columns by signal-flow depth. Returns how many blocks were placed.

    With ``only_missing`` (the default), blocks that already have a position are left alone, and nothing is
    done unless at least one block lacks a position. ``width_of`` gives a block's drawn width (the editor
    passes its real sizes) so wide blocks such as subsystems get room.
    """
    width = width_of or (lambda b: DEFAULT_WIDTH)
    blocks = diagram.blocks
    missing = [b for b in blocks if "position" not in b.meta]
    if only_missing and not missing:
        return 0
    targets = missing if only_missing else blocks
    back = _feedback_edges(diagram)
    preds: dict[int, list[int]] = {id(b): [] for b in blocks}
    for c in diagram.connections:
        if (id(c.src), id(c.dst)) not in back:
            preds[id(c.dst)].append(id(c.src))

    depth: dict[int, int] = {}

    def level(n: int, seen: frozenset[int] = frozenset()) -> int:
        if n in depth:
            return depth[n]
        if n in seen:
            return 0
        d = 1 + max((level(p, seen | {n}) for p in preds[n]), default=-1)
        depth[n] = d
        return d

    columns: dict[int, list[Block]] = {}
    for b in blocks:
        columns.setdefault(level(id(b)), []).append(b)
    target_ids = {id(b) for b in targets}
    x = 0.0
    for col in sorted(columns):
        members = columns[col]
        for row, b in enumerate(members):
            if id(b) in target_ids:
                b.meta["position"] = [round(x / 10) * 10, row * ROW_HEIGHT]
        x += max(width(b) for b in members) + COLUMN_GAP
    return len(targets)
