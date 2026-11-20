"""CAN Pack and CAN Unpack: convert between CAN frame bytes and physical signal values using a DBC file."""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from nervus.blocks.registry import register
from nervus.can import CanMessage, load_dbc, pack, unpack
from nervus.core.block import Block, Width
from nervus.core.errors import ParameterError
from nervus.core.params import Param, ParamKind
from nervus.core.sample_time import SampleTime
from nervus.core.types import Array

CATEGORY = "CAN"


@lru_cache(maxsize=32)
def _cached_dbc(path: str, mtime: float) -> dict[str, CanMessage]:
    return load_dbc(path)


class _CanBlock(Block):
    category = CATEGORY
    PARAMS: ClassVar[tuple[Param, ...]] = (
        Param("dbc_file", "", ParamKind.STR, "DBC file (relative paths are relative to the model file)"),
        Param("message", "", ParamKind.STR, "Message name in the DBC file"),
        Param("signals", "", ParamKind.STR, "Signals to use, comma separated (empty = all, in DBC order)"),
    )

    def _path(self) -> Path:
        p = Path(self.params["dbc_file"])
        root = self.diagram.root if self.diagram is not None else None
        source = getattr(root, "source_path", None)
        if not p.is_absolute() and source is not None:
            candidate = Path(source).parent / p
            if candidate.exists():
                return candidate
        return p

    def message(self) -> CanMessage:
        if not self.params["dbc_file"]:
            raise ParameterError("choose a DBC file")
        path = self._path()
        if not path.exists():
            raise ParameterError(f"DBC file not found: {path}")
        messages = _cached_dbc(str(path.resolve()), path.stat().st_mtime)
        name = self.params["message"]
        if name not in messages:
            raise ParameterError(f"message {name!r} not in {path.name}; messages: {', '.join(messages)}")
        return messages[name]

    def selected(self) -> list[Any]:
        try:
            msg = self.message()
        except ParameterError:
            return []
        wanted = [s.strip() for s in self.params["signals"].split(",") if s.strip()]
        if not wanted:
            return list(msg.signals)
        missing = [w for w in wanted if w not in {s.name for s in msg.signals}]
        if missing:
            raise ParameterError(f"signals not in {msg.name}: {', '.join(missing)}")
        return [msg.signal(w) for w in wanted]

    def suggestions(self, param: str) -> list[str]:
        if param == "message" and self.params["dbc_file"]:
            path = self._path()
            if path.exists():
                try:
                    return list(_cached_dbc(str(path.resolve()), path.stat().st_mtime))
                except ParameterError:
                    return []
        if param == "signals":
            try:
                return [", ".join(s.name for s in self.message().signals)]
            except ParameterError:
                return []
        return []

    def validate_params(self) -> None:
        if self.params["dbc_file"] and self.params["message"] and self.diagram is not None:
            self.selected()

    def configure(self, in_widths: list[int], out_widths: list[int]) -> None:
        super().configure(in_widths, out_widths)
        try:
            self._msg = self.message()
            self._signals = self.selected()
        except ParameterError as exc:
            raise ValueError(str(exc)) from exc


@register
class CanUnpack(_CanBlock):
    """Decodes a CAN frame: the input is the 8 data bytes (a vector of width 8), and there is one output per
    signal, in physical units (``raw · factor + offset`` from the DBC file).

    ![Decoding a CAN frame](figures/can_frame.png)

    Intel (little-endian) and Motorola (big-endian) byte order, signed and unsigned signals are supported. The
    block can be generated as C code.
    """

    type_id = "can.unpack"
    label = "CAN Unpack"
    TYPE_RULE = "double"

    def num_outputs(self) -> int:
        return max(1, len(self.selected()))

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [1] * self.num_outputs()

    def configure(self, in_widths: list[int], out_widths: list[int]) -> None:
        super().configure(in_widths, out_widths)
        if in_widths[0] != 8:
            raise ValueError("the input must be the 8 data bytes of the frame (width 8)")

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [np.array([unpack(s, u[0])]) for s in self._signals]


