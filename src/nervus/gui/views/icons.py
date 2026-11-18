"""Toolbar icons drawn with QPainter in the current theme's colours (no image files needed)."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

from nervus.gui.theme import current_theme

SIZE = 64


def _play(p: QPainter, c: QColor) -> None:
    p.setBrush(c)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPolygon(QPolygonF([QPointF(20, 14), QPointF(50, 32), QPointF(20, 50)]))


def _stop(p: QPainter, c: QColor) -> None:
    p.setBrush(c)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(18, 18, 28, 28), 4, 4)


def _gear(p: QPainter, c: QColor) -> None:
    p.setPen(QPen(c, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(32, 32), 11, 11)
    for i in range(8):
        p.save()
        p.translate(32, 32)
        p.rotate(i * 45)
        p.drawLine(QPointF(0, -16), QPointF(0, -21))
        p.restore()


def _plus_doc(p: QPainter, c: QColor) -> None:
    p.setPen(QPen(c, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(16, 10, 32, 44), 4, 4)
    p.drawLine(QPointF(32, 24), QPointF(32, 40))
    p.drawLine(QPointF(24, 32), QPointF(40, 32))


def _folder(p: QPainter, c: QColor) -> None:
    p.setPen(QPen(c, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath(QPointF(10, 18))
    for pt in ((26, 18), (30, 23), (54, 23), (54, 50), (10, 50)):
        path.lineTo(*pt)
    path.closeSubpath()
    p.drawPath(path)


def _save(p: QPainter, c: QColor) -> None:
    p.setPen(QPen(c, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(12, 12, 40, 40), 5, 5)
    p.drawRect(QRectF(22, 12, 20, 12))
    p.drawRect(QRectF(20, 34, 24, 18))


def _arrow(reverse: bool) -> Callable[[QPainter, QColor], None]:
    def draw(p: QPainter, c: QColor) -> None:
        p.setPen(QPen(c, 4.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if reverse:
            p.translate(SIZE, 0)
            p.scale(-1, 1)
        path = QPainterPath(QPointF(46, 46))
        path.cubicTo(QPointF(50, 26), QPointF(36, 18), QPointF(18, 24))
        p.drawPath(path)
        p.drawLine(QPointF(18, 24), QPointF(26, 14))
        p.drawLine(QPointF(18, 24), QPointF(28, 30))

    return draw


def _fit(p: QPainter, c: QColor) -> None:
    p.setPen(QPen(c, 4.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for x, y, dx, dy in ((14, 14, 1, 1), (50, 14, -1, 1), (14, 50, 1, -1), (50, 50, -1, -1)):
        p.drawLine(QPointF(x, y), QPointF(x + 10 * dx, y))
        p.drawLine(QPointF(x, y), QPointF(x, y + 10 * dy))


def _help(p: QPainter, c: QColor) -> None:
    p.setPen(QPen(c, 4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(32, 32), 20, 20)
    f = p.font()
    f.setPixelSize(26)
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(12, 12, 40, 40), Qt.AlignmentFlag.AlignCenter, "?")


_ICONS: dict[str, Callable[[QPainter, QColor], None]] = {
    "run": _play,
    "stop": _stop,
    "settings": _gear,
    "new": _plus_doc,
    "open": _folder,
    "save": _save,
    "undo": _arrow(False),
    "redo": _arrow(True),
    "fit": _fit,
    "help": _help,
}


def icon(name: str) -> QIcon:
    t = current_theme()
    colors = {"run": QColor("#1baf7a"), "stop": t.color("error")}
    c = colors.get(name, t.color("text_secondary"))
    pm = QPixmap(SIZE, SIZE)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _ICONS[name](p, c)
    p.end()
    return QIcon(pm)
