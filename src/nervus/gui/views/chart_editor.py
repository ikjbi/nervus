"""The graphical chart editor: states as boxes, transitions as arrows, and a property panel.

It edits an :class:`~nervus.blocks.chart_model.EditableChart` and writes the block's ``definition`` (the chart
language) and ``meta["chart_layout"]`` (the boxes) through the editor controller, so the change can be undone.
"""

from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSceneMouseEvent,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStyleOptionGraphicsItem,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from nervus.blocks.chart_model import HEADER, PAD, EditableChart, ETransition, _grow_to_fit, auto_layout, from_text
from nervus.core.block import Block
from nervus.core.errors import ParameterError
from nervus.gui.theme import current_theme, monospace_font

LAYOUT_KEY = "chart_layout"


def _border_point(r: QRectF, toward: QPointF) -> QPointF:
    """Where the line from the centre of ``r`` towards ``toward`` leaves ``r``."""
    c = r.center()
    dx, dy = toward.x() - c.x(), toward.y() - c.y()
    if dx == 0 and dy == 0:
        return c
    tx = (r.width() / 2) / abs(dx) if dx else math.inf
    ty = (r.height() / 2) / abs(dy) if dy else math.inf
    t = min(tx, ty)
    return QPointF(c.x() + dx * t, c.y() + dy * t)


def _crosses(start: QPointF, ctrl: QPointF, end: QPointF, boxes: list[QRectF]) -> bool:
    """Whether the quadratic curve passes through any of ``boxes``."""
    for k in range(1, 16):
        s = k / 16
        p = start * (1 - s) ** 2 + ctrl * (2 * s * (1 - s)) + end * s**2
        if any(b.contains(p) for b in boxes):
            return True
    return False