@register
class CanPack(_CanBlock):
    """Encodes a CAN frame: one input per signal (physical units), output = the 8 data bytes (``uint8``).

    Values are converted to the raw integer with rounding to nearest and saturated to the bit field, exactly
    as the generated C code does. Signals that are not selected are sent as 0.
    """

    type_id = "can.pack"
    label = "CAN Pack"

    def num_inputs(self) -> int:
        return max(1, len(self.selected()))

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [8]

    def output_types(self, in_types: list[Any]) -> list[Any]:
        from nervus.core.datatypes import parse_datatype

        return [parse_datatype("uint8")]

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        values = {s.name: float(v[0]) for s, v in zip(self._signals, u, strict=True)}
        return [pack(self._msg, values)]


_BUS = Param("bus", "can0", ParamKind.STR, "Name of the simulated CAN bus")
_PAYLOAD = Param("payload", "signals", ParamKind.CHOICE, "Signals (packed with the DBC) or the raw 8 data bytes",
                 choices=("signals", "bytes"))  # fmt: skip
_ST = Param("sample_time", 0.01, ParamKind.SAMPLE_TIME, "Task period of the block", "s")


@register
class CanTransmit(_CanBlock):
    """Sends a CAN message on a simulated bus: one input per signal (physical units), packed with the DBC file
    (with *payload* ``bytes``: one input with the 8 data bytes, e.g. from CAN Pack and E2E Protect).

    *mode* ``periodic`` sends at every sample: *sample_time* 0 takes the message's cycle time from the DBC file
    (``GenMsgCycleTime``; 10 ms if it has none);
    ``on_change`` sends only when the packed bytes change (event-triggered); ``on_trigger`` adds an input that
    sends on its rising edge. The frame competes for the bus with the other senders: the lowest identifier wins
    the arbitration, and it arrives after its transmission time (see the CAN Bus block).

    Fault injection for tests: *drop* (probability of losing a frame), *delay* (extra queueing delay),
    *corrupt* (probability of a flipped data bit, which an E2E check detects) and *bus_off* (from *fault_time*
    this node sends nothing).
    """

    type_id = "can.transmit"
    label = "CAN Transmit"
    NUM_OUTPUTS = 0
    PARAMS = (
        *_CanBlock.PARAMS,
        _BUS,
        _PAYLOAD,
        Param("mode", "periodic", ParamKind.CHOICE, "When to send", choices=("periodic", "on_change", "on_trigger")),
        Param("node", "", ParamKind.STR, "Sending ECU (for the trace)"),
        Param("drop", 0.0, ParamKind.FLOAT, "Probability of losing a frame (fault injection)", min=0.0, max=1.0),
        Param("delay", 0.0, ParamKind.FLOAT, "Extra delay before the frame is queued (fault injection)", "s", min=0.0),
        Param("corrupt", 0.0, ParamKind.FLOAT, "Probability of a flipped data bit (fault injection)", min=0.0, max=1.0),
        Param(
            "bus_off",
            0.0,
            ParamKind.FLOAT,
            "1: the node goes bus-off at fault_time (fault injection)",
            min=0.0,
            max=1.0,
        ),
        Param("fault_time", 0.0, ParamKind.FLOAT, "When the faults start", "s"),
        Param("sample_time", 0.0, ParamKind.SAMPLE_TIME, "Send period; 0 = the message's cycle time in the DBC", "s"),
    )

    def sample_time(self) -> SampleTime:
        if float(self.params["sample_time"]) == 0.0:
            try:
                cycle = self.message().cycle_time
            except ParameterError:
                cycle = None
            return SampleTime.from_value(cycle or 0.01)
        return super().sample_time()

    def configure(self, in_widths: list[int], out_widths: list[int]) -> None:
        from nervus.canbus import bus

        super().configure(in_widths, out_widths)
        bus(str(self.params["bus"])).reset()  # a new simulation starts

    def _raw(self) -> bool:
        return self.params["payload"] == "bytes"

    def num_inputs(self) -> int:
        n = 1 if self._raw() else max(1, len(self.selected()))
        return n + (1 if self.params["mode"] == "on_trigger" else 0)

    def input_names(self) -> list[str]:
        names = ["bytes"] if self._raw() else [s.name for s in self.selected()] or ["signal"]
        return names + (["trigger"] if self.params["mode"] == "on_trigger" else [])

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return []

    def initial_discrete_state(self) -> Array:
        return np.full(10, -1.0)  # last sent bytes (8), last trigger value, last send time

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return []

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        from nervus.canbus import bus

        p = self.params
        if self._raw():
            n = 1
            data = np.zeros(8)
            raw = np.ravel(u[0])[:8]
            data[: raw.size] = raw
        else:
            n = len(self._signals)
            values = {s.name: float(np.ravel(v)[0]) for s, v in zip(self._signals, u[:n], strict=True)}
            data = pack(self._msg, values)
        trig = float(np.ravel(u[n])[0]) if p["mode"] == "on_trigger" else 0.0
        mode = p["mode"]
        send = (
            mode == "periodic"
            or (mode == "on_change" and not np.array_equal(data, xd[:8]))
            or (mode == "on_trigger" and trig >= 0.5 > xd[8])
        )
        b = bus(str(p["bus"]))
        if t >= p["fault_time"]:
            b.set_fault(
                self._msg.frame_id, drop=p["drop"], delay=p["delay"], off=p["bus_off"] >= 0.5, corrupt=p["corrupt"]
            )
        else:
            b.set_fault(self._msg.frame_id, drop=0.0, delay=0.0, off=False, corrupt=0.0)
        if send:
            b.send(t, self._msg.frame_id, bytes(int(x) for x in data[: self._msg.length]), str(p["node"]))
        return np.array([*data, trig, t if send else xd[9]])


