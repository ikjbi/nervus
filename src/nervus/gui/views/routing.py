"""Orthogonal wire routing around blocks (pure geometry, no Qt).

The editor first tries the simple route (:func:`simple_route`). Only if that passes through a block does it
search for a route around the blocks with A* over a sparse grid: the candidate x and y coordinates are the
edges of the blocks (plus a margin) and the ends of the wire, so a route needs few nodes. The cost is the
length plus a penalty for every bend, which gives short routes with few corners.
"""

from __future__ import annotations

import heapq
from collections.abc import Callable, Sequence
from itertools import pairwise

Point = tuple[float, float]
Direction = tuple[int, int]
Rect = tuple[float, float, float, float]  # left, top, right, bottom

STUB = 10.0
MARGIN = 10.0
BEND_PENALTY = 30.0


def _snap(v: float, grid: float = 10.0) -> float:
    return round(v / grid) * grid


def _identity(x: float, y: float) -> Point:
    return (x, y)


def _mirror(x: float, y: float) -> Point:
    return (-x, y)


def _quarter_ccw(x: float, y: float) -> Point:
    return (y, -x)


def _quarter_cw(x: float, y: float) -> Point:
    return (-y, x)


_FRAMES: dict[Direction, tuple[Callable[[float, float], Point], Callable[[float, float], Point]]] = {
    (1, 0): (_identity, _identity),
    (-1, 0): (_mirror, _mirror),
    (0, 1): (_quarter_ccw, _quarter_cw),  # (0, 1) -> (1, 0) and back
    (0, -1): (_quarter_cw, _quarter_ccw),
}


def simple_route(a: Point, b: Point, da: Direction, db: Direction) -> list[Point]:
    """The default route from ``a`` (signal leaving in direction ``da``) to ``b`` (entering in ``db``)."""
    fwd, back = _FRAMES[da]
    dbx, dby = fwd(*db)
    pts = _route_right(fwd(*a), fwd(*b), (round(dbx), round(dby)))
    return [back(*p) for p in pts]


def _route_right(a: Point, b: Point, db: Direction) -> list[Point]:
    """Corner points from ``a`` (signal leaving to the right) to ``b``, entering ``b`` in direction ``db``."""
    (ax, ay), (bx, by) = a, b
    if db == (1, 0):
        if bx - ax >= 2 * STUB:
            mx = _snap((ax + bx) / 2)
            return [a, (mx, ay), (mx, by), b]
        # Backwards (feedback) wire: go out, loop below/above, come back in.
        out_x, in_x = ax + 2 * STUB, bx - 2 * STUB
        detour_y = max(ay, by) + 40 if abs(ay - by) < 30 else (ay + by) / 2
        return [a, (out_x, ay), (out_x, detour_y), (in_x, detour_y), (in_x, by), b]
    if db == (-1, 0):
        # Out of one side and into the same side of the other block (typical for a flipped feedback block):
        # go past both, then turn back.
        x = max(ax, bx) + 2 * STUB
        return [a, (x, ay), (x, by), b]
    # Into a port on the top (db = down) or bottom (db = up) of a rotated block.
    sy = db[1]
    if bx - ax >= STUB and (by - ay) * sy >= STUB:
        return [a, (bx, ay), b]  # one corner
    out_x, in_y = ax + 2 * STUB, by - sy * 2 * STUB
    return [a, (out_x, ay), (out_x, in_y), (bx, in_y), b]


def _hits(p: Point, q: Point, r: Rect) -> bool:
    """Whether the axis-parallel segment p-q passes through the inside of rectangle r."""
    left, top, right, bottom = r
    if p[1] == q[1]:  # horizontal
        y = p[1]
        lo, hi = min(p[0], q[0]), max(p[0], q[0])
        return top < y < bottom and lo < right and hi > left
    x = p[0]
    lo, hi = min(p[1], q[1]), max(p[1], q[1])
    return left < x < right and lo < bottom and hi > top


def blocked(points: Sequence[Point], obstacles: Sequence[Rect]) -> bool:
    """Whether a route passes through a block. The first and last segments (the stubs at the ports) are
    not checked: they start at a block's edge."""
    inner = list(points)
    for p, q in pairwise(inner[1:-1]):
        if p != q and any(_hits(p, q, r) for r in obstacles):
            return True
    if len(inner) <= 3:  # one corner: check both legs, except the last few pixels at each port
        for p, q in pairwise(inner):
            if any(_hits(_shrink(p, q), _shrink(q, p), r) for r in obstacles):
                return True
    return False


def _shrink(p: Point, q: Point) -> Point:
    """``p`` moved a stub length towards ``q``."""
    dx, dy = q[0] - p[0], q[1] - p[1]
    length = abs(dx) + abs(dy)
    if length <= 2 * STUB:
        return p
    return (p[0] + STUB * dx / length, p[1] + STUB * dy / length)


