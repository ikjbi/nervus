"""Linear Analysis dialog: linearize the model between an In and an Out block; Bode, margins, step response."""

from __future__ import annotations

from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from scipy import signal as sps

from nervus.analysis import LinearModel, PIDGains, feedback, linearize, pid_transfer, plant_at, trim, tune_pid
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
    def __init__(self, diagram: Diagram, parent: QWidget | None = None, editor: Any = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.diagram = diagram
        self.editor = editor  # EditorController, to apply tuned gains (optional)
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
        self.nyq = pg.PlotWidget()
        self.locus = pg.PlotWidget()
        for w, ylabel in (
            (self.mag, "magnitude [dB]"),
            (self.phase, "phase [°]"),
            (self.step, "output"),
            (self.nyq, "imaginary"),
            (self.locus, "imaginary"),
        ):
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
        self.nyq.setLabel("bottom", "real")
        self.locus.setLabel("bottom", "real")
        self.nyq.setAspectLocked(True)
        self.locus.setAspectLocked(True)
        bode = QWidget()
        bl = QVBoxLayout(bode)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.mag)
        bl.addWidget(self.phase)
        self.tabs = QTabWidget()
        self.tabs.addTab(bode, "Bode")
        self.tabs.addTab(self.step, "Step response")
        self.tabs.addTab(self.nyq, "Nyquist")
        self.tabs.addTab(self.locus, "Root locus")
        self.tabs.addTab(self._pid_tab(), "PID Tuning")

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
        legend = self.step.addLegend(offset=(-10, 10))
        try:
            ts, ys = lin.step_response(input=i, output=o)
            self.step.plot(ts, ys, pen=pg.mkPen(t.series[0], width=2), name="G (open loop)")
            tc, yc = sps.step(lin.closed_loop(i, o), N=500)
            self.step.plot(tc, yc, pen=pg.mkPen(t.series[1], width=2), name="G / (1 + G) (closed loop)")
        except ValueError:
            pass
        legend.setLabelTextColor(t.text_secondary)
        self._plot_nyquist(lin, i, o)
        self._plot_locus(lin, i, o)
        return lin

    def _plot_nyquist(self, lin: LinearModel, i: int, o: int) -> None:
        t = current_theme()
        self.nyq.clear()
        re, im = lin.nyquist(input=i, output=o)
        n = re.size // 2
        near = np.hypot(re, im) < 1e3  # an integrator goes to infinity at ω = 0
        re, im = np.where(near, re, np.nan), np.where(near, im, np.nan)
        self.nyq.plot(re[n:], im[n:], pen=pg.mkPen(t.series[0], width=2), connect="finite")  # ω > 0
        self.nyq.plot(re[:n], im[:n], pen=pg.mkPen(t.series[0], width=1, style=Qt.PenStyle.DashLine), connect="finite")
        self.nyq.plot([-1.0], [0.0], pen=None, symbol="+", symbolSize=14, symbolPen=pg.mkPen(t.error, width=2))
        label = pg.TextItem("−1", color=t.text_secondary, anchor=(0, 1))
        label.setPos(-1.0, 0.0)
        self.nyq.addItem(label)
        reach = float(np.nanmax(np.hypot(re, im))) if np.any(np.isfinite(re)) else 1.0
        if reach > 5.0:  # what matters is the curve near -1: zoom in there
            self.nyq.setRange(xRange=(-4.0, 2.0), yRange=(-3.0, 3.0))

    def _plot_locus(self, lin: LinearModel, i: int, o: int) -> None:
        t = current_theme()
        self.locus.clear()
        _gains, poles = lin.root_locus(input=i, output=o)
        for k in range(poles.shape[1]):
            branch = poles[:, k]
            ok = np.isfinite(branch)
            self.locus.plot(branch.real[ok], branch.imag[ok], pen=pg.mkPen(t.series[0], width=2))
        p0, z0 = lin.poles(), lin.zeros(i, o)
        self.locus.plot(p0.real, p0.imag, pen=None, symbol="x", symbolSize=12, symbolPen=pg.mkPen(t.text, width=2))
        if z0.size:
            self.locus.plot(z0.real, z0.imag, pen=None, symbol="o", symbolSize=10, symbolBrush=None,
                            symbolPen=pg.mkPen(t.text, width=2))  # fmt: skip
        self.locus.addItem(pg.InfiniteLine(0.0, angle=90, pen=pg.mkPen(t.text_muted, style=Qt.PenStyle.DashLine)))

    # ------------------------------------------------------------------ PID tuning

    def _controllers(self) -> list[str]:
        return [path for path, b in self.diagram.walk() if b.type_id in ("control.pid", "control.discrete_pid")]

    def _pid_tab(self) -> QWidget:
        tab = QWidget()
        self.pid_block = QComboBox()
        self.pid_block.addItems(self._controllers())
        self.pid_form = QComboBox()
        self.pid_form.addItems(["PI", "PID"])
        self.pid_pm = QDoubleSpinBox()
        self.pid_pm.setRange(20.0, 85.0)
        self.pid_pm.setValue(60.0)
        self.pid_pm.setSuffix(" °")
        self.pid_tune = QPushButton("Tune")
        self.pid_tune.setObjectName("primary")
        self.pid_apply = QPushButton("Apply to Block")
        self.pid_apply.setEnabled(False)
        self.pid_info = QLabel(
            "Opens the loop at a PID Controller block, linearizes the plant it controls and tunes the gains for "
            "the phase margin you choose."
            if self.pid_block.count()
            else "The model has no PID Controller block."
        )
        self.pid_info.setWordWrap(True)
        self.pid_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.pid_plot = pg.PlotWidget()
        self.pid_plot.setBackground(current_theme().plot_surface)
        self.pid_plot.showGrid(x=True, y=True, alpha=0.6)
        self.pid_plot.setLabel("bottom", "time", units="s")
        self.pid_plot.setLabel("left", "closed-loop step response")
        form = QFormLayout()
        form.addRow("Controller block", self.pid_block)
        form.addRow("Form", self.pid_form)
        form.addRow("Phase margin", self.pid_pm)
        buttons = QHBoxLayout()
        buttons.addWidget(self.pid_tune)
        buttons.addWidget(self.pid_apply)
        buttons.addStretch(1)
        layout = QVBoxLayout(tab)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addWidget(self.pid_info)
        layout.addWidget(self.pid_plot, 1)
        self.pid_tune.setEnabled(self.pid_block.count() > 0)
        self.pid_tune.clicked.connect(self.tune)
        self.pid_apply.clicked.connect(self.apply_gains)
        self.tuned: PIDGains | None = None
        return tab

    def tune(self) -> PIDGains | None:
        path = self.pid_block.currentText()
        block = dict(self.diagram.walk()).get(path)
        if block is None:
            return None
        try:
            plant = plant_at(self.diagram, path)
            st = block.resolved_sample_time
            cap = 2 * np.pi / (20 * st.period) if st is not None and st.is_discrete else None
            gains = tune_pid(plant, self.pid_form.currentText(), self.pid_pm.value(), max_crossover=cap)
        except (NervusError, ValueError, np.linalg.LinAlgError) as exc:
            self.pid_info.setText(f"<span style='color:{current_theme().error}'>{exc}</span>")
            self.pid_apply.setEnabled(False)
            return None
        self.tuned = gains
        gnum, gden = plant.transfer_function()
        p = block.params
        t = current_theme()
        self.pid_plot.clear()
        legend = self.pid_plot.addLegend(offset=(-10, -10))  # bottom right, below the settled responses
        horizon = 8.0 / gains.crossover
        tt = np.linspace(0.0, horizon, 600)
        for k, (label, c) in enumerate(
            (
                ("current gains", pid_transfer(float(p["P"]), float(p["I"]), float(p["D"]), float(p["N"]))),
                ("tuned gains", pid_transfer(gains.P, gains.I, gains.D, gains.N)),
            )
        ):
            lnum, lden = np.polymul(c[0], gnum), np.polymul(c[1], gden)
            try:
                _t, y = sps.step(feedback(np.asarray(lnum, float), np.asarray(lden, float)), T=tt)
            except ValueError:
                continue
            self.pid_plot.plot(tt, y, pen=pg.mkPen(t.series[k], width=2), name=label)
        legend.setLabelTextColor(t.text_secondary)
        cap_note = f" (limited to 2π/(20·Ts) = {cap:.3g} rad/s for the {st.period:g} s task)" if cap and st else ""
        self.pid_info.setText(
            f"<b>Plant</b> G(s) = ({_poly(gnum)}) / ({_poly(gden)})<br>"
            f"<b>Tuned</b>: P = {gains.P:.4g}, I = {gains.I:.4g}, D = {gains.D:.4g}, N = {gains.N:.4g}<br>"
            f"Crossover {gains.crossover:.3g} rad/s{cap_note}, phase margin {gains.phase_margin:.1f}°, "
            f"gain margin {'∞' if not np.isfinite(gains.gain_margin_db) else f'{gains.gain_margin_db:.1f} dB'}"
        )
        self.pid_apply.setEnabled(self.editor is not None)
        return gains

    def apply_gains(self) -> bool:
        """Write the tuned gains into the block; a gain given as a workspace variable updates the variable."""
        if self.tuned is None or self.editor is None:
            return False
        block = dict(self.diagram.walk()).get(self.pid_block.currentText())
        if block is None:
            return False
        values = (
            self.tuned.as_params()
            if self.pid_form.currentText() == "PID"
            else {"P": self.tuned.P, "I": self.tuned.I, "D": 0.0}
        )
        direct: dict[str, float] = {}
        ok = True
        for name, value in values.items():
            source = block.param_source(name)
            if isinstance(source, str) and source.isidentifier() and source in self.diagram.workspace:
                ok = self.editor.update_variable(source, value=float(value)) and ok
            else:
                direct[name] = float(value)
        if direct:
            ok = self.editor.set_params(block, direct) and ok
        return bool(ok)
