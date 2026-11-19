"""The simulated OBD ECU: ELM327 text protocol, pseudo-terminal, CAN (ISO-TP), and the OBD Responder block."""

import os
import sys

import numpy as np
import pytest

from nervus.obd import PIDS, Elm327
from nervus.obd_sim import CONFIRMED, PENDING, WARNING_INDICATOR, SimulatedEcu, encode_dtc

VALUES = {"rpm": 2175.25, "speed": 63.0, "coolant_temp": 88.0, "engine_load": 40.0}
DTCS = {"P0302": CONFIRMED | PENDING | WARNING_INDICATOR, "P0171": PENDING}


def _ecu() -> SimulatedEcu:
    return SimulatedEcu(VALUES, DTCS, vin="WVWZZZ1KZAW123456")


def test_encode_dtc_round_trip() -> None:
    from nervus.obd import decode_dtc

    for code in ("P0302", "P0171", "U0100", "C1234", "B2A0F"):
        assert decode_dtc(encode_dtc(code)) == code


def test_elm327_client_talks_to_the_simulated_ecu() -> None:
    elm = Elm327(_ecu())
    supported = elm.initialize()
    assert {0x01, 0x04, 0x05, 0x0C, 0x0D} <= supported
    assert elm.read(PIDS["rpm"]) == 2175.25
    assert elm.read(PIDS["coolant_temp"]) == 88.0
    assert elm.read(PIDS["maf"]) is None  # not provided: NO DATA
    assert elm.trouble_codes("stored") == ["P0302"]
    assert elm.trouble_codes("pending") == ["P0302", "P0171"]
    assert elm.vin() == "WVWZZZ1KZAW123456"  # a multi-frame answer


def test_monitor_status_and_clear() -> None:
    sim = _ecu()
    reply = sim.request(b"\x01\x01")
    assert reply is not None and reply[2] == 0x80 | 1  # MIL on, one confirmed code
    assert sim.request(b"\x04") == b"\x44"
    assert sim.clear_requests == 1
    assert sim.request(b"\x03") == b"\x43\x00"


@pytest.mark.skipif(sys.platform == "win32", reason="pseudo-terminals are POSIX only")
def test_serve_on_a_pseudo_terminal() -> None:
    import termios
    import tty

    from nervus.obd_sim import serve_pty

    path, _thread = serve_pty(_ecu())
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY)
    try:
        tty.setraw(fd)
        termios.tcflush(fd, termios.TCIOFLUSH)

        class Port:
            def write(self, data: bytes) -> int:
                return os.write(fd, data)

            def read_until(self, expected: bytes) -> bytes:
                out = b""
                while not out.endswith(expected):
                    out += os.read(fd, 256)
                return out

        elm = Elm327(Port())
        elm.initialize()
        assert elm.read(PIDS["speed"]) == 63.0
        assert elm.trouble_codes() == ["P0302"]
    finally:
        os.close(fd)


def test_obd_over_can_iso_tp() -> None:
    pytest.importorskip("can")
    import can

    from nervus.obd_can import CanObd, segment, serve_can

    assert segment(b"\x01\x0c") == [b"\x02\x01\x0c"]
    long = segment(bytes(range(20)))
    assert long[0][:2] == b"\x10\x14" and [f[0] for f in long[1:]] == [0x21, 0x22]
    stop = serve_can(_ecu(), "virtual", "obd_test")
    client = CanObd(can.Bus(interface="virtual", channel="obd_test"))
    try:
        assert 0x0C in client.initialize()
        assert client.read(PIDS["rpm"]) == 2175.25
        assert client.trouble_codes("pending") == ["P0302", "P0171"]
        assert client.vin() == "WVWZZZ1KZAW123456"  # first frame, flow control, consecutive frames
        assert client.read(PIDS["maf"]) is None
    finally:
        client.close()
        stop()


def test_responder_block_in_a_model(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import nervus.sim.simulator as simulator
    from nervus import load, simulate
    from nervus.obd_sim import _REGISTRY, ecu

    _REGISTRY.clear()
    from pathlib import Path

    d = load(Path(__file__).parent.parent / "examples" / "obd_ecu.nervus")
    sim = ecu()
    monkeypatch.setattr(simulator, "LIVE_INTERVAL", 0.0)
    cleared = []

    def tool(partial):  # type: ignore[no-untyped-def]
        # A scan tool connected while the model runs: it clears the codes once, at 60 s.
        if partial.t[-1] >= 60.0 and not cleared:
            cleared.append(sim.request(b"\x04"))

    res = simulate(d, 75.0, live=tool)
    assert cleared == [b"\x44"]
    k = int(np.searchsorted(res.t, 59.0))
    assert res["mil"][k] == 1.0
    assert res["mil"][-1] == 0.0  # the clear reached the monitors in the model
    assert res["misfire_ready"][int(np.searchsorted(res.t, 60.5))] == 0.0  # readiness reset
    elm = Elm327(sim)
    elm.initialize()
    assert elm.read(PIDS["coolant_temp"]) == pytest.approx(res["coolant_temp"][-1], abs=1.0)


@pytest.mark.skipif(sys.platform == "win32", reason="pseudo-terminals are POSIX only")
def test_simulate_command(capsys) -> None:  # type: ignore[no-untyped-def]
    from pathlib import Path

    from nervus.obd import _main

    model = Path(__file__).parent.parent / "examples" / "obd_ecu.nervus"
    assert _main(["simulate", str(model), "--fast", "--duration", "2"]) == 0
    out = capsys.readouterr().out
    assert "ELM327 on /dev/" in out and "done" in out