@register
class CanReceive(_CanBlock):
    """Receives a CAN message from a simulated bus: one output per signal (physical units, the last frame
    received; with *payload* ``bytes`` one output with the 8 data bytes, e.g. for an E2E Check), then **new** (1 for the sample in which a new frame arrived) and **age** (seconds since the last
    frame; use it for a timeout monitor, e.g. with a Diagnostic Monitor for U-codes). Until the first frame the
    signals are 0 and the age counts from the start.
    """

    type_id = "can.receive"
    label = "CAN Receive"
    TYPE_RULE = "double"
    DIRECT_FEEDTHROUGH = False
    NUM_INPUTS = 0
    PARAMS = (*_CanBlock.PARAMS, _BUS, _PAYLOAD, _ST)

    def _raw(self) -> bool:
        return self.params["payload"] == "bytes"

    def configure(self, in_widths: list[int], out_widths: list[int]) -> None:
        from nervus.canbus import bus

        super().configure(in_widths, out_widths)
        bus(str(self.params["bus"])).reset()  # a new simulation starts

    def num_outputs(self) -> int:
        return (1 if self._raw() else max(1, len(self.selected()))) + 2

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        widths: list[Width] = [8] if self._raw() else [1] * (self.num_outputs() - 2)
        return [*widths, 1, 1]

    def initial_discrete_state(self) -> Array:
        n = 8 if self._raw() else max(1, len(self.selected()))
        return np.array([*np.zeros(n), 0.0, -1.0, 0.0])  # values, new flag, end time of the last frame, age

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        n = len(xd) - 3
        values = [xd[:n].copy()] if self._raw() else [np.array([v]) for v in xd[:n]]
        return [*values, np.array([xd[n]]), np.array([xd[n + 2]])]

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        from nervus.canbus import bus

        n = len(xd) - 3
        frame = bus(str(self.params["bus"])).receive(t, self._msg.frame_id)
        values, new, last = xd[:n].copy(), 0.0, xd[n + 1]
        if frame is not None and frame.end > xd[n + 1]:
            data = np.frombuffer(frame.data.ljust(8, b"\0"), dtype=np.uint8).astype(float)
            if self._raw():
                values = data
            elif self._signals:
                values = np.array([unpack(s, data) for s in self._signals])
            new, last = 1.0, frame.end
        age = t - last if last >= 0 else t - self.t_start
        return np.array([*values, new, last, age])


