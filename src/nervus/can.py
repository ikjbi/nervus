"""CAN messages: read DBC files and pack/unpack signals bit-exactly.

DBC files describe which bits of a CAN frame carry which signal, and how the raw integer maps to a physical
value (``physical = raw · factor + offset``). Parsing uses ``cantools`` (``uv sync --extra can``); packing
and unpacking are implemented here with the same integer arithmetic the generated C code uses, so the
simulation and the ECU code agree bit for bit.

Bit layout: the 8 data bytes are viewed as one 64-bit word. For **Intel** (little-endian, ``@1``) signals byte
0 is the least significant byte and the start bit is the signal's LSB. For **Motorola** (big-endian, ``@0``)
byte 0 is the most significant byte and the DBC start bit is the signal's MSB in the DBC's "sawtooth"
numbering.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from nervus.core.errors import ParameterError
from nervus.core.types import Array


@dataclass(frozen=True)
class CanSignal:
    name: str
    start: int
    length: int
    little_endian: bool
    signed: bool
    factor: float
    offset: float
    minimum: float | None = None
    maximum: float | None = None
    unit: str = ""
    comment: str = ""

    @property
    def shift(self) -> int:
        """Right shift of the 64-bit word (in the frame's byte order) that brings the signal to bit 0."""
        if self.little_endian:
            return self.start
        msb = 8 * (self.start // 8) + (7 - self.start % 8)  # position counted from the word's MSB
        return 64 - (msb + self.length)

    @property
    def mask(self) -> int:
        return (1 << self.length) - 1


@dataclass(frozen=True)
class CanMessage:
    name: str
    frame_id: int
    length: int
    signals: tuple[CanSignal, ...]
    comment: str = ""
    sender: str = ""
    cycle_time: float | None = None
    """Transmission period in seconds (the DBC attribute GenMsgCycleTime), if the DBC file has it."""

    def signal(self, name: str) -> CanSignal:
        for s in self.signals:
            if s.name == name:
                return s
        raise KeyError(f"message {self.name} has no signal {name}")


def load_dbc(path: str | Path) -> dict[str, CanMessage]:
    """Messages of a DBC file, by name."""
    try:
        import cantools
    except ImportError as exc:
        raise ParameterError("reading DBC files needs cantools: uv sync --extra can") from exc
    try:
        db = cantools.database.load_file(str(path), strict=False)
    except Exception as exc:  # cantools raises various parse errors
        raise ParameterError(f"cannot read DBC file {path}: {exc}") from exc
    messages = {}
    for m in getattr(db, "messages", []):
        if m.length > 8:
            continue  # CAN FD frames: not supported yet
        sigs = tuple(
            CanSignal(
                s.name,
                s.start,
                s.length,
                s.byte_order == "little_endian",
                s.is_signed,
                float(s.scale),
                float(s.offset),
                s.minimum,
                s.maximum,
                s.unit or "",
                (s.comment or "") if isinstance(s.comment, str) else "",
            )
            for s in m.signals
            if s.multiplexer_ids is None
        )
        cycle = m.cycle_time / 1000.0 if getattr(m, "cycle_time", None) else None
        messages[m.name] = CanMessage(
            m.name, m.frame_id, m.length, sigs, m.comment or "", (m.senders or [""])[0], cycle
        )
    return messages


def _word(data: Array, little_endian: bool) -> int:
    b = bytes(int(v) & 0xFF for v in np.asarray(data, dtype=float)[:8]) + bytes(8 - min(8, len(data)))
    return int.from_bytes(b, "little" if little_endian else "big")


def unpack(sig: CanSignal, data: Array) -> float:
    """Physical value of ``sig`` from 8 data bytes."""
    raw = (_word(data, sig.little_endian) >> sig.shift) & sig.mask
    if sig.signed and raw & (1 << (sig.length - 1)):
        raw -= 1 << sig.length
    return raw * sig.factor + sig.offset


def raw_value(sig: CanSignal, value: float) -> int:
    """The raw integer for a physical value: rounded (half away from zero) and saturated to the bit field."""
    x = (float(value) - sig.offset) / sig.factor
    r = float(np.trunc(x))
    if abs(x - r) >= 0.5:
        r += 1.0 if x > 0 else -1.0
    lo, hi = (-(1 << (sig.length - 1)), (1 << (sig.length - 1)) - 1) if sig.signed else (0, (1 << sig.length) - 1)
    return int(min(max(r, lo), hi))


def pack(message: CanMessage, values: dict[str, float]) -> Array:
    """8 data bytes (as floats 0..255) with the given physical signal values (missing signals are 0)."""
    le, be = 0, 0
    for sig in message.signals:
        raw = raw_value(sig, values.get(sig.name, 0.0)) & sig.mask
        if sig.little_endian:
            le |= raw << sig.shift
        else:
            be |= raw << sig.shift
    data = np.frombuffer(le.to_bytes(8, "little"), dtype=np.uint8).astype(float)
    data += np.frombuffer(be.to_bytes(8, "big"), dtype=np.uint8).astype(float)  # disjoint bit fields
    return data
