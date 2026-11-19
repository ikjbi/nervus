"""Tools → Record from OBD-II: read live data from a car (or a simulated ECU) with live plots."""

from __future__ import annotations

import threading
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from nervus.gui.models.simulation_model import SimulationModel
from nervus.gui.theme import current_theme
from nervus.obd import PIDS, Elm327, ObdError, record
from nervus.sim import SimResult

ELM327, CAN, SIMULATED = "ELM327 adapter (serial port)", "CAN interface (python-can)", "Simulated ECU (OBD Responder)"
DEFAULT_PIDS = ("rpm", "speed", "coolant_temp", "engine_load")
MAX_PLOTS = 6


def serial_ports() -> list[str]:
    """Serial ports that may be an ELM327 (USB or Bluetooth), if pyserial is installed."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [p.device for p in list_ports.comports()]


class _Recorder(QObject):
    sample = Signal(float, object)  # time, {pid: value}
    finished = Signal(object)  # SimResult
    failed = Signal(str)

    def __init__(self, client: Any, pids: list[str], duration: float, interval: float, stop: threading.Event) -> None:
        super().__init__()
        self.client, self.pids, self.duration, self.interval, self.stop = client, pids, duration, interval, stop

    @Slot()
    def run(self) -> None:
        try:
            res = record(
                self.client,
                self.pids,
                self.duration,
                self.interval,
                on_sample=lambda t, v: self.sample.emit(t, dict(v)),
                should_stop=self.stop.is_set,
            )
        except (ObdError, OSError, ValueError) as exc:
            self.failed.emit(str(exc))
        else:
            self.finished.emit(res)


class ObdRecordDialog(QDialog):
    """Connect to a car through an ELM327 or a CAN interface (or to a simulated ECU), choose PIDs and record
    them with live plots; save the drive or open it in the Data Inspector."""

    def __init__(self, sim_model: SimulationModel | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.sim_model = sim_model
        self.setWindowTitle("Record from OBD-II")
        self.resize(980, 720)
        self.client: Any = None
        self.recording: SimResult | None = None
        self._thread: QThread | None = None
        self._stop = threading.Event()
        self._t: list[float] = []
        self._data: dict[str, list[float]] = {}
        self._curves: dict[str, Any] = {}
        self._latest: dict[str, float] = {}
        self._redraw = QTimer(self)
        self._redraw.setSingleShot(True)
        self._redraw.setInterval(100)
        self._redraw.timeout.connect(self._refresh_plots)

        self.source = QComboBox()
        self.source.addItems([ELM327, CAN, SIMULATED])
        self.port = QComboBox()
        self.port.setEditable(True)
        self.port.addItems(serial_ports())
        self.port.setCurrentText(self.port.currentText() or "/dev/tty.usbserial")
        self.can_interface = QComboBox()
        self.can_interface.setEditable(True)
        self.can_interface.addItems(["socketcan", "pcan", "kvaser", "vector", "slcan", "virtual"])
        self.can_channel = QLineEdit("can0")
        self.ecu_name = QLineEdit("ecu")
        pages = QStackedWidget()
        for rows in (
            (("Serial port", self.port),),
            (("Interface", self.can_interface), ("Channel", self.can_channel)),
            (("ECU name", self.ecu_name),),
        ):
            page = QWidget()
            form = QFormLayout(page)
            form.setContentsMargins(0, 0, 0, 0)
            for label, w in rows:
                form.addRow(label, w)
            pages.addWidget(page)
        self.source.currentIndexChanged.connect(pages.setCurrentIndex)
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.connect_car)

        self.pid_list = QListWidget()
        for p in PIDS.values():
            item = QListWidgetItem(f"{p.name}  ({p.unit}) — {p.description}")
            item.setData(Qt.ItemDataRole.UserRole, p.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if p.name in DEFAULT_PIDS else Qt.CheckState.Unchecked)
            self.pid_list.addItem(item)
        self.pid_list.setMaximumHeight(150)
        self.duration = QDoubleSpinBox()
        self.duration.setRange(0.0, 86400.0)
        self.duration.setValue(0.0)
        self.duration.setSpecialValueText("until Stop")
        self.duration.setSuffix(" s")
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.0, 60.0)
        self.interval.setValue(0.0)
        self.interval.setSpecialValueText("as fast as possible")
        self.interval.setSuffix(" s")
        self.record_button = QPushButton("Record")
        self.record_button.setObjectName("primary")
        self.record_button.setEnabled(False)
        self.record_button.clicked.connect(self.toggle)
        self.save_button = QPushButton("Save…")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save)
        self.inspect_button = QPushButton("Open in Data Inspector")
        self.inspect_button.setEnabled(False)
        self.inspect_button.clicked.connect(self.to_inspector)
        self.status = QLabel("Connect to the car (ignition on), choose PIDs and press Record. Nervus only reads.")
        self.status.setWordWrap(True)
        self.plots = pg.GraphicsLayoutWidget()
        self.plots.setBackground(current_theme().plot_surface)

        top = QFormLayout()
        top.addRow("Source", self.source)
        top.addRow("", pages)
        conn = QHBoxLayout()
        conn.addWidget(self.connect_button)
        conn.addStretch(1)
        top.addRow("", conn)
        top.addRow("PIDs", self.pid_list)
        timing = QHBoxLayout()
        timing.addWidget(QLabel("duration"))
        timing.addWidget(self.duration)
        timing.addWidget(QLabel("interval"))
        timing.addWidget(self.interval)
        timing.addStretch(1)
        top.addRow("", timing)
        buttons = QHBoxLayout()
        for b in (self.record_button, self.save_button, self.inspect_button):
            buttons.addWidget(b)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(buttons)
        layout.addWidget(self.status)
        layout.addWidget(self.plots, 1)

    # ------------------------------------------------------------------ connection

    def connect_car(self, client: Any = None) -> bool:
        """Open the chosen source (or use ``client``, e.g. an ``Elm327``) and ask which PIDs it supports."""
        try:
            if client is None:
                client = self._open()
            supported = client.initialize()
        except (ObdError, OSError, ValueError) as exc:
            self.status.setText(f"<span style='color:{current_theme().error}'>{exc}</span>")
            return False
        self.client = client
        for k in range(self.pid_list.count()):
            item = self.pid_list.item(k)
            pid = PIDS[str(item.data(Qt.ItemDataRole.UserRole))]
            ok = pid.pid in supported
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEnabled if ok else item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            if not ok:
                item.setCheckState(Qt.CheckState.Unchecked)
        n = sum(1 for p in PIDS.values() if p.pid in supported)
        self.status.setText(f"Connected: the car reports {n} of the PIDs Nervus decodes.")
        self.record_button.setEnabled(True)
        return True

    def _open(self) -> Any:
        source = self.source.currentText()
        if source == ELM327:
            from nervus.obd import SerialTransport

            return Elm327(SerialTransport(self.port.currentText().strip()))
        if source == CAN:
            from nervus.obd_can import CanObd

            return CanObd(interface=self.can_interface.currentText().strip(), channel=self.can_channel.text().strip())
        from nervus.obd_sim import ecu

        return Elm327(ecu(self.ecu_name.text().strip() or "ecu"))

    def chosen_pids(self) -> list[str]:
        return [
            str(self.pid_list.item(k).data(Qt.ItemDataRole.UserRole))
            for k in range(self.pid_list.count())
            if self.pid_list.item(k).checkState() == Qt.CheckState.Checked
        ]

    # ------------------------------------------------------------------ recording

    @property
    def is_recording(self) -> bool:
        return self._thread is not None

    def toggle(self) -> None:
        if self.is_recording:
            self._stop.set()
        else:
            self.start()

    def start(self) -> bool:
        pids = self.chosen_pids()
        if self.client is None or not pids:
            self.status.setText("Connect first, and tick at least one PID.")
            return False
        self._setup_plots(pids)
        self._stop.clear()
        self.recording = None
        self.record_button.setText("Stop")
        self.save_button.setEnabled(False)
        self.inspect_button.setEnabled(False)
        self.status.setText("Recording…")
        thread = QThread(self)
        worker = _Recorder(self.client, pids, self.duration.value(), self.interval.value(), self._stop)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.sample.connect(self._on_sample)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        self._thread, self._worker = thread, worker
        thread.start()
        return True

    def wait(self, timeout_ms: int = 30000) -> None:
        if self._thread is not None:
            self._thread.wait(timeout_ms)

    def _setup_plots(self, pids: list[str]) -> None:
        t = current_theme()
        self.plots.clear()
        self._t, self._data, self._curves = [], {p: [] for p in pids}, {}
        first = None
        shown = pids[:MAX_PLOTS]
        for k, name in enumerate(shown):
            plot = self.plots.addPlot(row=k, col=0)
            plot.showGrid(x=True, y=True, alpha=0.4)
            plot.setTitle(f"{name} [{PIDS[name].unit}]", size="9pt", color=t.text_secondary)
            if k < len(shown) - 1:
                plot.getAxis("bottom").setStyle(showValues=False)
            if first is None:
                first = plot
            else:
                plot.setXLink(first)
            self._curves[name] = plot.plot(pen=pg.mkPen(t.series[k % len(t.series)], width=2))
        if first is not None:
            self.plots.getItem(min(len(pids), MAX_PLOTS) - 1, 0).setLabel("bottom", "time", units="s")

    @Slot(float, object)
    def _on_sample(self, time: float, values: dict[str, float]) -> None:
        self._t.append(time)
        for name, series in self._data.items():
            series.append(values.get(name, np.nan))
        self._latest = values
        if not self._redraw.isActive():
            self._redraw.start()  # redraw at most 10 times a second, however fast the samples come

    def _refresh_plots(self) -> None:
        if not self._t:
            return
        t = np.asarray(self._t)
        for name, curve in self._curves.items():
            curve.setData(t, np.asarray(self._data[name], dtype=float), connect="finite")
        self.status.setText(
            f"Recording: {len(t)} samples, {t[-1]:.1f} s — "
            + ", ".join(f"{k} = {v:.1f}" for k, v in self._latest.items() if np.isfinite(v))
        )

    @Slot(object)
    def _on_finished(self, result: SimResult) -> None:
        self._thread = None
        self._refresh_plots()
        self.recording = result
        self.record_button.setText("Record")
        self.save_button.setEnabled(True)
        self.inspect_button.setEnabled(self.sim_model is not None)
        self.status.setText(f"Recorded {len(result.t)} samples in {result.t[-1] if len(result.t) else 0:.1f} s.")

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self._thread = None
        self.record_button.setText("Record")
        self.status.setText(f"<span style='color:{current_theme().error}'>{message}</span>")

    def save(self) -> None:
        if self.recording is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save the drive", "drive.nervres", "Nervus results (*.nervres);;CSV (*.csv)"
        )
        if not path:
            return
        if path.endswith(".csv"):
            self.recording.to_csv(path)
        else:
            self.recording.save(path)
        self.status.setText(f"Saved {path}")

    def to_inspector(self) -> None:
        if self.recording is not None and self.sim_model is not None:
            self.sim_model.add_run(self.recording, "OBD recording")
            show = getattr(self.parent(), "show_inspector", None)
            if callable(show):
                show()

    def closeEvent(self, event: Any) -> None:
        if self.is_recording:
            self._stop.set()
            self.wait()
        close = getattr(self.client, "close", None)
        if callable(close):
            close()
        super().closeEvent(event)