@register
class CanBusSetup(Block):
    """Settings of a simulated CAN bus, and its load: *bitrate* (125, 250, 500 kbit/s or 1 Mbit/s), and the
    output is the bus load (0..1) over the last *sample_time*. A CAN bus should stay below about 50-70 % load,
    so the lowest-priority messages still get through in time.

    With *interface* set (``socketcan``, ``pcan``, ``kvaser``, ``vector``, ...; needs python-can and the
    driver), the bus is connected to **real hardware**: every frame the model transmits is also sent on the
    interface, and frames from the interface reach the CAN Receive blocks. Run the simulation in real time
    (Simulation ▸ Real-time pacing) for HIL-style tests against a real ECU."""

    type_id = "can.bus"
    label = "CAN Bus"
    category = CATEGORY
    NUM_INPUTS = 0
    DIRECT_FEEDTHROUGH = False
    PARAMS = (
        _BUS,
        Param("bitrate", 500_000.0, ParamKind.FLOAT, "Bit rate", "bit/s", min=1.0),
        Param("interface", "none", ParamKind.CHOICE, "Real CAN interface (python-can); none = simulated only",
              choices=("none", "socketcan", "pcan", "kvaser", "vector", "slcan", "virtual")),
        Param("channel", "", ParamKind.STR, "Interface channel, e.g. can0, PCAN_USBBUS1, 0"),
        Param("sample_time", 0.1, ParamKind.SAMPLE_TIME, "Window for the bus load", "s"),
    )  # fmt: skip

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [1]

    def configure(self, in_widths: list[int], out_widths: list[int]) -> None:
        from nervus.canbus import bus

        super().configure(in_widths, out_widths)
        b = bus(str(self.params["bus"]))
        b.reset()
        b.bitrate = float(self.params["bitrate"])
        if self.params["interface"] != "none":
            try:
                b.connect_hardware(str(self.params["interface"]), str(self.params["channel"]), b.bitrate)
            except Exception as exc:  # python-can raises driver-specific errors
                raise ValueError(f"cannot open CAN interface {self.params['interface']}: {exc}") from exc
        else:
            b.disconnect_hardware()

    def initial_discrete_state(self) -> Array:
        return np.zeros(1)

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [xd.copy()]

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        from nervus.canbus import bus

        b = bus(str(self.params["bus"]))
        b.receive(t, -1)  # advance the bus to now
        return np.array([b.load(t - self.period(), t)])


_E2E = (
    Param("data_id", 0x100, ParamKind.INT, "E2E data ID (16 bit, agreed between sender and receiver)", min=0,
          max=0xFFFF),
    Param("crc_byte", 0, ParamKind.INT, "Byte that holds the CRC", min=0, max=7),
    Param("counter_byte", 1, ParamKind.INT, "Byte whose low 4 bits hold the alive counter", min=0, max=7),
)  # fmt: skip


def _bytes(u: Array) -> bytes:
    return bytes(int(v) & 0xFF for v in np.ravel(u)[:8])


@register
class E2EProtect(Block):
    """Protects a frame AUTOSAR E2E style (like profile 1): writes an **alive counter** (0..14, one step per
    sample) into the low 4 bits of *counter_byte* and a **CRC-8** (SAE J1850) over the *data_id* and the
    other bytes into *crc_byte*. Put it between CAN Pack and CAN Transmit (leave those two bytes free in the
    DBC). The receiver checks it with E2E Check, which detects corrupted, repeated, lost and out-of-order
    frames. Can be generated as C code."""

    type_id = "can.e2e_protect"
    label = "E2E Protect"
    category = CATEGORY
    PARAMS = (*_E2E, Param("sample_time", -1.0, ParamKind.SAMPLE_TIME, "-1 = inherited", "s"))

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [8]

    def output_types(self, in_types: list[Any]) -> list[Any]:
        from nervus.core.datatypes import parse_datatype

        return [parse_datatype("uint8")]

    def configure(self, in_widths: list[int], out_widths: list[int]) -> None:
        super().configure(in_widths, out_widths)
        if in_widths[0] != 8:
            raise ValueError("the input must be the 8 data bytes of the frame (width 8)")
        if self.params["crc_byte"] == self.params["counter_byte"]:
            raise ValueError("the CRC and the counter need different bytes")

    def initial_discrete_state(self) -> Array:
        return np.zeros(1)

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        from nervus.canbus import e2e_crc

        data = bytearray(_bytes(u[0]))
        cb, kb = int(self.params["counter_byte"]), int(self.params["crc_byte"])
        data[cb] = (data[cb] & 0xF0) | int(xd[0])
        data[kb] = e2e_crc(bytes(data), int(self.params["data_id"]), kb)
        return [np.array(list(data), dtype=float)]

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        return np.array([(xd[0] + 1) % 15])


