"""Graphics items for the diagram canvas: blocks, ports and wires."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPainterPathStroker, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QStyleOptionGraphicsItem, QWidget

from nervus.core import Block, Connection
from nervus.gui.theme import current_theme
from nervus.gui.views.glyphs import glyph

if TYPE_CHECKING:
    from nervus.gui.views.canvas import DiagramScene

GRID = 10.0
PORT_SIZE = 8.0
MIN_W, MIN_H = 70.0, 46.0


def snap(v: float) -> float:
    return round(v / GRID) * GRID


class PortItem(QGraphicsItem):
    """A port on the side of a block. Inputs are on the left, outputs on the right (swapped when flipped)."""

    def __init__(self, block_item: BlockItem, is_input: bool, index: int) -> None:
        super().__init__(block_item)
        self.block_item = block_item
        self.is_input = is_input
        self.index = index
        self.hover = False
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setZValue(2)

    @property
    def block(self) -> Block:
        return self.block_item.block

    @property
    def direction(self) -> int:
        """Direction the signal flows through this port: +1 = to the right, -1 = to the left (flipped block)."""
        return -1 if self.block_item.flipped else 1

    def boundingRect(self) -> QRectF:
        s = PORT_SIZE + 6  # generous hit area
        return QRectF(-s / 2, -s / 2, s, s)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        t = current_theme()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = PORT_SIZE / 2
        # A small triangle pointing in the signal direction.
        if self.is_input:
            pts = [QPointF(-h, -h), QPointF(h * 0.6, 0), QPointF(-h, h)]
        else:
            pts = [QPointF(-h * 0.6, -h), QPointF(h, 0), QPointF(-h * 0.6, h)]
        if self.direction < 0:
            pts = [QPointF(-p.x(), p.y()) for p in pts]
        color = t.color("accent") if self.hover else t.color("port")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF(pts))

    def hoverEnterEvent(self, event: Any) -> None:
        self.hover = True
        self.update()

    def hoverLeaveEvent(self, event: Any) -> None:
        self.hover = False
        self.update()

    def scene_anchor(self) -> QPointF:
        """Where wires attach, in scene coordinates."""
        outward = (-1 if self.is_input else 1) * self.direction
        return self.mapToScene(QPointF(outward * PORT_SIZE / 2, 0))


class BlockItem(QGraphicsItem):
    def __init__(self, block: Block) -> None:
        super().__init__()
        self.block = block
        self.error = False
        self.in_ports: list[PortItem] = []
        self.out_ports: list[PortItem] = []
        self._w, self._h = MIN_W, MIN_H
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(1)
        self.refresh()

    # ------------------------------------------------------------------ geometry

    @property
    def size(self) -> tuple[float, float]:
        return self._w, self._h

    def refresh(self) -> None:
        """Rebuild ports and size after the block's parameters changed."""
        self.prepareGeometryChange()
        text = glyph(self.block)
        lines = text.split("\n")
        n = max(self.block.num_inputs(), self.block.num_outputs(), 1)
        if getattr(self.block, "system", None) is not None:
            names = [b.name for b in self.block.inports() + self.block.outports()]  # type: ignore[attr-defined]
            names += ["⏻ enable "] * bool(getattr(self.block, "has_enable", False))
            names += ["↑ trigger "] * bool(getattr(self.block, "has_trigger", False))
            icon_lines = str(getattr(self.block, "mask_icon", "")).replace("\\n", "\n").split("\n")
            width = 2 * max((len(x) for x in names), default=4) + max((len(x) for x in icon_lines), default=0)
            lines = [" " * width] * max(1, len(icon_lines))
        self._w = max(MIN_W, snap(max(len(line) for line in lines) * 8 + 24))
        self._h = max(MIN_H, snap(max(n * 20 + 10, len(lines) * 16 + 16)))
        for p in self.in_ports + self.out_ports:
            p.setParentItem(None)  # type: ignore[arg-type]
            if p.scene():
                p.scene().removeItem(p)
        self.in_ports = [PortItem(self, True, i) for i in range(self.block.num_inputs())]
        names = self.block.input_names()
        for i, p in enumerate(self.in_ports):
            label = names[i] if i < len(names) and names[i] else ""
            p.setToolTip(f"input {i + 1}" + (f": {label}" if label else ""))
        self.out_ports = [PortItem(self, False, i) for i in range(self.block.num_outputs())]
        left, right = -PORT_SIZE / 2, self._w + PORT_SIZE / 2
        if self.flipped:
            left, right = right, left
        for ports, x in ((self.in_ports, left), (self.out_ports, right)):
            for i, p in enumerate(ports):
                p.setPos(x, self._h * (i + 1) / (len(ports) + 1))
        self.setToolTip(f"{self.block.label} ({self.block.type_id})\nDouble-click to edit · F1 for help")
        self.update()

    def boundingRect(self) -> QRectF:
        # Room for the name label under the block.
        return QRectF(-PORT_SIZE, -2, self._w + 2 * PORT_SIZE, self._h + 22)

    @property
    def flipped(self) -> bool:
        """Flipped blocks have their inputs on the right and outputs on the left (for feedback paths)."""
        return bool(self.block.meta.get("flipped", False))

    def body_rect(self) -> QRectF:
        return QRectF(0, 0, self._w, self._h)

    def center(self) -> QPointF:
        return self.mapToScene(self.body_rect().center())

    # ------------------------------------------------------------------ painting

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        t = current_theme()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.body_rect()
        border = (
            t.color("error") if self.error else t.color("selection") if self.isSelected() else t.color("block_border")
        )
        # soft shadow
        shadow = QColor(0, 0, 0, 35 if t.name == "light" else 90)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shadow)
        painter.drawRoundedRect(rect.translated(0, 2), 7, 7)
        painter.setBrush(t.color("block_fill"))
        painter.setPen(QPen(border, 2.0 if (self.isSelected() or self.error) else 1.2))
        painter.drawRoundedRect(rect, 7, 7)

        font = QFont(painter.font())
        font.setPointSizeF(11)
        painter.setFont(font)
        painter.setPen(t.color("block_text"))
        system = getattr(self.block, "system", None)
        if system is not None:
            self._paint_subsystem(painter, rect)
        else:
            painter.drawText(rect.adjusted(6, 4, -6, -4), Qt.AlignmentFlag.AlignCenter, glyph(self.block))

        name_font = QFont(font)
        name_font.setPointSizeF(10)
        painter.setFont(name_font)
        painter.setPen(t.color("text_secondary"))
        painter.drawText(QRectF(-40, self._h + 2, self._w + 80, 18), Qt.AlignmentFlag.AlignHCenter, self.block.name)

    def _paint_subsystem(self, painter: QPainter, rect: QRectF) -> None:
        """Port names inside the block, like Simulink's subsystem icon."""
        t = current_theme()
        small = QFont(painter.font())
        small.setPointSizeF(9)
        painter.setFont(small)
        painter.setPen(t.color("text_secondary"))
        sub = self.block
        left, right = Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignRight
        if self.flipped:
            left, right = right, left
        for ports, items, align, dx in (
            (sub.inports(), self.in_ports, left, 6 if not self.flipped else -6),  # type: ignore[attr-defined]
            (sub.outports(), self.out_ports, right, -6 if not self.flipped else 6),  # type: ignore[attr-defined]
        ):
            for port_block, item in zip(ports, items, strict=False):
                y = item.pos().y()
                box = QRectF(6 if dx > 0 else rect.width() / 2, y - 8, rect.width() / 2 - 8, 16)
                painter.drawText(box, align | Qt.AlignmentFlag.AlignVCenter, port_block.name)
        edge_marks = {"rising": "↑", "falling": "↓", "either": "↕", "function_call": "ƒ()"}
        for index, text in (
            (getattr(sub, "enable_index", None), "⏻ enable"),
            (getattr(sub, "trigger_index", None), f"{edge_marks.get(sub.params.get('trigger', ''), '')} trigger"),
        ):
            if index is None or index >= len(self.in_ports):
                continue
            y = self.in_ports[index].pos().y()
            painter.drawText(
                QRectF(6, y - 8, rect.width() / 2, 16),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                text,
            )
        if getattr(sub, "library_link", None) is not None:
            pen = QPen(t.color("block_text"), 1.0, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(3, 3, -3, -3), 4, 4)
            painter.setPen(t.color("block_text"))
        st = sub.params.get("sample_time", -1.0)
        if isinstance(st, int | float) and st > 0:
            period = f"{st * 1000:g} ms" if st < 1 else f"{st:g} s"
            small = QFont(painter.font())
            small.setPointSizeF(max(6.0, small.pointSizeF() - 1))
            painter.setFont(small)
            painter.drawText(
                rect.adjusted(6, 0, -18, -2), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight, f"⏱ {period}"
            )
        if getattr(sub, "variants", None):
            small = QFont(painter.font())
            small.setPointSizeF(max(6.0, small.pointSizeF() - 1))
            painter.setFont(small)
            painter.drawText(
                rect.adjusted(6, 0, -18, -2),
                Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
                f"◆ {getattr(sub, 'active_variant', '')}",
            )
        icon = getattr(sub, "mask_icon", "")
        if icon:
            big = QFont(painter.font())
            big.setPointSizeF(11)
            big.setBold(True)
            painter.setFont(big)
            painter.setPen(t.color("block_text"))
            painter.drawText(rect.adjusted(4, 4, -4, -4), Qt.AlignmentFlag.AlignCenter, icon.replace("\\n", "\n"))
        elif not sub.inports() and not sub.outports():  # type: ignore[attr-defined]
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "subsystem")
        # a small "open" hint in the corner
        painter.setPen(QPen(t.color("text_muted"), 1))
        painter.drawRect(QRectF(rect.right() - 13, rect.bottom() - 11, 8, 6))

    # ------------------------------------------------------------------ behaviour

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            return QPointF(snap(value.x()), snap(value.y()))
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            scene = self.scene()
            if scene is not None:
                scene.block_item_moved(self)  # type: ignore[attr-defined]
        return super().itemChange(change, value)

    def port(self, is_input: bool, index: int) -> PortItem | None:
        ports = self.in_ports if is_input else self.out_ports
        return ports[index] if 0 <= index < len(ports) else None


