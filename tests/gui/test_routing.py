"""Wire routing around blocks, and manually placed wire corners."""

from itertools import pairwise

from PySide6.QtCore import QPointF

from nervus.gui.views import routing


def _orthogonal(pts: list[tuple[float, float]]) -> bool:
    return all(a[0] == b[0] or a[1] == b[1] for a, b in pairwise(pts))


def test_simple_route_is_kept_when_clear() -> None:
    pts = routing.route((0, 0), (200, 50), (1, 0), (1, 0), [(300, -50, 400, 50)])
    assert pts == [(0, 0), (100, 0), (100, 50), (200, 50)]


def test_route_avoids_a_block_in_the_way() -> None:
    block = (80, -40, 160, 40)  # straddles the straight line from a to b
    pts = routing.route((0, 0), (240, 0), (1, 0), (1, 0), [block])
    assert pts[0] == (0, 0) and pts[-1] == (240, 0)
    assert _orthogonal(pts)
    assert not routing.blocked(pts, [block])
    assert len(pts) <= 6  # around the block, not a maze


def test_feedback_route_avoids_blocks() -> None:
    # Output of a block at x = 300 back to an input at x = 0, with a block lying on the default detour.
    a, b = (300.0, 0.0), (0.0, 0.0)
    detour = routing.simple_route(a, b, (1, 0), (1, 0))
    y = detour[2][1]
    obstacle = (100.0, y - 20, 200.0, y + 20)
    assert routing.blocked(detour, [obstacle])
    own = [(220.0, -25.0, 296.0, 25.0), (4.0, -25.0, 80.0, 25.0)]  # the source and destination blocks
    pts = routing.route(a, b, (1, 0), (1, 0), [obstacle, *own])
    assert _orthogonal(pts) and not routing.blocked(pts, [obstacle, *own])


def test_through_manual_corners_follows_moved_ends() -> None:
    corners = [(50.0, 0.0), (50.0, 100.0)]
    pts = routing.through((0, 10), (120, 90), (1, 0), (1, 0), corners)
    assert pts == [(0, 10), (50, 10), (50, 90), (120, 90)]  # the vertical segment stays at x = 50


def test_drag_wire_segment_and_branch(window) -> None:  # type: ignore[no-untyped-def]
    from nervus.gui.views.canvas import _moved
    from nervus.io import dumps, loads

    ed = window.editor
    c = ed.add_block("sources.constant", QPointF(0, 0))
    g1 = ed.add_block("math.gain", QPointF(300, -100))
    g2 = ed.add_block("math.gain", QPointF(300, 100))
    ed.connect_ports(c, 0, g1, 0)
    ed.connect_ports(c, 0, g2, 0)
    w1, w2 = (w for w in window.scene.wires.values())
    k = next(j for j in range(1, len(w1.corners()) - 2) if w1.corners()[j][0] == w1.corners()[j + 1][0])
    mid = w1.corners()[k]
    assert w1.segment_at(QPointF(mid[0] + 2, mid[1] + 5)) == k
    group = window.scene._segment_group(w1, k)
    assert {id(w) for w, _p, _k in group} == {id(w1), id(w2)}  # the shared vertical trunk: a branch point
    changes = [(w.connection, None, [list(p) for p in _moved(pts, j, 40.0, 0.0)[1:-1]]) for w, pts, j in group]
    assert ed.set_wire_points(changes)
    assert w1.corners()[k][0] == mid[0] + 40 and w2.corners()[k][0] == mid[0] + 40
    saved = loads(dumps(window.diagram_model.root))
    assert all(conn.meta["points"] for conn in saved.connections)
    ed.undo_stack.undo()
    assert w1.corners()[k][0] == mid[0] and "points" not in w1.connection.meta
    menu = window.context_menu(w1.connection)
    assert "Reset Route" not in [a.text() for a in menu.actions()]
