"""OBD-II: read live data from a car through its diagnostic port (read-only).

Every petrol car since 2001 (EU) / 1996 (US) and diesel since 2004 has an OBD-II port. With an **ELM327**
adapter (USB or Bluetooth, a few euros) you can read standard values such as engine speed, coolant temperature
or throttle position, defined by SAE J1979 as *mode 01 PIDs*. This module decodes those PIDs, talks to an
ELM327, and records a drive into a Nervus result file that you can plot in the Data Inspector or replay as a
test input::

    uv run python -m nervus.obd pids                                    # list the known PIDs
    uv run python -m nervus.obd record --port /dev/tty.usbserial-1110 \\
        --pids rpm,speed,coolant_temp,throttle --duration 120 --out drive.nervres

Nervus only sends standard *read* requests (mode 01). It never writes to or reprograms the car's ECUs.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from nervus.sim.result import SimResult, SimStats


@dataclass(frozen=True)
class Pid:
    pid: int
    name: str
    description: str
    unit: str
    n_bytes: int
    decode: Callable[[bytes], float]

    @property
    def request(self) -> str:
        return f"01{self.pid:02X}"


def _a(d: bytes) -> int:
    return d[0]


def _ab(d: bytes) -> int:
    return 256 * d[0] + d[1]


PIDS: dict[str, Pid] = {
    p.name: p
    for p in (
        Pid(0x04, "engine_load", "Calculated engine load", "%", 1, lambda d: _a(d) * 100 / 255),
        Pid(0x05, "coolant_temp", "Engine coolant temperature", "°C", 1, lambda d: _a(d) - 40),
        Pid(0x06, "stft_b1", "Short-term fuel trim, bank 1", "%", 1, lambda d: (_a(d) - 128) * 100 / 128),
        Pid(0x07, "ltft_b1", "Long-term fuel trim, bank 1", "%", 1, lambda d: (_a(d) - 128) * 100 / 128),
        Pid(0x0B, "map", "Intake manifold absolute pressure", "kPa", 1, lambda d: float(_a(d))),
        Pid(0x0C, "rpm", "Engine speed", "rpm", 2, lambda d: _ab(d) / 4),
        Pid(0x0D, "speed", "Vehicle speed", "km/h", 1, lambda d: float(_a(d))),
        Pid(0x0E, "timing_advance", "Ignition timing advance before TDC", "°", 1, lambda d: _a(d) / 2 - 64),
        Pid(0x0F, "intake_temp", "Intake air temperature", "°C", 1, lambda d: _a(d) - 40),
        Pid(0x10, "maf", "Mass air flow", "g/s", 2, lambda d: _ab(d) / 100),
        Pid(0x11, "throttle", "Throttle position", "%", 1, lambda d: _a(d) * 100 / 255),
        Pid(0x14, "o2_b1s1", "Oxygen sensor voltage, bank 1 sensor 1", "V", 2, lambda d: _a(d) / 200),
        Pid(0x1F, "run_time", "Time since engine start", "s", 2, lambda d: float(_ab(d))),
        Pid(0x2F, "fuel_level", "Fuel tank level", "%", 1, lambda d: _a(d) * 100 / 255),
        Pid(0x33, "baro", "Barometric pressure", "kPa", 1, lambda d: float(_a(d))),
        Pid(0x42, "module_voltage", "Control module voltage", "V", 2, lambda d: _ab(d) / 1000),
        Pid(0x44, "lambda_cmd", "Commanded air-fuel equivalence ratio (lambda)", "-", 2, lambda d: _ab(d) * 2 / 65536),
        Pid(0x46, "ambient_temp", "Ambient air temperature", "°C", 1, lambda d: _a(d) - 40),
        Pid(0x49, "pedal_d", "Accelerator pedal position D", "%", 1, lambda d: _a(d) * 100 / 255),
        Pid(0x5C, "oil_temp", "Engine oil temperature", "°C", 1, lambda d: _a(d) - 40),
        Pid(0x5E, "fuel_rate", "Engine fuel rate", "L/h", 2, lambda d: _ab(d) / 20),
    )
}
BY_NUMBER = {p.pid: p for p in PIDS.values()}


class ObdError(Exception):
    pass


def parse_response(text: str, mode: int, pid: int) -> bytes | None:
    """Data bytes of an ELM327 reply such as ``"41 0C 1A F8"`` (``None`` for ``NO DATA``).

    Handles echo, spaces or no spaces, ``SEARCHING...``, several lines and several ECUs answering (the first
    matching answer is used).
    """
    want = f"{0x40 + mode:02X}{pid:02X}"
    for line in text.replace("\r", "\n").split("\n"):
        compact = line.strip().replace(" ", "").upper()
        if not compact or compact.startswith(("SEARCHING", ">")):
            continue
        if "NODATA" in compact or "ERROR" in compact or "UNABLETOCONNECT" in compact:
            return None
        k = compact.find(want)
        if k >= 0:
            hexdata = compact[k + len(want) :]
            try:
                return bytes.fromhex(hexdata[: (len(hexdata) // 2) * 2])
            except ValueError:
                continue
    return None


def supported_from_bitmask(base: int, data: bytes) -> set[int]:
    """PIDs announced as supported by a reply to PID 0x00, 0x20, 0x40, ... (4 bytes, MSB first)."""
    bits = int.from_bytes(data[:4], "big")
    return {base + k + 1 for k in range(32) if bits & (1 << (31 - k))}


class Transport(Protocol):
    def write(self, data: bytes) -> object: ...

    def read_until(self, expected: bytes) -> bytes: ...


class SerialTransport:
    """A serial port (USB or Bluetooth SPP) to an ELM327; needs ``pyserial`` (``uv sync --extra obd``)."""

    def __init__(self, port: str, baudrate: int = 38400, timeout: float = 5.0) -> None:
        try:
            import serial
        except ImportError as exc:
            raise ObdError("talking to an ELM327 needs pyserial: uv sync --extra obd") from exc
        self.port = serial.Serial(port, baudrate=baudrate, timeout=timeout)

    def write(self, data: bytes) -> object:
        return self.port.write(data)

    def read_until(self, expected: bytes) -> bytes:
        return bytes(self.port.read_until(expected))


class Elm327:
    """Minimal ELM327 client: initialise, ask which PIDs the car supports, and read PIDs."""

    def __init__(self, transport: Transport) -> None:
        self.t = transport
        self.supported: set[int] = set()

    def command(self, cmd: str) -> str:
        self.t.write((cmd + "\r").encode("ascii"))
        return self.t.read_until(b">").decode("ascii", errors="replace").replace(">", "").strip()

    def initialize(self) -> set[int]:
        for cmd in ("ATZ", "ATE0", "ATL0", "ATS1", "ATH0", "ATSP0"):  # reset, no echo, auto protocol
            self.command(cmd)
        self.supported = set()
        base = 0
        while True:
            data = parse_response(self.command(f"01{base:02X}"), 1, base)
            if data is None or len(data) < 4:
                break
            found = supported_from_bitmask(base, data)
            self.supported |= found
            if base + 0x20 not in found:
                break
            base += 0x20
        if not self.supported:
            raise ObdError("no answer from the car: is the ignition on and the adapter connected?")
        return self.supported

    def read(self, pid: Pid) -> float | None:
        data = parse_response(self.command(pid.request), 1, pid.pid)
        if data is None or len(data) < pid.n_bytes:
            return None
        return float(pid.decode(data[: pid.n_bytes]))


def record(
    elm: Elm327,
    pids: Sequence[str],
    duration: float,
    interval: float = 0.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    on_sample: Callable[[float, dict[str, float]], None] | None = None,
) -> SimResult:
    """Poll ``pids`` (names from :data:`PIDS`) for ``duration`` seconds into a result.

    Each signal is named after its PID (``rpm``, ``speed``, ...). Missing answers are stored as NaN. The time
    axis is the time each sweep over all PIDs started.
    """
    chosen = [PIDS[p] for p in pids]
    unsupported = [p.name for p in chosen if elm.supported and p.pid not in elm.supported]
    if unsupported:
        raise ObdError(f"the car does not report: {', '.join(unsupported)}")
    t0 = clock()
    times: list[float] = []
    rows: list[list[float]] = []
    while True:
        now = clock() - t0
        if now > duration:
            break
        values = {}
        for p in chosen:
            v = elm.read(p)
            values[p.name] = np.nan if v is None else v
        times.append(now)
        rows.append([values[p.name] for p in chosen])
        if on_sample is not None:
            on_sample(now, values)
        if interval > 0:
            sleep(max(0.0, interval - (clock() - t0 - now)))
    data = np.array(rows, dtype=float).reshape(len(times), len(chosen))
    signals = {f"{p.name}:0": data[:, k : k + 1] for k, p in enumerate(chosen)}
    stats = SimStats("obd", None, len(times), len(times), float(times[-1]) if times else 0.0)
    return SimResult(np.array(times), signals, {}, {}, stats)


def _main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m nervus.obd", description="Read live data from a car (read-only).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pids", help="list the PIDs Nervus can decode")
    sp = sub.add_parser("supported", help="ask the car which PIDs it supports")
    sp.add_argument("--port", required=True)
    rp = sub.add_parser("record", help="record PIDs to a .nervres or .csv file")
    rp.add_argument("--port", required=True)
    rp.add_argument("--pids", default="rpm,speed,coolant_temp,throttle,engine_load")
    rp.add_argument("--duration", type=float, default=60.0)
    rp.add_argument("--interval", type=float, default=0.0, help="seconds between sweeps (0 = as fast as possible)")
    rp.add_argument("--out", default="drive.nervres")
    args = ap.parse_args(argv)
    if args.cmd == "pids":
        for p in PIDS.values():
            print(f"{p.name:16s} 01{p.pid:02X}  {p.unit:6s} {p.description}")
        return 0
    elm = Elm327(SerialTransport(args.port))
    supported = elm.initialize()
    if args.cmd == "supported":
        for n in sorted(supported):
            known = BY_NUMBER.get(n)
            print(f"01{n:02X}  {known.name if known else '(not decoded by Nervus)'}")
        return 0
    names = [p.strip() for p in args.pids.split(",") if p.strip()]
    res = record(
        elm,
        names,
        args.duration,
        args.interval,
        on_sample=lambda t, v: print(f"{t:7.2f} s  " + "  ".join(f"{k}={x:.1f}" for k, x in v.items())),
    )
    if args.out.endswith(".csv"):
        res.to_csv(args.out)
    else:
        res.save(args.out)
    print(f"saved {len(res.t)} samples to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
