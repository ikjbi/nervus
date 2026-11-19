"""Parameter Sweep / Monte Carlo dialog: run the model many times and compare the results."""

from __future__ import annotations

import re
import threading
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from nervus.core import Diagram, NervusError
from nervus.core.expressions import format_value, parse_value
from nervus.gui.controllers.editor_controller import EditorController
from nervus.gui.theme import current_theme
from nervus.sim import SimResult, compile_diagram
from nervus.sweep import STATISTICS, SweepTable, grid_points, metric, random_points, run_points

SWEEP, MONTE_CARLO = "Sweep (every combination)", "Monte Carlo (random values)"
_DIST = re.compile(r"^\s*(normal|uniform)\s*\(\s*([^,]+),\s*([^)]+)\)\s*$")


def parse_values(text: str) -> list[float]:
    """Values for a sweep: ``0.5, 1, 2``, ``[0.5 1 2]`` or ``linspace(0.5, 2, 4)``."""
    m = re.match(r"^\s*linspace\s*\(([^,]+),([^,]+),([^)]+)\)\s*$", text)
    if m:
        a, b, n = (float(parse_value(x.strip())) for x in m.groups())
        return [float(v) for v in np.linspace(a, b, int(n))]
    t = text.strip()
    v = parse_value(t if t.startswith("[") else f"[{t}]")
    return [float(x) for x in np.ravel(v)]


def parse_distribution(text: str) -> tuple[str, float, float]:
    """``normal(mean, std)`` or ``uniform(low, high)``."""
    m = _DIST.match(text)
    if m is None:
        raise ValueError(f"{text!r}: write normal(mean, std) or uniform(low, high)")
    return (m.group(1), float(parse_value(m.group(2).strip())), float(parse_value(m.group(3).strip())))


class _Worker(QObject):
    progress = Signal(int, object, object)  # run index, row, (t, y) of the plotted signal or None
    finished = Signal(object)  # SweepTable

    def __init__(
        self, diagram: Diagram, points: list[dict[str, Any]], signal: str, stat: str, stop: threading.Event
    ) -> None:
        super().__init__()
        self.diagram, self.points, self.signal, self.stat, self.stop = diagram, points, signal, stat, stop

    @Slot()
    def run(self) -> None:
        name = f"{self.stat}({self.signal})"

        def on_result(k: int, row: dict[str, Any], res: SimResult | None) -> None:
            trace = None
            if res is not None:
                y = np.asarray(res[self.signal], dtype=float)
                trace = (res.t, y if y.ndim == 1 else y[:, 0])
            self.progress.emit(k, row, trace)

        table = run_points(
            self.diagram,
            self.points,
            {name: metric(self.signal, self.stat)},
            on_result=on_result,
            should_stop=self.stop.is_set,
        )
        self.finished.emit(table)