class StateItem(QGraphicsRectItem):
    """A state: a rounded box with its name and actions; child states are child items."""

    def __init__(self, editor: ChartEditor, name: str, rect: list[float], parent: QGraphicsItem | None) -> None:
        super().__init__(0, 0, rect[2], rect[3], parent)
        self.editor, self.name = editor, name
        self.setPos(rect[0], rect[1])
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                      | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)  # fmt: skip
        self.setAcceptHoverEvents(True)
        self.setToolTip(f"State {name}: drag to move, double-click to edit")

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        t = current_theme()
        chart = self.editor.chart
        st = chart.state(self.name)
        parent = chart.state(st.parent) if st.parent is not None else None
        selected = self.isSelected()
        pen = QPen(t.color("selection") if selected else t.color("block_border"), 2.0 if selected else 1.2)
        if parent is not None and parent.parallel:
            pen.setStyle(Qt.PenStyle.DashLine)  # a parallel region
        painter.setPen(pen)
        active = self.name in self.editor.active_states
        fill = QColor(t.accent) if active else t.color("block_fill")
        if active:
            fill.setAlpha(40)
        painter.setBrush(QBrush(fill))
        painter.drawRoundedRect(self.rect(), 10, 10)
        font = QFont(painter.font())
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(t.color("block_text"))
        title = self.name + ("  (parallel)" if st.parallel else "")
        painter.drawText(QRectF(10, 6, self.rect().width() - 20, 18), Qt.AlignmentFlag.AlignLeft, title)
        small = QFont(painter.font())
        small.setBold(False)
        small.setPointSizeF(max(7.0, small.pointSizeF() - 1.5))
        painter.setFont(small)
        painter.setPen(t.color("text_secondary"))
        fm = QFontMetricsF(small)
        y = 26.0
        bottom = HEADER + 4 if chart.children(self.name) else self.rect().height() - 4
        for kind in ("entry", "during", "exit"):
            text = getattr(st, kind).strip()
            if text and y + fm.height() <= bottom:
                line = fm.elidedText(f"{kind}: {text}", Qt.TextElideMode.ElideRight, self.rect().width() - 20)
                painter.drawText(QPointF(10, y + fm.ascent()), line)
                y += fm.height()
        if st.history:
            painter.setPen(QPen(t.color("text_secondary"), 1.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            c = QPointF(self.rect().width() - 16, 15)
            painter.drawEllipse(c, 9, 9)
            painter.drawText(QRectF(c.x() - 9, c.y() - 9, 18, 18), Qt.AlignmentFlag.AlignCenter, "H")

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.parentItem() is not None:
            p = QPointF(value)
            return QPointF(max(p.x(), PAD / 2), max(p.y(), HEADER))  # stay inside the enclosing state
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.editor.state_moved(self)
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        super().mouseReleaseEvent(event)
        self.editor.move_finished(self.name)

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        self.editor.edit_state(self.name)


class InitialMarker(QGraphicsPathItem):
    """The filled dot and arrow pointing at the state entered by default."""

    def __init__(self, target: StateItem) -> None:
        super().__init__(target.parentItem())
        self.target = target
        self.setZValue(target.zValue() + 0.5)
        self.update_path()

    def update_path(self) -> None:
        r = self.target.mapRectToParent(self.target.rect())
        end = QPointF(r.left(), r.top() + 22)
        start = QPointF(r.left() - 26, r.top() + 22)
        path = QPainterPath()
        path.addEllipse(start, 4.5, 4.5)
        path.moveTo(start)
        path.lineTo(end)
        path.addPolygon(QPolygonF([end, end + QPointF(-8, -4), end + QPointF(-8, 4), end]))
        self.setPath(path)
        t = current_theme()
        self.setPen(QPen(t.color("wire"), 1.4))
        self.setBrush(QBrush(t.color("wire")))


class TransitionItem(QGraphicsPathItem):
    """An arrow from one state to another, labelled with its priority, guard and action."""

    def __init__(self, editor: ChartEditor, transition: ETransition) -> None:
        super().__init__()
        self.editor, self.transition = editor, transition
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setZValue(10)
        self.label_pos = QPointF()
        self.curve: tuple[QPointF, QPointF, QPointF] | None = None
        """Start, control point and end of the arrow (None for a self-loop)."""
        self.arrow = QPolygonF()
        self.update_path()

    def update_path(self) -> None:
        ed, tr = self.editor, self.transition
        src, dst = ed.state_items[tr.source], ed.state_items[tr.target]
        rs, rd = src.mapRectToScene(src.rect()), dst.mapRectToScene(dst.rect())
        same = [t for t in ed.chart.transitions if (t.source, t.target) == (tr.source, tr.target)]
        k = next(i for i, t in enumerate(same) if t is tr)
        path = QPainterPath()
        if tr.source == tr.target:  # a self-loop over the top-right corner
            a = QPointF(rs.right() - 30 - 18 * k, rs.top())
            b = QPointF(rs.right(), rs.top() + 24 + 14 * k)
            lift = 36 + 16 * k
            c1, c2 = a + QPointF(0, -lift), b + QPointF(lift, 0)
            path.moveTo(a)
            path.cubicTo(c1, c2, b)
            end, before = b, c2
            self.label_pos = QPointF(rs.right() + 0.25 * lift, rs.top() - 0.75 * lift)
            self.curve = None
        else:
            reverse = any((t.source, t.target) == (tr.target, tr.source) for t in ed.chart.transitions)
            c0, c1_ = rs.center(), rd.center()
            d = c1_ - c0
            length = math.hypot(d.x(), d.y()) or 1.0
            normal = QPointF(-d.y() / length, d.x() / length)
            if len(same) == 1 and not reverse:
                candidates = [0.0, 45.0, -45.0, 90.0, -90.0, 135.0, -135.0, 180.0, -180.0]
            else:  # keep to this side, so the arrows of a pair stay apart
                base = 18.0 + 26.0 * k
                candidates = [base + 45.0 * j for j in range(5)]
            obstacles = ed.obstacles(tr.source, tr.target)
            for offset in candidates:  # the smallest bend that does not cross another state
                ctrl = (c0 + c1_) / 2 + normal * (2 * offset)
                start, end = _border_point(rs, ctrl), _border_point(rd, ctrl)
                if not _crosses(start, ctrl, end, obstacles):
                    break
            else:
                ctrl = (c0 + c1_) / 2 + normal * (2 * candidates[0])
                start, end = _border_point(rs, ctrl), _border_point(rd, ctrl)
            path.moveTo(start)
            path.quadTo(ctrl, end)
            before = ctrl
            self.label_pos = start * 0.25 + ctrl * 0.5 + end * 0.25
            self.curve = (start, ctrl, end)
        v = end - before
        n = math.hypot(v.x(), v.y()) or 1.0
        u = QPointF(v.x() / n, v.y() / n)
        w = QPointF(-u.y(), u.x())
        self.arrow = QPolygonF([end, end - u * 11 + w * 5, end - u * 11 - w * 5])
        self.setToolTip(f"{tr.source} → {tr.target}: {self.label()}")
        self.prepareGeometryChange()
        self.setPath(path)

    def label(self) -> str:
        chart = self.editor.chart
        text = self.transition.label() or "(always)"
        if len(chart.outgoing(self.transition.source)) > 1:
            text = f"{chart.priority(self.transition)}: {text}"
        return text

    @staticmethod
    def label_font() -> QFont:
        font = QFont()
        font.setPointSizeF(max(7.0, font.pointSizeF() - 2.0))
        return font

    def place_label(self, taken: list[QRectF], boxes: list[QRectF]) -> QRectF:
        """Move the label along the arrow to the first place that overlaps no other label and no state."""
        if self.curve is not None:
            start, ctrl, end = self.curve

            def overlap(s: float) -> float:
                self.label_pos = start * (1 - s) ** 2 + ctrl * (2 * s * (1 - s)) + end * s**2
                r = self._label_rect()
                area = 0.0
                for o in (*taken, *boxes):
                    x = r.intersected(o)
                    area += max(x.width(), 0.0) * max(x.height(), 0.0)
                return area

            # the first free place from the middle outwards, or else the least covered one
            options = (0.5, 0.4, 0.6, 0.3, 0.7, 0.22, 0.78)
            best = next((s for s in options if overlap(s) == 0.0), None)
            if best is None:
                best = min(options, key=overlap)
            overlap(best)
        self.prepareGeometryChange()
        return self._label_rect()

    def _label_rect(self) -> QRectF:
        fm = QFontMetricsF(self.label_font())
        w = min(fm.horizontalAdvance(self.label()), 150.0) + 8
        return QRectF(self.label_pos.x() - w / 2, self.label_pos.y() - fm.height() / 2 - 2, w, fm.height() + 4)

    def boundingRect(self) -> QRectF:
        return super().boundingRect().adjusted(-12, -12, 12, 12).united(self._label_rect())

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(10)
        out = stroker.createStroke(self.path())
        out.addRect(self._label_rect())
        return out

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        t = current_theme()
        color = t.color("selection") if self.isSelected() else t.color("wire")
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(color, 2.0 if self.isSelected() else 1.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.path())
        painter.setBrush(QBrush(color))
        painter.drawPolygon(self.arrow)
        r = self._label_rect()
        painter.setPen(Qt.PenStyle.NoPen)
        bg = t.color("canvas")
        bg.setAlpha(215)  # crossing arrows stay visible through a label
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(r, 4, 4)
        painter.setPen(t.color("selection") if self.isSelected() else t.color("text"))
        painter.setFont(self.label_font())
        fm = QFontMetricsF(self.label_font())
        painter.drawText(
            r, Qt.AlignmentFlag.AlignCenter, fm.elidedText(self.label(), Qt.TextElideMode.ElideRight, r.width() - 6)
        )

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        self.editor.edit_transition(self.transition)


class ChartScene(QGraphicsScene):
    """Clicks in "add transition" mode pick the target state; a double-click on empty space adds a state."""

    stateClicked = Signal(str)
    emptyDoubleClicked = Signal(QPointF)

    def __init__(self, editor: ChartEditor) -> None:
        super().__init__(editor)
        self.editor = editor
        self.picking = False

    def _state_at(self, pos: QPointF) -> StateItem | None:
        items = [i for i in self.items(pos) if isinstance(i, StateItem)]
        return items[0] if items else None  # the innermost (topmost) state

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self.picking:
            item = self._state_at(event.scenePos())
            if item is not None:
                self.stateClicked.emit(item.name)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self.itemAt(event.scenePos(), self.views()[0].transform()) is None:
            self.emptyDoubleClicked.emit(event.scenePos())
            return
        super().mouseDoubleClickEvent(event)


class ChartEditor(QDialog):
    """Edit a State Chart block graphically. ``controller`` is the editor controller (``set_chart``)."""

    def __init__(self, block: Block, controller: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.block, self.controller = block, controller
        self.setWindowTitle(f"Chart — {block.name}")
        self.resize(1100, 720)
        self.chart: EditableChart = from_text(str(block.params["definition"]), block.meta.get(LAYOUT_KEY))
        self.state_items: dict[str, StateItem] = {}
        self.transition_items: list[TransitionItem] = []
        self.markers: list[InitialMarker] = []
        self.active_states: set[str] = set()
        self._pick_source: str | None = None
        self._loading = False

        self.scene = ChartScene(self)
        self.scene.selectionChanged.connect(self._selection_changed)
        self.scene.stateClicked.connect(self._picked)
        self.scene.emptyDoubleClicked.connect(lambda p: self.add_state(at=p))
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setBackgroundBrush(QBrush(current_theme().color("canvas")))
        self.view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.text = QPlainTextEdit()
        self.text.setFont(monospace_font())
        self.tabs = QTabWidget()
        self.tabs.addTab(self.view, "Diagram")
        self.tabs.addTab(self.text, "Text")
        self.tabs.currentChanged.connect(self._tab_changed)

        tools = QToolBar()
        self.act_state = self._tool(tools, "Add state", self.add_state, "Add a state (next to the selected one)")
        self.act_child = self._tool(tools, "Add child state", self.add_child, "Add a state inside the selected state")
        self.act_transition = self._tool(tools, "Add transition", self.start_transition,
                                         "Add a transition from the selected state: then click the target state")  # fmt: skip
        tools.addSeparator()
        self.act_initial = self._tool(tools, "Make initial", self.make_initial, "Enter this state first (at its level)")
        self.act_delete = self._tool(
            tools, "Delete", self.delete_selected, "Delete the selected states and transitions"
        )
        self.act_delete.setShortcut(QKeySequence.StandardKey.Delete)
        self.addAction(self.act_delete)
        tools.addSeparator()
        self._tool(tools, "Tidy up", self.tidy, "Place all states again in a grid")

        self.panel = QStackedWidget()
        self.panel.addWidget(self._chart_panel())
        self.panel.addWidget(self._state_panel())
        self.panel.addWidget(self._transition_panel())
        self.panel.setMinimumWidth(300)

        split = QSplitter()
        split.addWidget(self.tabs)
        split.addWidget(self.panel)
        split.setStretchFactor(0, 1)

        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setObjectName("muted")
        self.apply_button = QPushButton("Apply")
        self.ok_button = QPushButton("OK")
        self.ok_button.setObjectName("primary")
        cancel = QPushButton("Cancel")
        self.apply_button.clicked.connect(self.apply)
        self.ok_button.clicked.connect(self._ok)
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self.message, 1)
        for b in (self.apply_button, self.ok_button, cancel):
            buttons.addWidget(b)

        layout = QVBoxLayout(self)
        layout.addWidget(tools)
        layout.addWidget(split, 1)
        layout.addLayout(buttons)
        for b in self.findChildren(QPushButton):
            b.setAutoDefault(False)  # Enter in a text field must not press a button
        self.rebuild()

    def fit(self) -> None:
        """Show the whole chart (but do not magnify a small one)."""
        rect = self.scene.itemsBoundingRect().adjusted(-40, -40, 40, 40)
        self.view.resetTransform()
        vp = self.view.viewport()
        scale = min(1.0, vp.width() / max(rect.width(), 1.0), vp.height() / max(rect.height(), 1.0))
        scale = max(scale, 0.75)  # smaller text is hard to read: scroll instead
        self.view.scale(scale, scale)
        self.view.centerOn(rect.center())

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        self.fit()

    # ------------------------------------------------------------------ panels

    def _tool(self, bar: QToolBar, text: str, slot: Any, tip: str) -> QAction:
        act = bar.addAction(text)
        act.setToolTip(tip)
        act.triggered.connect(lambda _=False: slot())
        return act

    def _chart_panel(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        hint = QLabel("The chart's interface. Separate names with commas; outputs and locals take an initial value, "
                      "e.g. <code>mode = 0, fuel</code>. Select a state or a transition to edit it.")  # fmt: skip
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        form.addRow(hint)
        self.decl: dict[str, QLineEdit] = {}
        for key, label in (("inputs", "Inputs"), ("outputs", "Outputs"), ("locals", "Locals"), ("params", "Parameters"),
                           ("events", "Events")):  # fmt: skip
            edit = QLineEdit()
            edit.editingFinished.connect(lambda k=key, e=edit: self._set_declaration(k, e.text()))
            self.decl[key] = edit
            form.addRow(label, edit)
        return w

    def _state_panel(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.state_name = QLineEdit()
        self.state_name.editingFinished.connect(self._rename)
        form.addRow("Name", self.state_name)
        self.state_fields: dict[str, QPlainTextEdit] = {}
        for kind, tip in (("entry", "when the state is entered"), ("during", "every sample while active (no transition)"),
                          ("exit", "when the state is left")):  # fmt: skip
            edit = QPlainTextEdit()
            edit.setFont(monospace_font())
            edit.setFixedHeight(56)
            edit.setPlaceholderText(f"actions {tip}, e.g. y = 1; n = n + 1")
            edit.textChanged.connect(lambda k=kind, e=edit: self._set_state_field(k, e.toPlainText()))
            self.state_fields[kind] = edit
            form.addRow(kind.capitalize(), edit)
        self.state_parallel = QCheckBox("Children are parallel regions (all active)")
        self.state_history = QCheckBox("History: re-enter the child that was active")
        self.state_parallel.toggled.connect(lambda v: self._set_state_field("parallel", v))
        self.state_history.toggled.connect(lambda v: self._set_state_field("history", v))
        form.addRow(self.state_parallel)
        form.addRow(self.state_history)
        return w

    def _transition_panel(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.tr_title = QLabel()
        form.addRow(self.tr_title)
        self.tr_guard = QLineEdit()
        self.tr_guard.setPlaceholderText("e.g. rpm > 600 and after(10); empty: always")
        self.tr_action = QLineEdit()
        self.tr_action.setPlaceholderText("e.g. fuel = 0")
        self.tr_guard.textEdited.connect(lambda v: self._set_transition_field("guard", v))
        self.tr_action.textEdited.connect(lambda v: self._set_transition_field("action", v))
        form.addRow("Guard", self.tr_guard)
        form.addRow("Action", self.tr_action)
        row = QHBoxLayout()
        self.tr_priority = QLabel()
        up, down = QPushButton("Check earlier"), QPushButton("Check later")
        self.tr_up, self.tr_down = up, down
        up.clicked.connect(lambda: self._move_priority(-1))
        down.clicked.connect(lambda: self._move_priority(1))
        row.addWidget(self.tr_priority, 1)
        row.addWidget(up)
        row.addWidget(down)
        form.addRow(row)
        self.tr_within = QLabel()
        self.tr_within.setWordWrap(True)
        form.addRow(self.tr_within)
        note = QLabel("The transitions leaving a state are checked in priority order; the first whose guard is true "
                      "fires.")  # fmt: skip
        note.setWordWrap(True)
        note.setObjectName("muted")
        form.addRow(note)
        return w

    # ------------------------------------------------------------------ scene

    def rebuild(self, select: str | ETransition | None = None) -> None:
        """Draw the chart again from :attr:`chart` and refresh the panels."""
        self._loading = True
        self.scene.clear()
        self.state_items, self.transition_items, self.markers = {}, [], []
        auto_layout(self.chart)

        def add(name: str | None, parent: StateItem | None, depth: int) -> None:
            for st in self.chart.children(name):
                item = StateItem(self, st.name, self.chart.layout[st.name], parent)
                item.setZValue(depth)
                if parent is None:
                    self.scene.addItem(item)
                self.state_items[st.name] = item
                add(st.name, item, depth + 1)

        add(None, None, 0)
        for parent in [None, *[s.name for s in self.chart.states]]:
            par = self.chart.state(parent) if parent is not None else None
            if par is not None and par.parallel:
                continue  # every region is entered
            first = self.chart.initial_of(parent)
            if first is not None:
                marker = InitialMarker(self.state_items[first])
                if marker.parentItem() is None:
                    self.scene.addItem(marker)
                self.markers.append(marker)
        for t in self.chart.transitions:
            item = TransitionItem(self, t)
            self.scene.addItem(item)
            self.transition_items.append(item)
        self._place_labels()
        if isinstance(select, str) and select in self.state_items:
            self.state_items[select].setSelected(True)
        elif isinstance(select, ETransition):
            for ti in self.transition_items:
                ti.setSelected(ti.transition is select)
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-60, -60, 60, 60))
        self._loading = False
        self._selection_changed()
        self._validate()

    def obstacles(self, source: str, target: str) -> list[QRectF]:
        """The boxes (in the scene) a transition from ``source`` to ``target`` should not cross: every state that
        neither encloses one of them nor is one of them."""
        enclosing = {source, target}
        for name in (source, target):
            p = self.chart.state(name).parent
            while p is not None:
                enclosing.add(p)
                p = self.chart.state(p).parent
        out = []
        for name, item in self.state_items.items():
            if name not in enclosing:
                out.append(item.mapRectToScene(item.rect()).adjusted(-6, -6, 6, 6))
        return out

    def state_moved(self, item: StateItem) -> None:
        if self._loading:
            return
        box = self.chart.layout[item.name]
        box[0], box[1] = item.pos().x(), item.pos().y()
        for ti in self.transition_items:
            ti.update_path()
        self._place_labels()
        for m in self.markers:
            m.update_path()

    def _place_labels(self) -> None:
        boxes = [i.mapRectToScene(i.rect()) for i in self.state_items.values() if not self.chart.children(i.name)]
        taken: list[QRectF] = []
        for ti in self.transition_items:
            taken.append(ti.place_label(taken, boxes))

    def move_finished(self, name: str) -> None:
        parent = self.chart.state(name).parent if name in self.state_items else None
        if parent is not None:
            _grow_to_fit(self.chart, parent)
            self.rebuild(select=name)

    # ------------------------------------------------------------------ selection and panels

    def selected_state(self) -> str | None:
        items = [i for i in self.scene.selectedItems() if isinstance(i, StateItem)]
        return items[0].name if len(items) == 1 else None

    def selected_transition(self) -> ETransition | None:
        items = [i for i in self.scene.selectedItems() if isinstance(i, TransitionItem)]
        return items[0].transition if len(items) == 1 else None

    def _selection_changed(self) -> None:
        if self._loading or not isValid(self.scene):  # the scene emits this while it is destroyed
            return
        self._loading = True
        name, tr = self.selected_state(), self.selected_transition()
        if name is not None:
            st = self.chart.state(name)
            self.state_name.setText(st.name)
            for kind, edit in self.state_fields.items():
                edit.setPlainText(getattr(st, kind))
            self.state_parallel.setChecked(st.parallel)
            self.state_history.setChecked(st.history)
            has_kids = bool(self.chart.children(name))
            self.state_parallel.setEnabled(has_kids)
            self.state_history.setEnabled(has_kids and not st.parallel)
            self.panel.setCurrentIndex(1)
        elif tr is not None:
            self.tr_title.setText(f"<b>{tr.source} → {tr.target}</b>")
            self.tr_guard.setText(tr.guard)
            self.tr_action.setText(tr.action)
            n = len(self.chart.outgoing(tr.source))
            self.tr_priority.setText(f"Priority {self.chart.priority(tr)} of {n}")
            self.tr_up.setEnabled(self.chart.priority(tr) > 1)
            self.tr_down.setEnabled(self.chart.priority(tr) < n)
            where = "the chart" if tr.within == "chart" else tr.within
            self.tr_within.setText(
                f"Belongs to {where}: leaves and enters again every state below it (as drawn in Stateflow; "
                "change it in the Text tab)."
                if tr.within
                else ""
            )
            self.tr_within.setVisible(bool(tr.within))
            self.panel.setCurrentIndex(2)
        else:
            c = self.chart
            self.decl["inputs"].setText(", ".join(c.inputs))
            self.decl["outputs"].setText(", ".join(f"{n} = {v}" for n, v in c.outputs))
            self.decl["locals"].setText(", ".join(f"{n} = {v}" for n, v in c.locals))
            self.decl["params"].setText(", ".join(c.params))
            self.decl["events"].setText(", ".join(c.events))
            self.panel.setCurrentIndex(0)
        self.act_child.setEnabled(name is not None)
        self.act_transition.setEnabled(name is not None)
        self.act_initial.setEnabled(name is not None)
        self.act_delete.setEnabled(bool(self.scene.selectedItems()))
        self._loading = False

    def edit_state(self, name: str) -> None:
        self.scene.clearSelection()
        self.state_items[name].setSelected(True)
        self.state_fields["entry"].setFocus()

    def edit_transition(self, t: ETransition) -> None:
        self.rebuild(select=t)
        self.tr_guard.setFocus()

    # ------------------------------------------------------------------ edits

    def add_state(self, at: QPointF | None = None) -> str:
        sel = self.selected_state()
        parent = self.chart.state(sel).parent if sel is not None else None
        pos = None
        if at is not None:
            pos = (at.x(), at.y())
        elif sel is not None:
            x, y, w, _h = self.chart.layout[sel]
            pos = (x + w + 70, y)
        st = self.chart.add_state(parent=parent, at=pos)
        self.rebuild(select=st.name)
        self.state_name.setFocus()
        self.state_name.selectAll()
        return st.name

    def add_child(self) -> str | None:
        sel = self.selected_state()
        if sel is None:
            return None
        n = len(self.chart.children(sel))
        st = self.chart.add_state(parent=sel, at=(PAD + n * 170.0, HEADER + PAD))
        self.rebuild(select=st.name)
        return st.name

    def start_transition(self) -> None:
        self._pick_source = self.selected_state()
        if self._pick_source is None:
            return
        self.scene.picking = True
        self.view.setCursor(Qt.CursorShape.CrossCursor)
        self.message.setText(f"Click the state the transition from {self._pick_source} goes to (Esc cancels).")

    def add_transition(self, source: str, target: str, guard: str = "", action: str = "") -> ETransition:
        t = ETransition(source, target, guard, action)
        self.chart.transitions.append(t)
        self.rebuild(select=t)
        return t

    def _picked(self, target: str) -> None:
        source, self._pick_source = self._pick_source, None
        self.scene.picking = False
        self.view.unsetCursor()
        if source is not None:
            self.add_transition(source, target)
            self.tr_guard.setFocus()

    def keyPressEvent(self, event: Any) -> None:
        if event.key() == Qt.Key.Key_Escape and self.scene.picking:
            self.scene.picking, self._pick_source = False, None
            self.view.unsetCursor()
            self._validate()
            return
        super().keyPressEvent(event)

    def make_initial(self) -> None:
        sel = self.selected_state()
        if sel is None:
            return
        parent = self.chart.state(sel).parent
        if parent is None:
            self.chart.initial = sel
        else:
            self.chart.state(parent).initial = sel
        self.rebuild(select=sel)

    def delete_selected(self) -> None:
        for item in list(self.scene.selectedItems()):
            if isinstance(item, TransitionItem) and item.transition in self.chart.transitions:
                self.chart.transitions.remove(item.transition)
        for item in list(self.scene.selectedItems()):
            if isinstance(item, StateItem) and any(s.name == item.name for s in self.chart.states):
                self.chart.remove_state(item.name)
        self.rebuild()

    def tidy(self) -> None:
        self.chart.layout.clear()
        self.rebuild()

    def _rename(self) -> None:
        sel = self.selected_state()
        new = self.state_name.text().strip()
        if self._loading or sel is None or new == sel:
            return
        try:
            self.chart.rename_state(sel, new)
        except ValueError as exc:
            self._show_error(str(exc))
            self.state_name.setText(sel)
            return
        self.rebuild(select=new)

    def _set_state_field(self, kind: str, value: Any) -> None:
        sel = self.selected_state()
        if self._loading or sel is None:
            return
        setattr(self.chart.state(sel), kind, value)
        if kind == "parallel":
            self.state_history.setEnabled(not value)
        self.state_items[sel].update()
        self._validate()
        if kind == "parallel":
            self.rebuild(select=sel)

    def _set_transition_field(self, kind: str, value: str) -> None:
        tr = self.selected_transition()
        if self._loading or tr is None:
            return
        setattr(tr, kind, value)
        for ti in self.transition_items:
            if ti.transition is tr:
                ti.prepareGeometryChange()
                ti.update()
        self._validate()

    def _move_priority(self, delta: int) -> None:
        tr = self.selected_transition()
        if tr is not None:
            self.chart.move_priority(tr, delta)
            self.rebuild(select=tr)

    def _set_declaration(self, key: str, text: str) -> None:
        if self._loading:
            return
        parts = [p.strip() for p in text.split(",") if p.strip()]
        if key in ("outputs", "locals"):
            pairs = []
            for p in parts:
                name, _eq, init = p.partition("=")
                pairs.append((name.strip(), init.strip() or "0"))
            setattr(self.chart, key, pairs)
        else:
            setattr(self.chart, key, parts)
        self._validate()

    # ------------------------------------------------------------------ text, validation, apply

    def _tab_changed(self, index: int) -> None:
        if index == 1:
            try:
                self.text.setPlainText(self.chart.to_text())
            except ParameterError as exc:
                self.text.setPlainText(f"# The chart is not valid yet: {exc}\n")
        else:
            self._read_text()

    def _read_text(self) -> bool:
        text = self.text.toPlainText()
        if not text.strip() or text.startswith("# The chart is not valid yet"):
            return True
        try:
            self.chart = from_text(text, self.chart.layout)
        except ParameterError as exc:
            self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(1)
            self.tabs.blockSignals(False)
            self._show_error(f"The text is not a valid chart: {exc}")
            return False
        self.rebuild()
        return True

    def _show_error(self, text: str) -> None:
        self.message.setStyleSheet(f"color: {current_theme().error};")
        self.message.setText(text)

    def _validate(self) -> str | None:
        """The chart's text, or None (with the reason shown) if it is not valid."""
        try:
            text = self.chart.to_text()
        except ParameterError as exc:
            self._show_error(str(exc))
            self.apply_button.setEnabled(False)
            self.ok_button.setEnabled(False)
            return None
        self.message.setStyleSheet("")
        n_s, n_t = len(self.chart.states), len(self.chart.transitions)
        self.message.setText(f"{n_s} state{'s' * (n_s != 1)}, {n_t} transition{'s' * (n_t != 1)}. Double-click "
                             "empty space to add a state; select a state and press Add transition to connect it.")  # fmt: skip
        self.apply_button.setEnabled(True)
        self.ok_button.setEnabled(True)
        return text

    def apply(self) -> bool:
        if self.tabs.currentIndex() == 1 and not self._read_text():
            return False
        text = self._validate()
        if text is None:
            return False
        layout = {k: [round(v, 1) for v in box] for k, box in self.chart.layout.items()}
        return bool(self.controller.set_chart(self.block, text, layout))

    def _ok(self) -> None:
        if self.apply():
            self.accept()