class WireItem(QGraphicsPathItem):
    """A signal line drawn with orthogonal segments."""

    def __init__(self, connection: Connection, src: PortItem, dst: PortItem) -> None:
        super().__init__()
        self.connection = connection
        self.src, self.dst = src, dst
        self.hover = False
        self.type_label = ""
        """Data type shown next to the wire (empty: not shown, e.g. for double)."""
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.setZValue(0)
        self.update_path()

    def update_path(self) -> None:
        self.setPath(route(self.src.scene_anchor(), self.dst.scene_anchor(), self.src.direction, self.dst.direction))

    def boundingRect(self) -> QRectF:
        r = super().boundingRect()
        return r.adjusted(0, -16, 140, 0) if self.type_label else r

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(10)  # easy to click
        return stroker.createStroke(self.path())

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        t = current_theme()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = t.color("selection") if (self.isSelected() or self.hover) else t.color("wire")
        painter.setPen(
            QPen(
                color,
                2.0 if self.isSelected() else 1.5,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.path())
        # Arrow head at the destination.
        end = self.dst.scene_anchor()
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(QPolygonF([end, end + QPointF(-7, -4), end + QPointF(-7, 4)]))
        if self.type_label:
            start = self.src.scene_anchor()
            f = QFont(painter.font())
            f.setPointSizeF(8)
            painter.setFont(f)
            painter.setPen(t.color("accent"))
            painter.drawText(
                QRectF(start.x() + 4, start.y() - 15, 140, 12), Qt.AlignmentFlag.AlignLeft, self.type_label
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))
        # Branch dot where an output fans out to several inputs.
        scene: DiagramScene | None = self.scene()  # type: ignore[assignment]
        if scene is not None and scene.fanout(self.connection) > 1:
            painter.drawEllipse(self.src.scene_anchor() + QPointF(10, 0), 3, 3)

    def hoverEnterEvent(self, event: Any) -> None:
        self.hover = True
        self.update()

    def hoverLeaveEvent(self, event: Any) -> None:
        self.hover = False
        self.update()


