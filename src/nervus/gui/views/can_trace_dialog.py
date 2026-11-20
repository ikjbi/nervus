"""CAN Bus Trace: the frames of the last simulation, per bus, decoded with the model's DBC files."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nervus.can import CanMessage
from nervus.canbus import _REGISTRY, CanBus
from nervus.core import Diagram

MAX_ROWS = 5000


def dbc_messages(diagram: Diagram) -> dict[int, CanMessage]:
    """The messages of every DBC file used by the model's CAN blocks, by identifier."""
    from nervus.blocks.can_blocks import _cached_dbc, _CanBlock

    out: dict[int, CanMessage] = {}
    for _, blk in diagram.walk():
        if isinstance(blk, _CanBlock) and blk.params["dbc_file"]:
            path = blk._path()
            if path.exists():
                try:
                    for m in _cached_dbc(str(path.resolve()), path.stat().st_mtime).values():
                        out.setdefault(m.frame_id, m)
                except Exception:  # an unreadable DBC file: show raw frames
                    continue
    return out


def decode(msg: CanMessage | None, data: bytes) -> str:
    from nervus.can import unpack

    if msg is None:
        return ""
    raw = np.frombuffer(data.ljust(8, b"\0"), dtype=np.uint8).astype(float)
    return ", ".join(f"{s.name}={unpack(s, raw):g}{(' ' + s.unit) if s.unit else ''}" for s in msg.signals)


class CanTraceDialog(QDialog):
    """Frames over time on a simulated bus: time, identifier, sender, bytes and the decoded signals; the bus
    load; export to ASC and BLF."""

    def __init__(self, diagram: Diagram, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("CAN Bus Trace")
        self.resize(900, 480)
        self.messages = dbc_messages(diagram)
        self.bus_box = QComboBox()
        self.bus_box.addItems(sorted(_REGISTRY))
        self.bus_box.currentTextChanged.connect(self.refresh)
        self.info = QLabel()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Time [s]", "ID", "Message", "Sender", "DLC", "Data", "Signals"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        for col, w in enumerate((90, 60, 120, 110, 40, 180)):
            self.tree.setColumnWidth(col, w)
        asc = QPushButton("Export ASC…")
        blf = QPushButton("Export BLF…")
        asc.clicked.connect(lambda: self.export("asc"))
        blf.clicked.connect(lambda: self.export("blf"))
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        top = QHBoxLayout()
        top.addWidget(QLabel("Bus:"))
        top.addWidget(self.bus_box)
        top.addWidget(self.info, 1)
        bottom = QHBoxLayout()
        bottom.addWidget(asc)
        bottom.addWidget(blf)
        bottom.addStretch(1)
        bottom.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.tree, 1)
        layout.addLayout(bottom)
        self.refresh()

    def bus(self) -> CanBus | None:
        return _REGISTRY.get(self.bus_box.currentText())

    def refresh(self) -> None:
        self.tree.clear()
        b = self.bus()
        if b is None or not b.trace:
            self.info.setText("No frames: simulate a model with CAN Transmit or CAN Rest Bus blocks first.")
            return
        t0, t1 = b.trace[0].start, b.trace[-1].end
        lost = sum(f.lost for f in b.trace)
        self.info.setText(
            f"{len(b.trace)} frames in {t1 - t0:.3f} s, bus load {100 * b.load(t0, t1):.1f} % at "
            f"{b.bitrate / 1000:g} kbit/s" + (f", {lost} lost" if lost else "")
            + (f" (showing the first {MAX_ROWS})" if len(b.trace) > MAX_ROWS else "")
        )  # fmt: skip
        items = []
        for f in b.trace[:MAX_ROWS]:
            msg = self.messages.get(f.can_id)
            items.append(
                QTreeWidgetItem([
                    f"{f.end:.6f}", f"0x{f.can_id:03X}", msg.name if msg else "", f.sender, str(len(f.data)),
                    " ".join(f"{x:02X}" for x in f.data), "lost" if f.lost else decode(msg, f.data),
                ])
            )  # fmt: skip
        self.tree.addTopLevelItems(items)

    def export(self, kind: str, path: str | None = None) -> Path | None:
        b = self.bus()
        if b is None:
            return None
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, f"Export {kind.upper()}", f"{b.name}.{kind}",
                                                  f"{kind.upper()} log (*.{kind})")  # fmt: skip
            if not path:
                return None
        return b.write_asc(path) if kind == "asc" else b.write_blf(path)