def route(
    a: Point, b: Point, da: Direction, db: Direction, obstacles: Sequence[Rect] = (), max_nodes: int = 4000
) -> list[Point]:
    """Corner points of an orthogonal route from ``a`` to ``b`` that avoids ``obstacles`` if it can."""
    simple = simple_route(a, b, da, db)
    if not obstacles or not blocked(simple, obstacles):
        return simple
    found = _astar(a, b, da, db, obstacles, max_nodes)
    return _simplify(found) if found is not None else simple


def _astar(
    a: Point, b: Point, da: Direction, db: Direction, obstacles: Sequence[Rect], max_nodes: int
) -> list[Point] | None:
    start = (a[0] + STUB * da[0], a[1] + STUB * da[1])
    goal = (b[0] - STUB * db[0], b[1] - STUB * db[1])
    xs = sorted({start[0], goal[0], *(v for r in obstacles for v in (r[0] - MARGIN, r[2] + MARGIN))})
    ys = sorted({start[1], goal[1], *(v for r in obstacles for v in (r[1] - MARGIN, r[3] + MARGIN))})
    if len(xs) * len(ys) > max_nodes:
        return None
    inside = [(r[0] - MARGIN / 2, r[1] - MARGIN / 2, r[2] + MARGIN / 2, r[3] + MARGIN / 2) for r in obstacles]

    def free(p: Point) -> bool:
        return not any(r[0] < p[0] < r[2] and r[1] < p[1] < r[3] for r in inside)

    xi, yi = {x: k for k, x in enumerate(xs)}, {y: k for k, y in enumerate(ys)}
    State = tuple[int, int, Direction]
    s0: State = (xi[start[0]], yi[start[1]], da)
    best: dict[State, float] = {s0: 0.0}
    came: dict[State, State] = {}
    heap: list[tuple[float, float, State]] = [(0.0, 0.0, s0)]

    def h(i: int, j: int) -> float:
        return abs(xs[i] - goal[0]) + abs(ys[j] - goal[1])

    while heap:
        _f, g, state = heapq.heappop(heap)
        i, j, d = state
        if g > best.get(state, float("inf")):
            continue
        if (xs[i], ys[j]) == goal:
            path = [state]
            while path[-1] in came:
                path.append(came[path[-1]])
            pts = [(xs[s[0]], ys[s[1]]) for s in reversed(path)]
            return [a, *pts, b]
        for nd in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if nd == (-d[0], -d[1]):
                continue  # no U-turns on the spot
            ni, nj = i + nd[0], j + nd[1]
            if not (0 <= ni < len(xs) and 0 <= nj < len(ys)):
                continue
            p, q = (xs[i], ys[j]), (xs[ni], ys[nj])
            if not free(q) or any(_hits(p, q, r) for r in inside):
                continue
            cost = g + abs(q[0] - p[0]) + abs(q[1] - p[1]) + (BEND_PENALTY if nd != d else 0.0)
            if (xs[ni], ys[nj]) == goal and nd != db:
                cost += BEND_PENALTY  # arriving sideways needs one more bend into the port
            ns: State = (ni, nj, nd)
            if cost < best.get(ns, float("inf")):
                best[ns] = cost
                came[ns] = state
                heapq.heappush(heap, (cost + h(ni, nj), cost, ns))
    return None


def _simplify(points: list[Point]) -> list[Point]:
    """Drop repeated points and points in the middle of straight lines."""
    out: list[Point] = []
    for p in points:
        if out and p == out[-1]:
            continue
        if len(out) >= 2:
            (x0, y0), (x1, y1) = out[-2], out[-1]
            if (x0 == x1 == p[0]) or (y0 == y1 == p[1]):
                out[-1] = p
                continue
        out.append(p)
    return out


def through(a: Point, b: Point, da: Direction, db: Direction, corners: Sequence[Point]) -> list[Point]:
    """A route through manually placed ``corners``, kept orthogonal when the ends move: the first corner
    follows ``a`` and the last follows ``b`` along the direction of the port."""
    if not corners:
        return simple_route(a, b, da, db)
    pts = [tuple(c) for c in corners]
    first, last = pts[0], pts[-1]
    pts[0] = (first[0], a[1]) if da[1] == 0 else (a[0], first[1])
    pts[-1] = (last[0], b[1]) if db[1] == 0 else (b[0], last[1])
    if len(pts) == 1:  # one corner must serve both ends
        pts = [(pts[0][0], a[1]), (pts[0][0], b[1])] if da[1] == 0 and db[1] == 0 else pts
    return _simplify([a, *[(float(x), float(y)) for x, y in pts], b])
