"""Scope window: plots the signals going into a Scope block after a simulation."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from nervus.core import Block
from nervus.gui.models.simulation_model import SimulationModel
from nervus.gui.theme import Theme, ThemeManager, current_theme
from nervus.sim import SimResult


class ScopeWindow(QWidget):
    """One window per Scope block. Updates automatically after each run.

    Series colours come from the theme's categorical palette in a fixed order: input 1 is always the first
    colour. A legend is shown when there is more than one series.
    """

    def __init__(self, block: Block, sim: SimulationModel, parent: QWidget | None = None, path: str = "") -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.block = block
        self.path = path or block.name
        self.sim = sim
        self.setWindowTitle(f"Scope — {self.path}")
        self.resize(760, 460)

        pg.setConfigOptions(antialias=True)
        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True, alpha=0.6)
        self.plot.setLabel("bottom", "time", units="s")
        self.legend = self.plot.addLegend(offset=(10, 10))
        self.readout = QLabel(" ")
        self.readout.setObjectName("muted")
        self.autoscale = QPushButton("Autoscale")
        self.autoscale.clicked.connect(lambda: self.plot.enableAutoRange())
        self.markers = QCheckBox("Show samples")
        self.markers.toggled.connect(lambda _v: self.refresh())

        bar = QHBoxLayout()
        bar.addWidget(self.readout, 1)
        bar.addWidget(self.markers)
        bar.addWidget(self.autoscale)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.plot, 1)
        layout.addLayout(bar)

        self._vline = pg.InfiniteLine(angle=90, movable=False)
        self.plot.addItem(self._vline, ignoreBounds=True)
        self._proxy = pg.SignalProxy(self.plot.scene().sigMouseMoved, rateLimit=30, slot=self._mouse_moved)
        self._series: list[tuple[str, np.ndarray]] = []
        self._t = np.zeros(0)

        sim.resultChanged.connect(self._on_result)
        ThemeManager.instance().themeChanged.connect(self._apply_theme)
        self._apply_theme(current_theme())
        self._on_result(sim.result)

    def _apply_theme(self, t: Theme) -> None:
        self.plot.setBackground(t.plot_surface)
        for axis in ("left", "bottom"):
            ax = self.plot.getAxis(axis)
            ax.setPen(pg.mkPen(t.plot_grid))
            ax.setTextPen(pg.mkPen(t.text_secondary))
        self._vline.setPen(pg.mkPen(t.text_muted, width=1, style=Qt.PenStyle.DashLine))
        self.legend.setLabelTextColor(t.text_secondary)
        self.refresh()

    def _on_result(self, result: SimResult | None) -> None:
        self._series = []
        self._t = np.zeros(0)
        if result is not None and self.path in result.input_keys:
            self._t = result.t
            for key in result.input_keys[self.path]:
                data = result.signals[key]
                label = key[:-2] if key.endswith(":0") else key
                if data.shape[1] == 1:
                    self._series.append((label, data[:, 0]))
                else:
                    self._series.extend((f"{label}[{j}]", data[:, j]) for j in range(data.shape[1]))
        self.refresh()

    def refresh(self) -> None:
        t = current_theme()
        self.plot.clear()
        self.plot.addItem(self._vline, ignoreBounds=True)
        self.legend.clear()
        self.legend.setVisible(len(self._series) > 1)
        if not self._series:
            self.readout.setText("Run the simulation (⌘R / Ctrl+R) to see data.")
            return
        for i, (name, y) in enumerate(self._series[: len(t.series)]):
            color = t.series[i]
            kwargs = {}
            if self.markers.isChecked():
                kwargs = {"symbol": "o", "symbolSize": 5, "symbolBrush": color, "symbolPen": None}
            self.plot.plot(self._t, y, pen=pg.mkPen(color, width=2), name=name, **kwargs)
        hidden = len(self._series) - len(t.series)
        self.readout.setText(
            f"{len(self._series)} signal(s), {len(self._t)} points"
            + (f" — {hidden} more not shown (max {len(t.series)})" if hidden > 0 else "")
        )

    def _mouse_moved(self, evt: tuple[object]) -> None:
        if not self._series or self._t.size == 0:
            return
        pos = evt[0]
        item = self.plot.getPlotItem()
        if not item.sceneBoundingRect().contains(pos):
            return
        vb = item.vb
        x = vb.mapSceneToView(pos).x()
        k = int(np.clip(np.searchsorted(self._t, x), 0, self._t.size - 1))
        self._vline.setPos(self._t[k])
        values = "   ".join(f"{name} = {y[k]:.6g}" for name, y in self._series[:8])
        self.readout.setText(f"t = {self._t[k]:.6g} s   {values}")
