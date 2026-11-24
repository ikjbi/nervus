"""CAN messages: read DBC files and pack/unpack signals bit-exactly.

DBC files describe which bits of a CAN frame carry which signal, and how the raw integer maps to a physical
value (``physical = raw · factor + offset``). Parsing uses ``cantools`` (``uv sync --extra can``); packing
and unpacking are implemented here with the same integer arithmetic the generated C code uses, so the
simulation and the ECU code agree bit for bit.

Bit layout: bit *k* of byte *b* has the DBC bit number ``8·b + k``. For **Intel** (little-endian, ``@1``)
signals the start bit is the signal's LSB and the following bits count upwards, into the next byte. For
**Motorola** (big-endian, ``@0``) the start bit is the signal's MSB and the following bits count down, from
bit 0 of a byte to bit 7 of the next one (the DBC's "sawtooth" numbering). Frames may have up to 64 data
bytes (CAN FD).

**Multiplexed** messages carry different signals depending on the value of a multiplexer signal: a signal
with ``mux_ids`` is only present when the multiplexer has one of those values.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from nervus.core.errors import MissingDependencyError, ParameterError, install_hint
from nervus.core.types import Array

FD_LENGTHS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64)


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
    mux_ids: tuple[int, ...] | None = None
    """Multiplexed signal: present only when the message's multiplexer has one of these values."""
    is_multiplexer: bool = False
    choices: tuple[tuple[int, str], ...] = ()
    """Value table (``VAL_``): raw value → name, e.g. ((0, "Park"), (1, "Reverse"))."""
    initial: float = 0.0
    """Physical initial value (``GenSigStartValue``, else raw 0), sent when the model provides no value."""

    @property
    def mask(self) -> int:
        return (1 << self.length) - 1

    def bits(self) -> list[int]:
        """DBC bit numbers (8·byte + bit) of the signal, from its LSB to its MSB."""
        if self.little_endian:
            return [self.start + k for k in range(self.length)]
        out, pos = [], self.start  # Motorola: from the MSB down
        for _ in range(self.length):
            out.append(pos)
            pos = pos + 15 if pos % 8 == 0 else pos - 1
        return out[::-1]

    def segments(self) -> list[tuple[int, int, int, int]]:
        """The signal as runs of bits inside single bytes: (byte, first bit in the byte, number of bits, position
        of the run in the raw value). Generated C code uses the same runs."""
        segs: list[list[int]] = []
        for k, b in enumerate(self.bits()):
            if segs and b // 8 == segs[-1][0] and b % 8 == segs[-1][1] + segs[-1][2]:
                segs[-1][2] += 1
            else:
                segs.append([b // 8, b % 8, 1, k])
        return [(a, b, c, d) for a, b, c, d in segs]

    def label(self, raw: int) -> str:
        """The value-table name of a raw value, or ''."""
        return dict(self.choices).get(raw, "")


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
    is_fd: bool = False
    """A CAN FD frame (up to 64 data bytes, faster data phase)."""
    is_extended: bool = False

    def signal(self, name: str) -> CanSignal:
        for s in self.signals:
            if s.name == name:
                return s
        raise KeyError(f"message {self.name} has no signal {name}")

    @property
    def multiplexer(self) -> CanSignal | None:
        return next((s for s in self.signals if s.is_multiplexer), None)


def load_dbc(path: str | Path) -> dict[str, CanMessage]:
    """Messages of a DBC file, by name (also CAN FD frames and multiplexed signals)."""
    try:
        import cantools
    except ImportError as exc:
        raise MissingDependencyError(f"reading DBC files needs cantools: {install_hint('can')}") from exc
    try:
        db = cantools.database.load_file(str(path), strict=False)
    except Exception as exc:  # cantools raises various parse errors
        raise ParameterError(f"cannot read DBC file {path}: {exc}") from exc
    messages = {}
    for m in getattr(db, "messages", []):
        sigs = tuple(_signal(s) for s in m.signals)
        cycle = m.cycle_time / 1000.0 if getattr(m, "cycle_time", None) else None
        messages[m.name] = CanMessage(
            m.name, m.frame_id, m.length, sigs, m.comment or "", (m.senders or [""])[0], cycle,
            bool(getattr(m, "is_fd", False)), bool(m.is_extended_frame),
        )  # fmt: skip
    return messages


def _signal(s: object) -> CanSignal:
    choices = tuple((int(k), str(v)) for k, v in (getattr(s, "choices", None) or {}).items())
    initial = getattr(s, "raw_initial", None)
    scale, offset = float(s.scale), float(s.offset)  # type: ignore[attr-defined]
    comment = getattr(s, "comment", "")
    return CanSignal(
        s.name,  # type: ignore[attr-defined]
        s.start,  # type: ignore[attr-defined]
        s.length,  # type: ignore[attr-defined]
        s.byte_order == "little_endian",  # type: ignore[attr-defined]
        s.is_signed,  # type: ignore[attr-defined]
        scale,
        offset,
        s.minimum,  # type: ignore[attr-defined]
        s.maximum,  # type: ignore[attr-defined]
        s.unit or "",  # type: ignore[attr-defined]
        comment if isinstance(comment, str) else "",
        tuple(int(x) for x in s.multiplexer_ids) if s.multiplexer_ids else None,  # type: ignore[attr-defined]
        bool(s.is_multiplexer),  # type: ignore[attr-defined]
        choices,
        float(initial or 0) * scale + offset,  # GenSigStartValue, else raw 0
    )


def _raw(sig: CanSignal, data: Array) -> int:
    d = np.asarray(data, dtype=float)
    raw = 0
    for byte, bit, n, pos in sig.segments():
        if byte < d.size:
            raw |= ((int(d[byte]) & 0xFF) >> bit & ((1 << n) - 1)) << pos
    return raw


def unpack(sig: CanSignal, data: Array) -> float:
    """Physical value of ``sig`` from the frame's data bytes."""
    raw = _raw(sig, data)
    if sig.signed and raw & (1 << (sig.length - 1)):
        raw -= 1 << sig.length
    return raw * sig.factor + sig.offset


def unpack_raw(sig: CanSignal, data: Array) -> int:
    """The raw (unsigned bit field) value of ``sig``, e.g. for its value table."""
    return _raw(sig, data)


def raw_value(sig: CanSignal, value: float) -> int:
    """The raw integer for a physical value: rounded (half away from zero) and saturated to the bit field."""
    x = (float(value) - sig.offset) / sig.factor
    r = float(np.trunc(x))
    if abs(x - r) >= 0.5:
        r += 1.0 if x > 0 else -1.0
    lo, hi = (-(1 << (sig.length - 1)), (1 << (sig.length - 1)) - 1) if sig.signed else (0, (1 << sig.length) - 1)
    return int(min(max(r, lo), hi))


def present(sig: CanSignal, mux_value: int | None) -> bool:
    """Whether a signal is in the frame for this multiplexer value (always for plain signals)."""
    return sig.mux_ids is None or (mux_value is not None and mux_value in sig.mux_ids)


def pack(message: CanMessage, values: dict[str, float]) -> Array:
    """The frame's data bytes (as floats 0..255) with the given physical signal values (missing signals: their
    initial value). Multiplexed signals are only written when the multiplexer value selects them."""
    data = [0] * message.length
    mux = message.multiplexer
    mux_value = raw_value(mux, values.get(mux.name, mux.initial)) & mux.mask if mux is not None else None
    for sig in message.signals:
        if not present(sig, mux_value):
            continue
        raw = raw_value(sig, values.get(sig.name, sig.initial)) & sig.mask
        for byte, bit, n, pos in sig.segments():
            data[byte] |= ((raw >> pos) & ((1 << n) - 1)) << bit
    return np.array(data, dtype=float)


def _identifier(text: str) -> str:
    import re

    out = re.sub(r"\W+", "_", text.strip()).strip("_")
    return out if out and not out[0].isdigit() else f"_{out}"


def dbc_variables(path: str | Path, signals: bool = True, value_tables: bool = True) -> list[Any]:
    """Workspace variables from a DBC file:

    - **value tables** (``VAL_``) as named constants ``<Signal>_<Name>``, e.g. ``GearSelector_Drive = 3``, so
      a model compares ``GearSelector == GearSelector_Drive`` instead of a magic number;
    - **signals** as variables ``<Signal>`` holding the initial value, with the unit, range and comment
      (a data dictionary of the bus).

    All are constants (not calibratable). Use them with :meth:`Workspace.add`, or in the app with Model
    Workspace ▸ Import DBC.
    """
    from nervus.core.workspace import Variable

    out: dict[str, Variable] = {}
    for m in load_dbc(path).values():
        for s in m.signals:
            if signals and s.name not in out:
                desc = f"{m.name} signal (0x{m.frame_id:X})" + (f": {s.comment}" if s.comment else "")
                lo, hi = s.minimum, s.maximum
                out[s.name] = Variable(_identifier(s.name), s.initial, desc, s.unit,
                                       None if lo is None else float(lo), None if hi is None else float(hi),
                                       calibratable=False)  # fmt: skip
            if value_tables:
                for raw, label in s.choices:
                    name = _identifier(f"{s.name}_{label}")
                    if name not in out:
                        out[name] = Variable(name, raw * s.factor + s.offset, f"{m.name}.{s.name} = {label}", s.unit,
                                             calibratable=False)  # fmt: skip
    return list(out.values())