E2E_STATUS = ("ok", "no_new_data", "wrong_crc", "repeated", "wrong_sequence")


@register
class E2ECheck(Block):
    """Checks a frame protected by E2E Protect. Inputs: the 8 data bytes and **new** (from CAN Receive).
    Outputs: the **status** and **valid** (1 = use the data).

    ===== =============== ==========================================================================
    0     ok              new frame, CRC right, counter one step on (up to *max_delta*: some lost)
    1     no_new_data     no frame since the last sample
    2     wrong_crc       the bytes are corrupted (or the sender uses another data ID)
    3     repeated        the same counter again: a stuck sender
    4     wrong_sequence  the counter jumped more than *max_delta*: too many frames lost
    ===== =============== ==========================================================================

    A receiver typically substitutes a safe value when *valid* is 0 for longer than a timeout, and sets a
    DTC. Can be generated as C code.
    """

    type_id = "can.e2e_check"
    label = "E2E Check"
    category = CATEGORY
    NUM_INPUTS = 2
    NUM_OUTPUTS = 2
    TYPE_RULE = "double"
    PARAMS = (
        *_E2E,
        Param("max_delta", 2, ParamKind.INT, "Largest counter step accepted (1 = no frame may be lost)", min=1,
              max=14),
        Param("sample_time", -1.0, ParamKind.SAMPLE_TIME, "-1 = inherited", "s"),
    )  # fmt: skip

    def input_names(self) -> list[str]:
        return ["data", "new"]

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [1, 1]

    def configure(self, in_widths: list[int], out_widths: list[int]) -> None:
        super().configure(in_widths, out_widths)
        if in_widths[0] != 8:
            raise ValueError("the data input must be the 8 data bytes of the frame (width 8)")

    def initial_discrete_state(self) -> Array:
        return np.array([-1.0])  # last accepted counter (-1: none yet)

    def _status(self, u: Sequence[Array], last: float) -> tuple[int, int]:
        from nervus.canbus import e2e_crc

        if float(np.ravel(u[1])[0]) < 0.5:
            return 1, -1
        data = _bytes(u[0])
        kb = int(self.params["crc_byte"])
        if data[kb] != e2e_crc(data, int(self.params["data_id"]), kb):
            return 2, -1
        counter = data[int(self.params["counter_byte"])] & 0x0F
        if last < 0:
            return 0, counter
        delta = (counter - int(last)) % 15
        if delta == 0:
            return 3, counter
        return (0 if delta <= int(self.params["max_delta"]) else 4), counter

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        status, _ = self._status(u, xd[0])
        return [np.array([float(status)]), np.array([1.0 if status == 0 else 0.0])]

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        status, counter = self._status(u, xd[0])
        return np.array([float(counter)]) if status in (0, 3, 4) else xd.copy()


def _ids(text: str) -> set[int]:
    return {int(x, 0) for x in str(text).replace(";", ",").split(",") if x.strip()}


