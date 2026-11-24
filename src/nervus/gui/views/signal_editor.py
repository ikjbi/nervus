"""The signal editor of the Signal Builder block: draw piecewise-linear test signals, grouped into scenarios.

Drag a point to move it, double-click in a plot to add one, select a point and press Delete to remove it; the table
shows the selected signal's points exactly. Apply writes the block's *definition* (and *group*) through the editor
controller, so it can be undone.
"""

from __future__ import annotations

import copy
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from nervus.blocks.signal_builder import Signal, SignalGroup, parse_signals, signals_to_text
from nervus.core.block import Block
from nervus.core.errors import ParameterError
from nervus.gui.theme import current_theme, monospace_font


class PointsItem(pg.GraphItem):  # type: ignore[misc]  # pyqtgraph has no type hints
    """The points of one signal: drag one to move it (between its neighbours in time), click to select it."""

    def __init__(self, editor: SignalEditor, index: int) -> None:
        super().__init__()
        self.editor, self.index = editor, index
        self._drag: int | None = None

    def refresh(self) -> None:
        sig = self.editor.signal(self.index)
        t = current_theme()
        sel = self.editor.selected if self.editor.selected[0] == self.index else (self.index, -1)
        color = t.series[self.index % len(t.series)]
        n = len(sig.times)
        chosen = [k == sel[1] for k in range(n)]  # the selected point: larger, with a ring in the text colour
        pos = np.column_stack([sig.times, sig.values]) if sig.times else np.zeros((0, 2))
        adj = np.array([[k, k + 1] for k in range(n - 1)], dtype=int).reshape(-1, 2)
        self.setData(pos=pos, adj=adj, symbol="o", pxMode=True, pen=pg.mkPen(color, width=2),
                     size=[15 if c else 10 for c in chosen],
                     symbolBrush=[pg.mkBrush(color)] * n,
                     symbolPen=[pg.mkPen(t.text, width=2.5) if c else pg.mkPen(color) for c in chosen])  # fmt: skip

    def _point_at(self, pos: QPointF) -> int | None:
        pts = self.scatter.pointsAt(pos)
        return int(pts[0].index()) if len(pts) else None

    def mouseClickEvent(self, ev: Any) -> None:
        k = self._point_at(ev.pos())
        if k is None:
            ev.ignore()
            return
        ev.accept()
        self.editor.select(self.index, k)

    def mouseDragEvent(self, ev: Any) -> None:
        if ev.button() != Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        if ev.isStart():
            k = self._point_at(ev.buttonDownPos())
            if k is None:
                ev.ignore()
                return
            self._drag = k
            self.editor.select(self.index, k)
        elif self._drag is None:
            ev.ignore()
            return
        ev.accept()
        p = ev.pos()
        self.editor.move_point(self.index, self._drag, p.x(), p.y())
        if ev.isFinish():
            self._drag = None