def route(a: QPointF, b: QPointF, a_dir: int = 1, b_dir: int = 1) -> QPainterPath:
    """Orthogonal route from an output anchor ``a`` to an input anchor ``b``.

    ``a_dir``/``b_dir`` are the signal directions at the ports (+1 = to the right, -1 = flipped block).
    """
    stub = 10.0
    if a_dir < 0 and b_dir < 0:  # both flipped: route the mirror image
        mirrored = route(QPointF(-a.x(), a.y()), QPointF(-b.x(), b.y()))
        path = QPainterPath(a)
        for k in range(1, mirrored.elementCount()):
            el = mirrored.elementAt(k)
            path.lineTo(-el.x, el.y)
        return path
    path = QPainterPath(a)
    if a_dir != b_dir:
        # Out of one side and into the same side of the other block (typical for a flipped feedback block):
        # go past both, then turn back.
        x = max(a.x(), b.x()) + 2 * stub if a_dir > 0 else min(a.x(), b.x()) - 2 * stub
        path.lineTo(x, a.y())
        path.lineTo(x, b.y())
        path.lineTo(b)
        return path
    if b.x() - a.x() >= 2 * stub:
        mx = snap((a.x() + b.x()) / 2)
        path.lineTo(mx, a.y())
        path.lineTo(mx, b.y())
        path.lineTo(b)
    else:
        # Backwards (feedback) wire: go out, loop below/above, come back in.
        out_x, in_x = a.x() + 2 * stub, b.x() - 2 * stub
        detour_y = max(a.y(), b.y()) + 40 if abs(a.y() - b.y()) < 30 else (a.y() + b.y()) / 2
        path.lineTo(out_x, a.y())
        path.lineTo(out_x, detour_y)
        path.lineTo(in_x, detour_y)
        path.lineTo(in_x, b.y())
        path.lineTo(b)
    return path
