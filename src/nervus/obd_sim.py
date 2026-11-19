"""A simulated car ECU that answers OBD-II requests, so diagnostic tools can be tested without a car.

:class:`SimulatedEcu` holds current PID values and trouble codes and answers OBD services (SAE J1979):
mode 01 (live data, including PID 01: MIL and number of codes), 03/07/0A (stored, pending, permanent codes),
04 (clear codes), 09 PID 02 (VIN). It speaks three ways:

* :meth:`SimulatedEcu.request` for raw service bytes (``b"\\x01\\x0c"`` -> ``b"\\x41\\x0c\\x1a\\xf8"``);
* as an **ELM327 adapter** (AT commands and hex text): it is a :class:`nervus.obd.Transport`, so
  ``Elm327(SimulatedEcu())`` talks to it, and :func:`serve_pty` offers it on a pseudo-terminal (macOS/Linux)
  for any OBD program;
* on a **CAN bus** (ISO 15765-4) with :meth:`SimulatedEcu.serve_can` (see :mod:`nervus.obd_can`).

In a model, the **OBD Responder** block feeds model signals and Diagnostic Monitor statuses into an ECU while
the simulation runs::

    uv run python -m nervus.obd simulate examples/obd_ecu.nervus     # runs in real time, prints the port
"""

from __future__ import annotations

import os
import threading
from collections.abc import Mapping

from nervus.obd import BY_NUMBER, PIDS

CONFIRMED, PENDING, WARNING_INDICATOR, NOT_COMPLETED_SINCE_CLEAR = 0x08, 0x04, 0x80, 0x10

_REGISTRY: dict[str, SimulatedEcu] = {}


def ecu(name: str = "ecu") -> SimulatedEcu:
    """The simulated ECU named ``name`` (created on first use); OBD Responder blocks publish into it."""
    if name not in _REGISTRY:
        _REGISTRY[name] = SimulatedEcu()
    return _REGISTRY[name]


def encode_dtc(code: str) -> bytes:
    """``"P0133"`` -> ``b"\\x01\\x33"`` (the inverse of :func:`nervus.obd.decode_dtc`)."""
    letter = "PCBU".index(code[0].upper())
    a = (letter << 6) | (int(code[1]) << 4) | int(code[2], 16)
    return bytes([a, int(code[3:5], 16)])