class SignalEditor(QDialog):
    """Edit a Signal Builder block. ``controller`` is the editor controller (``set_params``)."""

    def __init__(self, block: Block, controller: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.block, self.controller = block, controller
        self.setWindowTitle(f"Signals — {block.name}")
        self.resize(1150, 700)
        self.groups: list[SignalGroup] = parse_signals(str(block.params["definition"]))
        names = [g.name for g in self.groups]
        chosen = str(block.params["group"]).strip()
        self.current = names.index(chosen) if chosen in names else 0
        self.selected: tuple[int, int] = (0, -1)  # (signal, point)
        self._loading = False

        # groups
        self.group_list = QListWidget()
        self.group_list.currentRowChanged.connect(self._group_changed)
        group_buttons = QHBoxLayout()
        for text, slot, tip in (("Add", self.add_group, "A new group, a copy of this one"),
                                ("Rename", self.rename_group, "Rename this group"),
                                ("Delete", self.delete_group, "Delete this group")):  # fmt: skip
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, s=slot: s())
            group_buttons.addWidget(b)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        title = QLabel("<b>Groups</b> (scenarios)")
        lv.addWidget(title)
        lv.addWidget(self.group_list, 1)
        lv.addLayout(group_buttons)
        self.play_label = QLabel()
        self.play_label.setWordWrap(True)
        self.play_label.setObjectName("muted")
        lv.addWidget(self.play_label)
        self.play_button = QPushButton("Play this group")
        self.play_button.setToolTip("Make this the group the simulation uses")
        self.play_button.clicked.connect(self._play)
        lv.addWidget(self.play_button)
        self.played = chosen if chosen in names else names[0]

        # plots
        t = current_theme()
        self.plots = pg.GraphicsLayoutWidget()
        self.plots.setBackground(t.plot_surface)
        self.text = QPlainTextEdit()
        self.text.setFont(monospace_font())
        self.tabs = QTabWidget()
        self.tabs.addTab(self.plots, "Signals")
        self.tabs.addTab(self.text, "Text")
        self.tabs.currentChanged.connect(self._tab_changed)

        # table of the selected signal
        self.table_title = QLabel()
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["time [s]", "value"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemChanged.connect(self._table_edited)
        self.table.cellClicked.connect(lambda r, _c: self.select(self.selected[0], r))
        signal_buttons = QHBoxLayout()
        for text, slot, tip in (("Add signal", self.add_signal, "A new signal (an output) in every group"),
                                ("Rename", self.rename_signal, "Rename the selected signal"),
                                ("Remove", self.remove_signal, "Remove the selected signal from every group")):  # fmt: skip
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, s=slot: s())
            signal_buttons.addWidget(b)
        point_buttons = QHBoxLayout()
        for text, slot, tip in (("Add point", self.add_point_after, "A point after the selected one"),
                                ("Delete point", self.delete_point, "Delete the selected point (Delete key)")):  # fmt: skip
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, s=slot: s())
            point_buttons.addWidget(b)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(self.table_title)
        rv.addWidget(self.table, 1)
        rv.addLayout(point_buttons)
        rv.addLayout(signal_buttons)
        hint = QLabel("Drag a point to move it; double-click in a plot to add one; Delete removes the selected "
                      "point. Two points at the same time make a jump.")  # fmt: skip
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        rv.addWidget(hint)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(self.tabs)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([200, 680, 270])

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
        bottom = QHBoxLayout()
        bottom.addWidget(self.message, 1)
        for b in (self.apply_button, self.ok_button, cancel):
            bottom.addWidget(b)
        layout = QVBoxLayout(self)
        layout.addWidget(split, 1)
        layout.addLayout(bottom)
        for b in self.findChildren(QPushButton):
            b.setAutoDefault(False)  # Enter in the table must not press a button
        self.points: list[PointsItem] = []
        self._refresh_groups()
        self.rebuild()

    # ------------------------------------------------------------------ model access

    @property
    def group(self) -> SignalGroup:
        return self.groups[self.current]

    def signal(self, index: int) -> Signal:
        return self.group.signals[index]

    # ------------------------------------------------------------------ drawing

    def rebuild(self) -> None:
        """Draw the plots again (one per signal, time axes linked)."""
        self.plots.clear()
        self.points = []
        t = current_theme()
        first = None
        end = max(max(s.times) for s in self.group.signals) if self.group.signals else 10.0
        for k, sig in enumerate(self.group.signals):
            plot = self.plots.addPlot(row=k, col=0)
            plot.setLabel("left", sig.name)
            plot.showGrid(x=True, y=True, alpha=0.25)
            plot.getAxis("left").setTextPen(t.text)
            plot.getAxis("bottom").setTextPen(t.text)
            if first is None:
                first = plot
            else:
                plot.setXLink(first)
            if k == len(self.group.signals) - 1:
                plot.setLabel("bottom", "time", units="s")
            item = PointsItem(self, k)
            plot.addItem(item)
            item.refresh()
            self.points.append(item)
            plot.setXRange(0.0, end * 1.1 + 1e-9, padding=0.02)
            vals = sig.values
            lo, hi = min(vals), max(vals)
            span = (hi - lo) or max(abs(hi), 1.0)
            plot.setYRange(lo - 0.15 * span, hi + 0.15 * span, padding=0)
            plot.vb.setMouseEnabled(x=True, y=False)
            plot.scene().sigMouseClicked.connect(self._scene_clicked)
        self._refresh_table()
        self._validate()

    def _refresh_points(self) -> None:
        for item in self.points:
            item.refresh()
        self._refresh_table()
        self._validate()

    def _refresh_groups(self) -> None:
        self._loading = True
        self.group_list.clear()
        for g in self.groups:
            self.group_list.addItem(g.name + ("  ▶" if g.name == self.played else ""))
        self.group_list.setCurrentRow(self.current)
        self.play_label.setText(f"The simulation plays <b>{self.played}</b>.")
        self._loading = False

    def _refresh_table(self) -> None:
        self._loading = True
        k, p = self.selected
        k = min(k, len(self.group.signals) - 1)
        sig = self.signal(k)
        self.table_title.setText(f"<b>{sig.name}</b> in group {self.group.name}")
        self.table.setRowCount(len(sig.times))
        for r, (tt, v) in enumerate(zip(sig.times, sig.values, strict=True)):
            self.table.setItem(r, 0, QTableWidgetItem(f"{tt:g}"))
            self.table.setItem(r, 1, QTableWidgetItem(f"{v:g}"))
        if 0 <= p < len(sig.times):
            self.table.selectRow(p)
        self._loading = False

    # ------------------------------------------------------------------ points

    def select(self, signal: int, point: int) -> None:
        self.selected = (signal, point)
        self._refresh_points()

    def move_point(self, signal: int, k: int, t: float, v: float) -> None:
        sig = self.signal(signal)
        lo = sig.times[k - 1] if k > 0 else 0.0
        hi = sig.times[k + 1] if k + 1 < len(sig.times) else float("inf")
        sig.times[k] = float(min(max(t, lo), hi))
        sig.values[k] = float(v)
        self.selected = (signal, k)
        self._refresh_points()

    def add_point(self, signal: int, t: float, v: float) -> int:
        sig = self.signal(signal)
        k = int(np.searchsorted(sig.times, t, side="right"))
        sig.times.insert(k, float(t))
        sig.values.insert(k, float(v))
        self.select(signal, k)
        return k

    def add_point_after(self) -> None:
        s, k = self.selected
        sig = self.signal(s)
        k = k if 0 <= k < len(sig.times) else len(sig.times) - 1
        t = sig.times[k] + (sig.times[k + 1] - sig.times[k]) / 2 if k + 1 < len(sig.times) else sig.times[k] + 1.0
        self.add_point(s, t, sig.value(t))

    def delete_point(self) -> None:
        s, k = self.selected
        sig = self.signal(s)
        if not 0 <= k < len(sig.times):
            return
        if len(sig.times) == 1:
            self.message.setText("A signal needs at least one point.")
            return
        del sig.times[k], sig.values[k]
        self.select(s, min(k, len(sig.times) - 1))

    def _scene_clicked(self, ev: Any) -> None:
        if not ev.double():
            return
        for k, item in enumerate(self.points):
            vb = item.getViewBox()
            if vb is not None and vb.sceneBoundingRect().contains(ev.scenePos()):
                p = vb.mapSceneToView(ev.scenePos())
                self.add_point(k, max(p.x(), 0.0), p.y())
                ev.accept()
                return

    def keyPressEvent(self, event: Any) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and not self.table.hasFocus():
            self.delete_point()
            return
        super().keyPressEvent(event)

    def _table_edited(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        s, _ = self.selected
        sig = self.signal(s)
        r = item.row()
        try:
            value = float(item.text())
        except ValueError:
            self._refresh_table()
            return
        if item.column() == 0:
            sig.times[r] = value
            order = sorted(range(len(sig.times)), key=lambda i: sig.times[i])  # keep the points in time order
            sig.times[:] = [sig.times[i] for i in order]
            sig.values[:] = [sig.values[i] for i in order]
            r = order.index(r)
        else:
            sig.values[r] = value
        self.selected = (s, r)
        self.rebuild()

    # ------------------------------------------------------------------ signals and groups

    def add_signal(self, name: str | None = None) -> None:
        if name is None:
            name, ok = QInputDialog.getText(self, "Add signal", "Name of the new signal (an output of the block):")
            if not ok:
                return
        name = name.strip()
        if not name.isidentifier() or any(s.name == name for s in self.group.signals):
            self.message.setText(f"'{name}' is not a new, valid name (letters, digits and _).")
            return
        for g in self.groups:
            g.signals.append(Signal(name, [0.0], [0.0]))
        self.selected = (len(self.group.signals) - 1, 0)
        self.rebuild()

    def rename_signal(self, name: str | None = None) -> None:
        s, _ = self.selected
        old = self.signal(s).name
        if name is None:
            name, ok = QInputDialog.getText(self, "Rename signal", "New name:", text=old)
            if not ok:
                return
        name = name.strip()
        if not name.isidentifier() or any(x.name == name for x in self.group.signals if x.name != old):
            self.message.setText(f"'{name}' is not a new, valid name (letters, digits and _).")
            return
        for g in self.groups:
            g.signal(old).name = name
        self.rebuild()

    def remove_signal(self) -> None:
        if len(self.group.signals) == 1:
            self.message.setText("The block needs at least one signal.")
            return
        s, _ = self.selected
        for g in self.groups:
            del g.signals[s]
        self.selected = (max(0, s - 1), -1)
        self.rebuild()

    def add_group(self, name: str | None = None) -> None:
        if name is None:
            name, ok = QInputDialog.getText(self, "Add group", "Name of the new group (a copy of this one):",
                                            text=f"{self.group.name}_2")  # fmt: skip
            if not ok:
                return
        name = name.strip()
        if not name.isidentifier() or any(g.name == name for g in self.groups):
            self.message.setText(f"'{name}' is not a new, valid group name.")
            return
        new = copy.deepcopy(self.group)
        new.name = name
        self.groups.append(new)
        self.current = len(self.groups) - 1
        self._refresh_groups()
        self.rebuild()

    def rename_group(self, name: str | None = None) -> None:
        if name is None:
            name, ok = QInputDialog.getText(self, "Rename group", "New name:", text=self.group.name)
            if not ok:
                return
        name = name.strip()
        if not name.isidentifier() or any(g.name == name for g in self.groups if g is not self.group):
            self.message.setText(f"'{name}' is not a new, valid group name.")
            return
        if self.played == self.group.name:
            self.played = name
        self.group.name = name
        self._refresh_groups()
        self.rebuild()

    def delete_group(self) -> None:
        if len(self.groups) == 1:
            self.message.setText("The block needs at least one group.")
            return
        gone = self.groups.pop(self.current)
        if self.played == gone.name:
            self.played = self.groups[0].name
        self.current = min(self.current, len(self.groups) - 1)
        self._refresh_groups()
        self.rebuild()

    def _group_changed(self, row: int) -> None:
        if self._loading or row < 0:
            return
        self.current = row
        self.selected = (min(self.selected[0], len(self.group.signals) - 1), -1)
        self.rebuild()

    def _play(self) -> None:
        self.played = self.group.name
        self._refresh_groups()

    # ------------------------------------------------------------------ text, apply

    def _tab_changed(self, index: int) -> None:
        if index == 1:
            try:
                self.text.setPlainText(signals_to_text(self.groups))
            except ParameterError as exc:
                self.text.setPlainText(f"# not valid yet: {exc}\n")
            return
        try:
            groups = parse_signals(self.text.toPlainText())
        except ParameterError as exc:
            self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(1)
            self.tabs.blockSignals(False)
            self.message.setText(f"The text is not valid: {exc}")
            return
        self.groups = groups
        names = [g.name for g in groups]
        self.current = min(self.current, len(groups) - 1)
        if self.played not in names:
            self.played = names[0]
        self.selected = (0, -1)
        self._refresh_groups()
        self.rebuild()

    def _validate(self) -> str | None:
        try:
            text = signals_to_text(self.groups)
        except ParameterError as exc:
            self.message.setStyleSheet(f"color: {current_theme().error};")
            self.message.setText(str(exc))
            self.apply_button.setEnabled(False)
            self.ok_button.setEnabled(False)
            return None
        self.message.setStyleSheet("")
        n = len(self.group.signals)
        self.message.setText(f"{len(self.groups)} group(s), {n} signal(s): the block has {n} output(s).")
        self.apply_button.setEnabled(True)
        self.ok_button.setEnabled(True)
        return text

    def apply(self) -> bool:
        if self.tabs.currentIndex() == 1:
            self.tabs.setCurrentIndex(0)  # read the text first
            if self.tabs.currentIndex() == 1:
                return False
        text = self._validate()
        if text is None:
            return False
        group = "" if self.played == self.groups[0].name else self.played
        return bool(self.controller.set_params(self.block, {"definition": text, "group": group}))

    def _ok(self) -> None:
        if self.apply():
            self.accept()