class SweepDialog(QDialog):
    """Analysis → Parameter Sweep: vary workspace variables over a grid or randomly, plot a signal of every run
    and a metric (final value, maximum, ...) against the parameters."""

    def __init__(self, diagram: Diagram, editor: EditorController, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.diagram, self.editor = diagram, editor
        self.setWindowTitle("Parameter Sweep")
        self.resize(1000, 700)
        self.table: SweepTable | None = None
        self.traces: list[tuple[dict[str, Any], tuple[np.ndarray, np.ndarray]]] = []
        self._param_names: list[str] = []
        self._thread: QThread | None = None
        self._worker: _Worker | None = None
        self._stop = threading.Event()

        self.mode = QComboBox()
        self.mode.addItems([SWEEP, MONTE_CARLO])
        self.params = QTableWidget(0, 2)
        self.params.setHorizontalHeaderLabels(["Variable", "Values"])
        self.params.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.params.verticalHeader().setVisible(False)
        self.params.setMaximumHeight(130)
        add, remove = QPushButton("Add Variable"), QPushButton("Remove")
        add.clicked.connect(lambda: self.add_parameter())
        remove.clicked.connect(lambda: self.params.removeRow(max(0, self.params.currentRow())))
        self.runs = QSpinBox()
        self.runs.setRange(1, 100000)
        self.runs.setValue(50)
        self.seed = QSpinBox()
        self.seed.setRange(0, 2**31 - 1)
        self.seed.setValue(1)
        self.signal = QComboBox()
        self.signal.setEditable(True)
        self.signal.addItems(self._signal_names())
        self.stat = QComboBox()
        self.stat.addItems(list(STATISTICS))
        self.run_button = QPushButton("Run")
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(self.toggle)
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.status = QLabel(" ")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Mode", self.mode)
        rowbtn = QHBoxLayout()
        rowbtn.addWidget(add)
        rowbtn.addWidget(remove)
        rowbtn.addStretch(1)
        form.addRow("Variables", self.params)
        form.addRow("", rowbtn)
        mc = QHBoxLayout()
        mc.addWidget(QLabel("runs"))
        mc.addWidget(self.runs)
        mc.addWidget(QLabel("seed"))
        mc.addWidget(self.seed)
        mc.addStretch(1)
        self._mc_row = QWidget()
        self._mc_row.setLayout(mc)
        form.addRow("Monte Carlo", self._mc_row)
        metric_row = QHBoxLayout()
        metric_row.addWidget(self.signal, 2)
        metric_row.addWidget(self.stat, 1)
        form.addRow("Signal, metric", metric_row)

        self.signal_plot = pg.PlotWidget()
        self.metric_plot = pg.PlotWidget()
        for plot in (self.signal_plot, self.metric_plot):
            plot.showGrid(x=True, y=True, alpha=0.5)
            plot.setBackground(current_theme().plot_surface)
        self.signal_plot.setLabel("bottom", "time", units="s")
        self.results = QTableWidget(0, 0)
        export = QPushButton("Export CSV…")
        export.clicked.connect(self.export_csv)
        table_tab = QWidget()
        tl = QVBoxLayout(table_tab)
        tl.addWidget(self.results)
        tl.addWidget(export, 0, Qt.AlignmentFlag.AlignRight)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.signal_plot, "Signal")
        self.tabs.addTab(self.metric_plot, "Metric")
        self.tabs.addTab(table_tab, "Table")

        top = QHBoxLayout()
        top.addLayout(form, 1)
        side = QVBoxLayout()
        side.addWidget(self.run_button)
        side.addWidget(self.progress)
        side.addStretch(1)
        top.addLayout(side)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.status)
        layout.addWidget(self.tabs, 1)

        self.mode.currentTextChanged.connect(self._mode_changed)
        self._mode_changed(self.mode.currentText())

    # ------------------------------------------------------------------ setup

    def _numeric_variables(self) -> list[str]:
        try:
            ns = self.diagram.workspace.namespace()
        except NervusError:
            return list(self.diagram.workspace)
        return [n for n in self.diagram.workspace if n in ns and np.ndim(ns[n]) == 0]

    def _signal_names(self) -> list[str]:
        try:
            m = compile_diagram(self.diagram)
        except NervusError:
            return []
        outs = [b.name for b in self.diagram.blocks if b.type_id == "ports.outport"]
        return outs + [n for n in m.names if n not in outs and "/" not in n]

    def add_parameter(self, name: str | None = None, values: str = "") -> None:
        row = self.params.rowCount()
        self.params.insertRow(row)
        combo = QComboBox()
        combo.addItems(self._numeric_variables())
        if name is not None:
            combo.setCurrentText(name)
        self.params.setCellWidget(row, 0, combo)
        edit = QLineEdit(values or self._default_values(combo.currentText()))
        self.params.setCellWidget(row, 1, edit)
        combo.currentTextChanged.connect(lambda n, e=edit: e.setText(self._default_values(n)))

    def _default_values(self, name: str) -> str:
        try:
            v = float(self.diagram.workspace.namespace()[name])
        except (NervusError, KeyError, TypeError, ValueError):
            return ""
        if self.mode.currentText() == SWEEP:
            return ", ".join(format_value(x) for x in (0.5 * v, v, 1.5 * v)) if v else "0, 1, 2"
        return f"normal({format_value(v)}, {format_value(abs(v) * 0.05 or 0.1)})"

    def _mode_changed(self, mode: str) -> None:
        self._mc_row.setEnabled(mode == MONTE_CARLO)
        self.params.horizontalHeaderItem(1).setText(  # type: ignore[union-attr]
            "Values: 0.5, 1, 2 or linspace(0, 1, 5)"
            if mode == SWEEP
            else "Distribution: normal(mean, std) or uniform(low, high)"
        )
        for row in range(self.params.rowCount()):
            combo, edit = self.params.cellWidget(row, 0), self.params.cellWidget(row, 1)
            if isinstance(combo, QComboBox) and isinstance(edit, QLineEdit):
                edit.setText(self._default_values(combo.currentText()))

    def points(self) -> list[dict[str, Any]]:
        """The runs to make, from the table. Raises ``ValueError`` for invalid entries."""
        spec: dict[str, str] = {}
        for row in range(self.params.rowCount()):
            combo, edit = self.params.cellWidget(row, 0), self.params.cellWidget(row, 1)
            if isinstance(combo, QComboBox) and isinstance(edit, QLineEdit) and combo.currentText():
                spec[combo.currentText()] = edit.text()
        if not spec:
            raise ValueError("add at least one variable to vary")
        if self.mode.currentText() == SWEEP:
            return grid_points({n: parse_values(t) for n, t in spec.items()})
        return random_points({n: parse_distribution(t) for n, t in spec.items()}, self.runs.value(), self.seed.value())

    # ------------------------------------------------------------------ running

    @property
    def is_running(self) -> bool:
        return self._thread is not None

    def toggle(self) -> None:
        if self.is_running:
            self._stop.set()
        else:
            self.start()

    def start(self) -> bool:
        try:
            points = self.points()
        except ValueError as exc:
            self.status.setText(str(exc))
            return False
        signal = self.signal.currentText().strip()
        if not signal:
            self.status.setText("Choose a signal to plot (an Out block or a block name).")
            return False
        self.traces = []
        self.table = None
        self._param_names = list(points[0])
        self._stop.clear()
        self.progress.setRange(0, len(points))
        self.progress.setValue(0)
        self.run_button.setText("Stop")
        self.status.setText(f"Running {len(points)} simulations…")
        self.editor.set_editing_enabled(False)  # the runs read the model on another thread
        thread = QThread(self)
        worker = _Worker(self.diagram, points, signal, self.stat.currentText(), self._stop)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        self._thread, self._worker = thread, worker
        thread.start()
        return True

    def wait(self, timeout_ms: int = 60000) -> None:
        if self._thread is not None:
            self._thread.wait(timeout_ms)

    @Slot(int, object, object)
    def _on_progress(self, k: int, row: dict[str, Any], trace: tuple[np.ndarray, np.ndarray] | None) -> None:
        self.progress.setValue(k + 1)
        if trace is not None:
            self.traces.append((row, trace))
            self._plot_traces()

    @Slot(object)
    def _on_finished(self, table: SweepTable) -> None:
        self.table = table
        self._thread = None
        self.editor.set_editing_enabled(True)
        self.run_button.setText("Run")
        self.status.setText(table.summary().replace("\n", " · "))
        self._plot_metric()
        self._fill_table()

    # ------------------------------------------------------------------ results

    def _label(self, row: dict[str, Any]) -> str:
        return ", ".join(f"{n} = {row[n]:.4g}" for n in self._param_names if isinstance(row.get(n), float | int))

    def _plot_traces(self) -> None:
        t = current_theme()
        self.signal_plot.clear()
        many = len(self.traces) > len(t.series) or self.mode.currentText() == MONTE_CARLO
        legend = self.signal_plot.addLegend(offset=(-10, 10)) if not many else None  # top right
        for k, (row, (time, y)) in enumerate(self.traces):
            if many:  # one hue, transparent: where the runs bunch up is darker
                color = pg.mkColor(t.series[0])
                color.setAlpha(70)
                self.signal_plot.plot(time, y, pen=pg.mkPen(color, width=1.5))
            else:
                self.signal_plot.plot(time, y, pen=pg.mkPen(t.series[k], width=2), name=self._label(row))
        if legend is not None:
            legend.setLabelTextColor(t.text_secondary)
        self.signal_plot.setLabel("left", self.signal.currentText())

    def _plot_metric(self) -> None:
        tab = self.table
        self.metric_plot.clear()
        if tab is None or not tab.metrics or not tab.rows:
            return
        t = current_theme()
        m = tab.metrics[0]
        values = tab.column(m)
        self.metric_plot.setLabel("left", m)
        if self.mode.currentText() == MONTE_CARLO:
            finite = values[np.isfinite(values)]
            if finite.size:
                counts, edges = np.histogram(finite, bins=min(30, max(5, finite.size // 5)))
                self.metric_plot.addItem(
                    pg.BarGraphItem(x0=edges[:-1], x1=edges[1:], height=counts, brush=t.series[0], pen=t.plot_surface)
                )
                self.metric_plot.setLabel("bottom", m)
                self.metric_plot.setLabel("left", "runs")
            return
        x_name = tab.parameters[0]
        x = tab.column(x_name)
        self.metric_plot.setLabel("bottom", x_name)
        if len(tab.parameters) == 1:
            order = np.argsort(x)
            self.metric_plot.plot(x[order], values[order], pen=pg.mkPen(t.series[0], width=2), symbol="o",
                                  symbolBrush=t.series[0], symbolPen=t.plot_surface, symbolSize=8)  # fmt: skip
            return
        legend = self.metric_plot.addLegend(offset=(-10, 10))
        groups = tab.column(tab.parameters[1])
        for k, g in enumerate(sorted(set(groups.tolist()))[: len(t.series)]):
            sel = groups == g
            order = np.argsort(x[sel])
            self.metric_plot.plot(x[sel][order], values[sel][order], pen=pg.mkPen(t.series[k], width=2), symbol="o",
                                  symbolBrush=t.series[k], symbolPen=t.plot_surface, symbolSize=8,
                                  name=f"{tab.parameters[1]} = {g:.4g}")  # fmt: skip
        legend.setLabelTextColor(t.text_secondary)

    def _fill_table(self) -> None:
        tab = self.table
        if tab is None:
            return
        cols = [*tab.parameters, *tab.metrics, "error"]
        self.results.setColumnCount(len(cols))
        self.results.setHorizontalHeaderLabels(cols)
        self.results.setRowCount(len(tab.rows))
        for r, row in enumerate(tab.rows):
            for c, name in enumerate(cols):
                v = row.get(name, "")
                self.results.setItem(r, c, QTableWidgetItem(f"{v:.6g}" if isinstance(v, float) else str(v)))

    def export_csv(self) -> None:
        if self.table is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export results", "sweep.csv", "CSV files (*.csv)")
        if path:
            self.table.to_csv(path)
            self.status.setText(f"Saved {path}")

    def closeEvent(self, event: Any) -> None:
        if self.is_running:
            self._stop.set()
            self.wait()
        super().closeEvent(event)