class SimulatedEcu:
    """An engine ECU as seen through the OBD port. Thread-safe: a simulation can update it while a tool reads."""

    def __init__(
        self,
        values: Mapping[str, float] | None = None,
        dtcs: Mapping[str, int] | None = None,
        vin: str = "NERVUS0SIMULATED0",
    ) -> None:
        self._lock = threading.Lock()
        self.values: dict[str, float] = dict(values or {})
        """Current values by PID name (``rpm``, ``speed``, ...); only these PIDs are reported as supported."""
        self.dtcs: dict[str, int] = dict(dtcs or {})
        """Trouble codes and their UDS status byte (see the Diagnostic Monitor block)."""
        self.vin = vin
        self.clear_requests = 0
        """How many mode 04 requests arrived (a model can react, e.g. clear its monitors)."""
        self.log: list[tuple[bytes, bytes | None]] = []
        """Requests and replies, for tests and debugging (the last 200)."""
        self._echo, self._spaces, self._headers = True, True, False
        self._pending = b""

    # ------------------------------------------------------------------ data from the model

    def update(self, values: Mapping[str, float] | None = None, dtcs: Mapping[str, int] | None = None) -> None:
        with self._lock:
            if values:
                self.values.update(values)
            if dtcs:
                self.dtcs.update(dtcs)

    # ------------------------------------------------------------------ OBD services

    def _codes(self, bit: int) -> list[str]:
        return [code for code, status in self.dtcs.items() if status & bit]

    def request(self, service: bytes) -> bytes | None:
        """Answer one OBD request (service bytes without length or headers); ``None``: no answer (NO DATA)."""
        with self._lock:
            reply = self._answer(bytes(service))
            self.log = [*self.log[-199:], (bytes(service), reply)]
            return reply

    def _answer(self, req: bytes) -> bytes | None:
        if not req:
            return None
        mode = req[0]
        if mode == 0x01 and len(req) >= 2:
            pid = req[1]
            if pid % 0x20 == 0:  # supported PIDs pid+1 .. pid+32
                supported = {PIDS[n].pid for n in self.values if n in PIDS} | {0x01}
                bits = 0
                for k in range(32):
                    n = pid + k + 1
                    if n in supported or (k == 31 and any(x > n for x in supported)):
                        bits |= 1 << (31 - k)
                return bytes([0x41, pid]) + bits.to_bytes(4, "big") if bits or pid == 0 else None
            if pid == 0x01:  # monitor status since codes were cleared: MIL, number of codes, readiness
                confirmed = self._codes(CONFIRMED)
                mil = any(s & WARNING_INDICATOR for s in self.dtcs.values())
                incomplete = any(s & NOT_COMPLETED_SINCE_CLEAR for s in self.dtcs.values())
                a = (0x80 if mil else 0) | min(len(confirmed), 0x7F)
                b = 0x07 | (0x40 if incomplete else 0)  # misfire, fuel system, components; components complete?
                return bytes([0x41, 0x01, a, b, 0x00, 0x00])
            spec = BY_NUMBER.get(pid)
            if spec is None or spec.name not in self.values:
                return None
            return bytes([0x41, pid]) + spec.encode(self.values[spec.name])
        if mode in (0x03, 0x07, 0x0A):
            codes = self._codes(CONFIRMED) if mode in (0x03, 0x0A) else self._codes(PENDING)
            return bytes([0x40 + mode, len(codes)]) + b"".join(encode_dtc(c) for c in codes)
        if mode == 0x04:  # clear: the model decides what that means (the responder passes it on)
            self.clear_requests += 1
            for code in self.dtcs:
                self.dtcs[code] = NOT_COMPLETED_SINCE_CLEAR | 0x40
            return bytes([0x44])
        if mode == 0x09 and len(req) >= 2 and req[1] == 0x02:
            return bytes([0x49, 0x02, 0x01]) + self.vin.encode("ascii")[:17].ljust(17, b"0")
        if mode == 0x09 and len(req) >= 2 and req[1] == 0x00:
            return bytes([0x49, 0x00, 0x40, 0x00, 0x00, 0x00])  # PID 02 (VIN) supported
        return None

    # ------------------------------------------------------------------ ELM327 text protocol

    def elm327(self, line: str) -> str:
        """The reply of an ELM327 adapter (without the ``>`` prompt) to one command line."""
        cmd = line.strip().upper().replace(" ", "")
        echo = line.strip() + "\r" if self._echo else ""
        if cmd.startswith("AT"):
            at = cmd[2:]
            if at == "Z":
                self._echo, self._spaces, self._headers = True, True, False
                return echo + "\rELM327 v1.5 (Nervus simulated ECU)"
            if at == "I":
                return echo + "ELM327 v1.5"
            if at in ("E0", "E1"):
                self._echo = at == "E1"
            elif at in ("S0", "S1"):
                self._spaces = at == "S1"
            elif at in ("H0", "H1"):
                self._headers = at == "H1"
            elif at == "DP":
                return echo + "ISO 15765-4 (CAN 11/500)"
            elif at == "RV":
                return echo + "14.2V"
            return echo + "OK"
        try:
            req = bytes.fromhex(cmd)
        except ValueError:
            return echo + "?"
        reply = self.request(req)
        if reply is None:
            return echo + "NO DATA"
        sep = " " if self._spaces else ""
        if len(reply) <= 7:
            return echo + sep.join(f"{b:02X}" for b in reply)
        # Longer than one CAN frame: the ELM327 shows the byte count, then numbered frames.
        lines = [f"{len(reply):03X}"]
        chunks = [reply[:6]] + [reply[k : k + 7] for k in range(6, len(reply), 7)]
        lines += [f"{k:X}:{sep}" + sep.join(f"{b:02X}" for b in c) for k, c in enumerate(chunks)]
        return echo + "\r".join(lines)

    # Transport protocol (nervus.obd.Elm327 talks to this object like to a serial port)

    def write(self, data: bytes) -> int:
        self._pending += bytes(data)
        return len(data)

    def read_until(self, expected: bytes = b">") -> bytes:
        text = self._pending.decode("ascii", errors="replace")
        self._pending = b""
        replies = [self.elm327(line) for line in text.split("\r") if line.strip()]
        return ("\r".join(replies) + "\r\r>").encode("ascii")


def serve_pty(sim: SimulatedEcu) -> tuple[str, threading.Thread]:
    """Offer ``sim`` as an ELM327 on a pseudo-terminal (macOS/Linux). Returns the device path (give it to the
    OBD program as its serial port) and the serving thread (a daemon: it ends with the program)."""
    import pty
    import tty

    master, slave = pty.openpty()
    tty.setraw(slave)
    path = os.ttyname(slave)

    def loop() -> None:
        buf = b""
        while True:
            try:
                chunk = os.read(master, 256)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\r" in buf:
                line, buf = buf.split(b"\r", 1)
                reply = sim.elm327(line.decode("ascii", errors="replace"))
                os.write(master, (reply + "\r\r>").encode("ascii"))

    thread = threading.Thread(target=loop, name="obd-pty", daemon=True)
    thread.start()
    return path, thread