@register
class CanRestBus(Block):
    """Rest-bus simulation: sends every message of the ECUs (*nodes*) that are not modelled, at their cycle
    times from the DBC file, so the ECU under test sees a complete bus. Signal values default to 0 (or to
    the DBC's initial value); set others with *values*, e.g. ``CoolantTemp=90, VehicleSpeed=50``.
    *nodes* empty = every sender in the DBC file."""

    type_id = "can.rest_bus"
    label = "CAN Rest Bus"
    category = CATEGORY
    NUM_INPUTS = 0
    NUM_OUTPUTS = 0
    PARAMS = (
        Param("dbc_file", "", ParamKind.STR, "DBC file"),
        Param("nodes", "", ParamKind.STR, "Sending ECUs to simulate, comma separated (empty = all)"),
        Param("values", "", ParamKind.STR, "Signal values, e.g. CoolantTemp=90, VehicleSpeed=50"),
        _BUS,
        Param("sample_time", 0.001, ParamKind.SAMPLE_TIME, "Scheduler tick (a divisor of the cycle times)", "s"),
    )

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return []

    def _path(self) -> Path:
        return _CanBlock._path(self)  # type: ignore[arg-type]

    def configure(self, in_widths: list[int], out_widths: list[int]) -> None:
        from nervus.canbus import bus

        super().configure(in_widths, out_widths)
        path = self._path()
        if not path.exists():
            raise ValueError(f"DBC file not found: {path}")
        messages = _cached_dbc(str(path.resolve()), path.stat().st_mtime)
        nodes = {n.strip() for n in str(self.params["nodes"]).split(",") if n.strip()}
        values = {}
        for item in str(self.params["values"]).split(","):
            if "=" in item:
                k, v = item.split("=", 1)
                values[k.strip()] = float(v)
        tick = self.period()
        self._schedule = []
        for m in messages.values():
            if nodes and m.sender not in nodes:
                continue
            cycle = m.cycle_time or 0.1
            every = max(1, round(cycle / tick))
            self._schedule.append((m.frame_id, every, bytes(int(x) for x in pack(m, values)[: m.length]), m.sender))
        if not self._schedule:
            raise ValueError(f"no messages sent by {', '.join(sorted(nodes))} in {path.name}")
        bus(str(self.params["bus"])).reset()

    def initial_discrete_state(self) -> Array:
        return np.zeros(1)  # tick counter

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return []

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        from nervus.canbus import bus

        b = bus(str(self.params["bus"]))
        k = int(xd[0])
        for frame_id, every, data, sender in self._schedule:
            if k % every == 0:
                b.send(t, frame_id, data, sender or "rest bus")
        return np.array([k + 1.0])


@register
class CanGateway(Block):
    """Forwards frames from one bus to another, like the central gateway between the powertrain and the body
    CAN. *ids*: the identifiers to route (e.g. ``0x100, 0x200``; empty = all). A frame is forwarded at the
    gateway's next task (*sample_time*), so routing adds up to one period of latency plus the transmission
    time on the second bus."""

    type_id = "can.gateway"
    label = "CAN Gateway"
    category = CATEGORY
    NUM_INPUTS = 0
    NUM_OUTPUTS = 0
    PARAMS = (
        Param("from_bus", "can0", ParamKind.STR, "Bus to read from"),
        Param("to_bus", "can1", ParamKind.STR, "Bus to send on"),
        Param("ids", "", ParamKind.STR, "Identifiers to route, comma separated (empty = all)"),
        Param("sample_time", 0.001, ParamKind.SAMPLE_TIME, "Gateway task period", "s"),
    )

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return []

    def validate_params(self) -> None:
        try:
            _ids(self.params["ids"])
        except ValueError as exc:
            raise ParameterError(f"ids: {exc}") from exc
        if self.params["from_bus"] == self.params["to_bus"]:
            raise ParameterError("the gateway needs two different buses")

    def configure(self, in_widths: list[int], out_widths: list[int]) -> None:
        from nervus.canbus import bus

        super().configure(in_widths, out_widths)
        self._routes = _ids(self.params["ids"])
        bus(str(self.params["from_bus"])).reset()
        bus(str(self.params["to_bus"])).reset()

    def initial_discrete_state(self) -> Array:
        return np.array([-1.0])  # time up to which frames were forwarded

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return []

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        from nervus.canbus import bus

        src, dst = bus(str(self.params["from_bus"])), bus(str(self.params["to_bus"]))
        for f in src.delivered_between(float(xd[0]), t):
            if (not self._routes or f.can_id in self._routes) and f.sender != f"gateway {dst.name}":
                dst.send(t, f.can_id, f.data, f"gateway {src.name}")
        return np.array([t])
