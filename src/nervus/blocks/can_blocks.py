"""CAN Pack and CAN Unpack: convert between CAN frame bytes and physical signal values using a DBC file."""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from nervus.blocks.registry import register
from nervus.can import CanMessage, load_dbc, pack, present, unpack, unpack_raw
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

    def _length(self) -> int:
        try:
            return self.message().length
        except ParameterError:
            return 8

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
    """Decodes a CAN frame: the input is the frame's data bytes (a vector: 8 for classic CAN, up to 64 for CAN
    FD), and there is one output per signal, in physical units (``raw · factor + offset`` from the DBC file).

    ![Decoding a CAN frame](figures/can_frame.png)

    Intel (little-endian) and Motorola (big-endian) byte order, signed and unsigned signals are supported.
    **Multiplexed** signals are only in the frame when the multiplexer selects them; their outputs hold the
    last value received. The block can be generated as C code.
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
        if in_widths[0] != self._msg.length:
            raise ValueError(f"the input must be the {self._msg.length} data bytes of {self._msg.name}")

    def _has_mux(self) -> bool:
        return any(s.mux_ids is not None for s in self.selected())

    def initial_discrete_state(self) -> Array:
        return np.zeros(len(self.selected())) if self._has_mux() else np.zeros(0)

    def _values(self, u: Array, xd: Array) -> list[float]:
        mux = self._msg.multiplexer
        mux_value = unpack_raw(mux, u) if mux is not None else None
        return [unpack(s, u) if present(s, mux_value) else float(xd[k]) for k, s in enumerate(self._signals)]

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [np.array([v]) for v in self._values(u[0], xd)]

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        return np.array(self._values(u[0], xd)) if xd.size else xd


@register
class CanPack(_CanBlock):
    """Encodes a CAN frame: one input per signal (physical units), output = the data bytes (``uint8``; 8 for
    classic CAN, up to 64 for CAN FD).

    Values are converted to the raw integer with rounding to nearest and saturated to the bit field, exactly
    as the generated C code does. Signals that are not selected are sent with their initial value from the
    DBC file (``GenSigStartValue``, else raw 0). Multiplexed signals are written only when the multiplexer value
    selects them.
    """

    type_id = "can.pack"
    label = "CAN Pack"

    def num_inputs(self) -> int:
        return max(1, len(self.selected()))

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        try:
            return [self.message().length]
        except ParameterError:
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
        try:
            n = self.message().length
        except ParameterError:
            n = 8
        return np.full(n + 2, -1.0)  # last sent bytes, last trigger value, last send time

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return []

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        from nervus.canbus import bus

        p = self.params
        if self._raw():
            n = 1
            data = np.zeros(self._msg.length)
            raw = np.ravel(u[0])[: self._msg.length]
            data[: raw.size] = raw
        else:
            n = len(self._signals)
            values = {s.name: float(np.ravel(v)[0]) for s, v in zip(self._signals, u[:n], strict=True)}
            data = pack(self._msg, values)
        trig = float(np.ravel(u[n])[0]) if p["mode"] == "on_trigger" else 0.0
        mode = p["mode"]
        send = (
            mode == "periodic"
            or (mode == "on_change" and not np.array_equal(data, xd[:-2]))
            or (mode == "on_trigger" and trig >= 0.5 > xd[-2])
        )
        b = bus(str(p["bus"]))
        if t >= p["fault_time"]:
            b.set_fault(
                self._msg.frame_id, drop=p["drop"], delay=p["delay"], off=p["bus_off"] >= 0.5, corrupt=p["corrupt"]
            )
        else:
            b.set_fault(self._msg.frame_id, drop=0.0, delay=0.0, off=False, corrupt=0.0)
        if send:
            b.send(t, self._msg.frame_id, bytes(int(x) for x in data), str(p["node"]), fd=self._msg.is_fd)
        return np.array([*data, trig, t if send else xd[-1]])


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
        widths: list[Width] = [self._length()] if self._raw() else [1] * (self.num_outputs() - 2)
        return [*widths, 1, 1]

    def initial_discrete_state(self) -> Array:
        n = self._length() if self._raw() else max(1, len(self.selected()))
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
            data = np.frombuffer(frame.data.ljust(self._msg.length, b"\0"), dtype=np.uint8).astype(float)
            if self._raw():
                values = data[:n]
            elif self._signals:
                mux = self._msg.multiplexer
                mux_value = unpack_raw(mux, data) if mux is not None else None
                values = np.array([unpack(s, data) if present(s, mux_value) else values[k]
                                   for k, s in enumerate(self._signals)])  # fmt: skip
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
        Param("data_bitrate", 2_000_000.0, ParamKind.FLOAT, "CAN FD data-phase bit rate", "bit/s", min=1.0),
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
        b.data_bitrate = float(self.params["data_bitrate"])
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
    Param("crc_byte", 0, ParamKind.INT, "Byte that holds the CRC", min=0, max=63),
    Param("counter_byte", 1, ParamKind.INT, "Byte whose low 4 bits hold the alive counter", min=0, max=63),
)  # fmt: skip


def _check_e2e_width(block: Block, width: int) -> None:
    if not 2 <= width <= 64:
        raise ValueError("the data input must be the frame's data bytes (2 to 64)")
    for name in ("crc_byte", "counter_byte"):
        if int(block.params[name]) >= width:
            raise ValueError(f"{name} {block.params[name]} is beyond the frame's {width} bytes")


def _bytes(u: Array) -> bytes:
    return bytes(int(v) & 0xFF for v in np.ravel(u))


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
        return [in_widths[0]]

    def output_types(self, in_types: list[Any]) -> list[Any]:
        from nervus.core.datatypes import parse_datatype

        return [parse_datatype("uint8")]

    def configure(self, in_widths: list[int], out_widths: list[int]) -> None:
        super().configure(in_widths, out_widths)
        _check_e2e_width(self, in_widths[0])
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
        _check_e2e_width(self, in_widths[0])

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


XCP_CAL_BASE = 0x00010000
XCP_MEAS_BASE = 0x00020000


def _names(text: str) -> list[str]:
    return [n.strip() for n in str(text).split(",") if n.strip()]


@register
class XcpSlave(Block):
    """Makes the simulated ECU reachable for a calibration tool over **XCP on CAN** (INCA, CANape, or
    ``nervus.xcp.XcpMaster``): the inputs are **measurements** that the tool can read, the outputs are
    **calibration** values that the tool can change while the simulation runs (like the ECU's calibration
    RAM). Use the outputs where the model needs the tunable value, e.g. as the gain of a controller.

    *calibrations* lists workspace variables (scalars); each output starts at the variable's value.
    *measurements* names the inputs. The memory map (8-byte IEEE doubles, Intel byte order): calibration
    *k* at 0x10000 + 8·k, measurement *k* at 0x20000 + 8·k; :meth:`write_a2l` writes the matching A2L file.

    Requests arrive on *request_id*, answers go out on *response_id* (both on *bus*). With an interface on
    the CAN Bus block and real-time pacing, a real tool on a real CAN adapter can connect.
    """

    type_id = "can.xcp_slave"
    label = "XCP Slave"
    category = CATEGORY
    DIRECT_FEEDTHROUGH = False
    PARAMS = (
        _BUS,
        Param("request_id", 0x7F0, ParamKind.INT, "CAN identifier of the requests (master → slave)", min=0,
              max=0x7FF),
        Param("response_id", 0x7F1, ParamKind.INT, "CAN identifier of the answers (slave → master)", min=0,
              max=0x7FF),
        Param("measurements", "", ParamKind.STR, "Names of the measured inputs, comma separated"),
        Param("calibrations", "", ParamKind.STR, "Workspace variables to calibrate (one output each)"),
        Param("sample_time", 0.001, ParamKind.SAMPLE_TIME, "Task period: requests are answered at this rate", "s"),
    )  # fmt: skip

    def num_inputs(self) -> int:
        return len(_names(self.params["measurements"]))

    def input_names(self) -> list[str]:
        return _names(self.params["measurements"])

    def num_outputs(self) -> int:
        return len(_names(self.params["calibrations"]))

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [1] * self.num_outputs()

    def validate_params(self) -> None:
        if self.params["request_id"] == self.params["response_id"]:
            raise ParameterError("the request and response identifiers must differ")
        for n in (*_names(self.params["measurements"]), *_names(self.params["calibrations"])):
            if not n.isidentifier():
                raise ParameterError(f"invalid name {n!r}")

    def _cal_values(self) -> list[float]:
        ns = self._namespace() or {}
        out = []
        for n in _names(self.params["calibrations"]):
            if n not in ns:
                raise ValueError(f"calibration {n!r} is not a workspace variable")
            out.append(float(np.ravel(ns[n])[0]))
        return out

    def configure(self, in_widths: list[int], out_widths: list[int]) -> None:
        from nervus.canbus import bus

        super().configure(in_widths, out_widths)
        if any(w != 1 for w in in_widths):
            raise ValueError("measurements must be scalar signals")
        self._initial = self._cal_values()
        bus(str(self.params["bus"])).reset()

    def initial_discrete_state(self) -> Array:
        try:
            cal = self._cal_values()
        except ValueError:
            cal = [0.0] * self.num_outputs()
        return np.array([0.0, 0.0, -1.0, *cal])  # connected, MTA, time up to which requests were read, values

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        return [np.array([v]) for v in xd[3:]]

    def memory(self, u: Sequence[Array], cal: np.ndarray) -> Any:
        from nervus.xcp import Memory, Region

        meas = np.array([float(np.ravel(x)[0]) for x in u], dtype="<f8")

        def write(offset: int, data: bytes) -> None:
            raw = bytearray(cal.astype("<f8").tobytes())
            raw[offset : offset + len(data)] = data
            cal[:] = np.frombuffer(bytes(raw), dtype="<f8")

        return Memory([
            Region(XCP_CAL_BASE, 8 * cal.size, lambda: cal.astype("<f8").tobytes(), write),
            Region(XCP_MEAS_BASE, 8 * meas.size, meas.tobytes),
        ])  # fmt: skip

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        from nervus.canbus import bus
        from nervus.xcp import XcpServer

        b = bus(str(self.params["bus"]))
        req_id, resp_id = int(self.params["request_id"]), int(self.params["response_id"])
        cal = xd[3:].copy()
        server = XcpServer(self.memory(u, cal))
        server.connected, server.mta = bool(xd[0]), int(xd[1])
        for f in b.delivered_between(float(xd[2]), t):
            if f.can_id == req_id:
                b.send(t, resp_id, server.handle(f.data), "XCP slave")
        return np.array([float(server.connected), float(server.mta), t, *cal])

    def write_a2l(self, path: str | Path, name: str = "nervus_xcp") -> Path:
        """An A2L file describing this slave's memory and its CAN identifiers, for INCA/CANape or XcpMaster."""
        ns_ws = self.diagram.root.workspace if self.diagram is not None else None
        lines = ["ASAP2_VERSION 1 71", f'/begin PROJECT {name} "Nervus XCP slave"', f'  /begin MODULE {name} ""',
                 '    /begin MOD_COMMON ""', "      BYTE_ORDER MSB_LAST", "    /end MOD_COMMON",
                 '    /begin COMPU_METHOD CM_IDENTICAL "identity" IDENTICAL "%12.6" ""', "    /end COMPU_METHOD",
                 "    /begin RECORD_LAYOUT RL_FLOAT64 FNC_VALUES 1 FLOAT64_IEEE ROW_DIR DIRECT",
                 "    /end RECORD_LAYOUT",
                 f"    /* XCP on CAN: CAN_ID_MASTER 0x{self.params['request_id']:X}, "
                 f"CAN_ID_SLAVE 0x{self.params['response_id']:X} */"]  # fmt: skip
        for k, n in enumerate(_names(self.params["calibrations"])):
            var = ns_ws.variable(n) if ns_ws is not None and n in ns_ws else None
            lo = var.min if var is not None and var.min is not None else -1e12
            hi = var.max if var is not None and var.max is not None else 1e12
            desc = (var.description if var is not None else "").replace('"', "'")
            lines += [f'    /begin CHARACTERISTIC {n} "{desc}"',
                      f"      VALUE 0x{XCP_CAL_BASE + 8 * k:X} RL_FLOAT64 0 CM_IDENTICAL {lo!r} {hi!r}",
                      *([f'      PHYS_UNIT "{var.unit}"'] if var is not None and var.unit else []),
                      "    /end CHARACTERISTIC"]  # fmt: skip
        for k, n in enumerate(_names(self.params["measurements"])):
            lines += [f'    /begin MEASUREMENT {n} ""', "      FLOAT64_IEEE CM_IDENTICAL 0 0 -1e12 1e12",
                      f"      ECU_ADDRESS 0x{XCP_MEAS_BASE + 8 * k:X}", "    /end MEASUREMENT"]  # fmt: skip
        lines += ["  /end MODULE", "/end PROJECT", ""]
        p = Path(path)
        p.write_text("\n".join(lines), encoding="utf-8")
        return p
