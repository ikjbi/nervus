"""A simulated CAN bus: arbitration, bit timing, bus load, fault injection and a frame trace.

Every CAN frame starts with its identifier. When several ECUs want to send, they all start together and the
frame with the **lowest identifier wins the arbitration** (a dominant 0 bit overwrites a recessive 1); the
others wait until the bus is idle again. A frame's duration follows from its bits: an 11-bit frame with *n*
data bytes has 44 + 8n bits from the start bit to the end of frame, plus the **stuff bits** the sender inserts
after five equal bits, plus 3 bits of inter-frame space. At 500 kbit/s an 8-byte frame takes about 0.25 ms.

:class:`CanBus` is the bus as a discrete-event model. The CAN Transmit blocks queue frames; the bus decides when
each one is on the wire (arbitration, transmission time) and the CAN Receive blocks read the frames that have
been delivered by their sample time. The bus keeps a **trace** of every frame (for the trace view, and for
export to ASC or BLF log files) and its **load**.

A bus can also be backed by real hardware through ``python-can`` (``hardware=``): transmitted frames are sent
on the interface and received frames come from it.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REGISTRY: dict[str, CanBus] = {}


def bus(name: str = "can0") -> CanBus:
    """The simulated bus called ``name`` (created on first use)."""
    if name not in _REGISTRY:
        _REGISTRY[name] = CanBus(name)
    return _REGISTRY[name]


def crc15(bits: list[int]) -> int:
    """The CAN CRC-15 (polynomial 0x4599) of a bit sequence."""
    crc = 0
    for b in bits:
        nxt = b ^ ((crc >> 14) & 1)
        crc = (crc << 1) & 0x7FFF
        if nxt:
            crc ^= 0x4599
    return crc


def frame_bits(can_id: int, data: bytes) -> int:
    """Number of bits of a standard (11-bit) data frame on the wire, including stuff bits and the 3-bit
    inter-frame space."""
    head = [0]  # SOF
    head += [(can_id >> (10 - k)) & 1 for k in range(11)]
    head += [0, 0, 0]  # RTR, IDE, r0
    n = len(data)
    head += [(n >> (3 - k)) & 1 for k in range(4)]
    for byte in data:
        head += [(byte >> (7 - k)) & 1 for k in range(8)]
    crc = crc15(head)
    stuffed = head + [(crc >> (14 - k)) & 1 for k in range(15)]
    stuff, run, last = 0, 0, -1
    for b in stuffed:
        if b == last:
            run += 1
        else:
            run, last = 1, b
        if run == 5:  # a stuff bit of the opposite value, which also starts a new run
            stuff += 1
            run, last = 1, 1 - b
    return len(stuffed) + stuff + 1 + 2 + 7 + 3  # CRC delimiter, ACK slot + delimiter, EOF, IFS


@dataclass(order=True)
class _Pending:
    queued: float
    can_id: int
    seq: int
    data: bytes = field(compare=False)
    sender: str = field(compare=False, default="")
    sent: float = field(compare=False, default=0.0)


@dataclass
class Frame:
    """A frame on the bus: when the sender queued it, when it went on the wire and when it was received."""

    can_id: int
    data: bytes
    queued: float
    start: float
    end: float
    sender: str = ""
    lost: bool = False


@dataclass
class CanBus:
    name: str
    bitrate: float = 500_000.0
    trace: list[Frame] = field(default_factory=list)
    hardware: Any = None
    """A ``python-can`` bus: frames are also sent to it, and frames from it are delivered."""
    _queue: list[_Pending] = field(default_factory=list)
    _seq: int = 0
    _busy_until: float = 0.0
    _last_t: float = -1.0
    _delivered: dict[int, list[Frame]] = field(default_factory=dict)
    _faults: dict[int, dict[str, Any]] = field(default_factory=dict)

    # ------------------------------------------------------------------ lifecycle

    def reset(self) -> None:
        self.trace.clear()
        self._queue.clear()
        self._delivered.clear()
        self._faults.clear()
        self._busy_until = 0.0
        self._last_t = -1.0
        self._seq = 0

    def _touch(self, t: float) -> None:
        if t < self._last_t - 1e-9:  # a new simulation started: forget the old one
            self.reset()
        self._last_t = max(self._last_t, t)

    def set_fault(self, can_id: int, **fault: Any) -> None:
        """Inject a fault for one identifier: ``drop`` (probability 0..1 of losing a frame), ``delay`` (extra
        seconds before the frame is queued), ``off`` (True: the sender is bus-off and sends nothing), ``corrupt``
        (probability 0..1 that a data bit is flipped: a fault that the CAN CRC does not catch, e.g. in a
        gateway's memory or the sender's software, but an E2E check does)."""
        self._faults.setdefault(can_id, {}).update(fault)

    # ------------------------------------------------------------------ sending and receiving

    def send(self, t: float, can_id: int, data: bytes, sender: str = "") -> None:
        """Queue a frame at time ``t`` (from a CAN Transmit block)."""
        self._touch(t)
        f = self._faults.get(can_id, {})
        if f.get("off"):
            return
        self._seq += 1
        heapq.heappush(self._queue, _Pending(t + float(f.get("delay", 0.0)), can_id, self._seq, bytes(data), sender, t))
        if self.hardware is not None:
            import can

            self.hardware.send(can.Message(arbitration_id=can_id, data=bytes(data), is_extended_id=False))

    def _run(self, t: float) -> None:
        """Put frames on the wire until time ``t``: when the bus is idle, the lowest identifier among the
        frames waiting wins."""
        while self._queue:
            first = min(self._queue, key=lambda p: p.queued).queued
            start = max(self._busy_until, first)
            if start >= t:  # decided later: another block may still queue a frame for this instant
                return
            ready = [p for p in self._queue if p.queued <= start]
            win = min(ready, key=lambda p: (p.can_id, p.seq))
            self._queue.remove(win)
            heapq.heapify(self._queue)
            duration = frame_bits(win.can_id, win.data) / self.bitrate
            f = self._faults.get(win.can_id, {})
            lost = bool(f.get("drop")) and _random(self.name, win.seq) < float(f["drop"])
            data = win.data
            if f.get("corrupt") and data and _random(self.name + "c", win.seq) < float(f["corrupt"]):
                bit = int(_random(self.name + "b", win.seq) * 8 * len(data))
                flipped = bytearray(data)
                flipped[bit // 8] ^= 1 << (bit % 8)
                data = bytes(flipped)
            frame = Frame(win.can_id, data, win.sent, start, start + duration, win.sender, lost)
            self.trace.append(frame)
            if not lost:
                self._deliver(frame)
            self._busy_until = start + duration

    def _deliver(self, frame: Frame) -> None:
        self._delivered.setdefault(frame.can_id, []).append(frame)

    def receive(self, t: float, can_id: int) -> Frame | None:
        """The latest frame with ``can_id`` completely received by time ``t``."""
        self._touch(t)
        self._run(t)
        if self.hardware is not None:
            self._poll_hardware(t)
        for f in reversed(self._delivered.get(can_id, [])):
            if f.end <= t + 1e-12:
                return f
        return None

    def delivered_between(self, t0: float, t1: float) -> list[Frame]:
        """Frames completely received in (t0, t1], in order (for gateways)."""
        self._touch(t1)
        self._run(t1)
        if self.hardware is not None:
            self._poll_hardware(t1)
        return sorted((f for f in self.trace if not f.lost and t0 < f.end <= t1 + 1e-12), key=lambda f: f.end)

    def connect_hardware(self, interface: str, channel: str, bitrate: float | None = None) -> None:
        """Back the bus with a real CAN interface through python-can (``socketcan``, ``pcan``, ``kvaser``,
        ``vector``, ``virtual``, ...)."""
        try:
            import can
        except ImportError as exc:
            raise RuntimeError("real CAN hardware needs python-can: uv sync --extra can") from exc
        self.disconnect_hardware()
        kwargs: dict[str, Any] = {"interface": interface, "channel": channel}
        if bitrate and interface not in ("virtual", "socketcan"):
            kwargs["bitrate"] = int(bitrate)
        self.hardware = can.Bus(**kwargs)

    def disconnect_hardware(self) -> None:
        if self.hardware is not None:
            self.hardware.shutdown()
            self.hardware = None

    def _poll_hardware(self, t: float) -> None:
        while True:
            msg = self.hardware.recv(timeout=0.0)
            if msg is None:
                return
            frame = Frame(msg.arbitration_id, bytes(msg.data), t, t, t, "hardware")
            self.trace.append(frame)
            self._deliver(frame)

    # ------------------------------------------------------------------ statistics and logs

    def load(self, t0: float, t1: float) -> float:
        """Share of the time between ``t0`` and ``t1`` the bus was busy (0..1)."""
        if t1 <= t0:
            return 0.0
        busy = sum(max(0.0, min(f.end, t1) - max(f.start, t0)) for f in self.trace if f.sender != "hardware")
        return busy / (t1 - t0)

    def latency(self, can_id: int) -> list[float]:
        """For each frame of ``can_id``: the time from being queued until it was received."""
        return [f.end - f.queued for f in self.trace if f.can_id == can_id and not f.lost]

    def write_asc(self, path: str | Path, channel: int = 1) -> Path:
        """The trace as a Vector ASC log (readable by CANalyzer, CANoe, python-can, SavvyCAN, ...)."""
        lines = ["date Thu Jan 1 00:00:00.000 am 1970", "base hex  timestamps absolute", "no internal events logged"]
        for f in self.trace:
            if f.lost:
                continue
            data = " ".join(f"{b:02X}" for b in f.data)
            lines.append(f"{f.end:12.6f} {channel}  {f.can_id:X}             Rx   d {len(f.data)} {data}")
        p = Path(path)
        p.write_text("\n".join(lines) + "\n", encoding="ascii")
        return p

    def write_blf(self, path: str | Path, channel: int = 0) -> Path:
        """The trace as a Vector BLF binary log (needs python-can)."""
        import can

        with can.BLFWriter(str(path)) as writer:
            for f in self.trace:
                if not f.lost:
                    writer.on_message_received(
                        can.Message(
                            timestamp=f.end, arbitration_id=f.can_id, data=f.data, is_extended_id=False, channel=channel
                        )
                    )
        return Path(path)


def _random(name: str, k: int) -> float:
    """A reproducible uniform number for frame ``k`` of a bus (for injected frame loss)."""
    import numpy as np

    return float(np.random.default_rng([sum(map(ord, name)), k]).random())


def crc8_j1850(data: bytes, crc: int = 0xFF) -> int:
    """CRC-8 SAE J1850 (polynomial 0x1D), the CRC of AUTOSAR E2E profile 1, before the final XOR."""
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1D) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def e2e_crc(data: bytes, data_id: int, crc_byte: int = 0) -> int:
    """The E2E CRC of a frame: over the 16-bit data ID (low byte first) and every byte except the CRC byte."""
    body = bytes([data_id & 0xFF, (data_id >> 8) & 0xFF]) + bytes(b for k, b in enumerate(data) if k != crc_byte)
    return crc8_j1850(body) ^ 0xFF
