"""Linear Analysis dialog: linearize the model between an In and an Out block; Bode, margins, step response."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from nervus.analysis import LinearModel, linearize, trim
from nervus.blocks.ports import Inport, Outport
from nervus.core import Diagram, NervusError
from nervus.gui.theme import current_theme


def _poly(coeffs: np.ndarray) -> str:
    n = len(coeffs) - 1
    terms = []
    for i, c in enumerate(coeffs):
        if abs(c) < 1e-12:
            continue
        p = n - i
        s = "" if p == 0 else "s" if p == 1 else f"s^{p}"
        terms.append(f"{c:.4g}{(' ' + s) if s else ''}")
    return " + ".join(terms).replace("+ -", "- ") or "0"


class AnalysisDialog(QDialog):
    def __init__(self, diagram: Diagram, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.diagram = diagram
        self.lin: LinearModel | None = None
        self.setWindowTitle("Linear Analysis")
        self.resize(960, 680)
        ins = [b.name for b in sorted(diagram.blocks, key=lambda b: b.params.get("port", 0)) if isinstance(b, Inport)]
        outs = [b.name for b in sorted(diagram.blocks, key=lambda b: b.params.get("port", 0)) if isinstance(b, Outport)]
        self.input = QComboBox()
        self.input.addItems(ins)
        self.output = QComboBox()
        self.output.addItems(outs)
        self.point = QComboBox()
        self.point.addItems(["initial states", "steady state (trim)"])
        self.compute = QPushButton("Linearize")
        self.compute.setObjectName("primary")
        form = QFormLayout()
        form.addRow("Input (In block)", self.input)
        form.addRow("Output (Out block)", self.output)
        form.addRow("Operating point", self.point)
        top = QHBoxLayout()
        top.addLayout(form, 1)
        top.addWidget(self.compute, 0, Qt.AlignmentFlag.AlignBottom)

        self.info = QLabel(
            "Linearizes the model from a top-level In block to an Out block. Add In and Out blocks to the model "
            "to choose the input and output."
            if not (ins and outs)
            else "Press Linearize."
        )
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        pg.setConfigOptions(antialias=True)
        t = current_theme()
        self.mag = pg.PlotWidget()
        self.phase = pg.PlotWidget()
        self.step = pg.PlotWidget()
        for w, ylabel in ((self.mag, "magnitude [dB]"), (self.phase, "phase [°]"), (self.step, "output")):
            w.setBackground(t.plot_surface)
            w.showGrid(x=True, y=True, alpha=0.6)
            w.setLabel("left", ylabel)
            for axis in ("left", "bottom"):
                w.getAxis(axis).setPen(pg.mkPen(t.plot_grid))
                w.getAxis(axis).setTextPen(pg.mkPen(t.text_secondary))
        self.mag.setLogMode(x=True)
        self.phase.setLogMode(x=True)
        self.phase.setXLink(self.mag)
        self.phase.setLabel("bottom", "frequency [rad/s]")
        self.step.setLabel("bottom", "time [s]")
        bode = QWidget()
        bl = QVBoxLayout(bode)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.mag)
        bl.addWidget(self.phase)
        self.tabs = QTabWidget()
        self.tabs.addTab(bode, "Bode")
        self.tabs.addTab(self.step, "Step response")

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.info)
        layout.addWidget(self.tabs, 1)
        self.compute.clicked.connect(self.run)
        self.compute.setEnabled(bool(ins and outs))

    def run(self) -> LinearModel | None:
        try:
            x0 = None
            if self.point.currentIndex() == 1:
                op = trim(self.diagram)
                x0 = op.x
            lin = linearize(self.diagram, x0=x0)
        except (NervusError, ValueError, np.linalg.LinAlgError) as exc:
            self.info.setText(f"<span style='color:{current_theme().error}'>{exc}</span>")
            return None
        self.lin = lin
        i, o = self.input.currentIndex(), self.output.currentIndex()
        num, den = lin.transfer_function(i, o)
        re = lin.poles().real
        verdict = (
            "stable"
            if lin.is_stable()
            else "marginally stable (poles on the imaginary axis, e.g. an integrator)"
            if np.all(re <= 1e-9)
            else "NOT stable"
        )
        poles = ", ".join(f"{p.real:.4g}{p.imag:+.4g}j" if abs(p.imag) > 1e-9 else f"{p.real:.4g}" for p in lin.poles())
        m = lin.margins(i, o)
        gm = "∞" if not np.isfinite(m.gain_margin_db) else f"{m.gain_margin_db:.2f} dB at {m.phase_crossover:.3g} rad/s"
        pm = (
            "∞" if not np.isfinite(m.phase_margin_deg) else f"{m.phase_margin_deg:.1f}° at {m.gain_crossover:.3g} rad/s"
        )
        self.info.setText(
            f"<b>G(s)</b> = ({_poly(num)}) / ({_poly(den)})<br>"
            f"<b>Poles</b>: {poles or 'none'} — {verdict}<br>"
            f"<b>DC gain</b>: {lin.dc_gain(i, o):.4g}<br>"
            f"<b>Margins</b> (if G is the open loop of a unity feedback): gain {gm}, phase {pm}"
        )
        t = current_theme()
        w, mag, phase = lin.bode(input=i, output=o)
        self.mag.clear()
        self.phase.clear()
        self.mag.plot(w, mag, pen=pg.mkPen(t.series[0], width=2))
        self.phase.plot(w, phase, pen=pg.mkPen(t.series[0], width=2))
        self.mag.addItem(pg.InfiniteLine(0.0, angle=0, pen=pg.mkPen(t.text_muted, style=Qt.PenStyle.DashLine)))
        self.phase.addItem(pg.InfiniteLine(-180.0, angle=0, pen=pg.mkPen(t.text_muted, style=Qt.PenStyle.DashLine)))
        self.step.clear()
        try:
            ts, ys = lin.step_response(input=i, output=o)
            self.step.plot(ts, ys, pen=pg.mkPen(t.series[0], width=2))
        except ValueError:
            pass
        return lin
