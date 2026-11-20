"""CAN FD frames, multiplexed signals, value tables and DBC variables."""

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("cantools")
import cantools

from nervus import Diagram, simulate
from nervus.blocks import CanPack, CanReceive, CanTransmit, CanUnpack, Constant, Inport, Outport, Scope
from nervus.can import dbc_variables, load_dbc, pack, present, unpack, unpack_raw
from nervus.canbus import bus, fd_frame_time, frame_bits
from nervus.codegen.sil import back_to_back, find_compiler

DBC = Path(__file__).parent.parent / "examples" / "data" / "chassis.dbc"


def test_fd_and_mux_match_cantools() -> None:
    msgs = load_dbc(DBC)
    db = cantools.database.load_file(str(DBC))
    assert msgs["WheelSpeeds"].is_fd and msgs["WheelSpeeds"].length == 32
    rng = np.random.default_rng(7)
    for m in msgs.values():
        for _ in range(200):
            data = rng.integers(0, 256, m.length)
            if m.multiplexer is not None:
                data[0] = rng.integers(1, 3)  # a page that exists
            ref = db.decode_message(m.frame_id, bytes(data.tolist()), decode_choices=False)
            mux = unpack_raw(m.multiplexer, data) if m.multiplexer else None
            got = {s.name: unpack(s, data) for s in m.signals if present(s, mux)}
            assert got.keys() == ref.keys()
            for k, v in ref.items():
                assert got[k] == pytest.approx(v, abs=1e-9)
            encoded = db.encode_message(m.frame_id, ref, scaling=True, strict=False)
            assert bytes(int(x) for x in pack(m, ref)) == encoded


def test_value_tables_and_variables() -> None:
    gear = load_dbc(DBC)["TransmissionStatus"].signal("GearSelector")
    assert gear.label(3) == "Drive"
    ws = {v.name: v for v in dbc_variables(DBC)}
    assert ws["GearSelector_Drive"].value == 3.0 and not ws["GearSelector_Drive"].calibratable
    assert ws["CurrentGear"].value == 1.0  # GenSigStartValue
    assert ws["OilTemp"].value == -40.0 and ws["OilTemp"].unit == "degC" and ws["OilTemp"].min == -40.0
    assert "Position of the gear selector lever" in ws["GearSelector"].description


def _mux_model() -> Diagram:
    d = Diagram("mux")
    page = d.add(Inport(port=1), name="page")
    temp = d.add(Inport(port=2), name="oil_temp")
    volt = d.add(Inport(port=3), name="battery")
    p = d.add(CanPack(dbc_file=str(DBC), message="Diagnostics", signals="Page, OilTemp, BatteryVoltage"), name="pack")
    u = d.add(CanUnpack(dbc_file=str(DBC), message="Diagnostics", signals="OilTemp, BatteryVoltage"), name="unpack")
    for k, src in enumerate((page, temp, volt)):
        d.connect(src, (p, k))
    d.chain(p, u)
    d.connect((u, 0), d.add(Outport(port=1), name="oil_out"))
    d.connect((u, 1), d.add(Outport(port=2), name="volt_out"))
    d.connect(p, d.add(Outport(port=3), name="frame"))
    return d


def _mux_inputs(steps: int) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(2)
    return {
        "page": rng.integers(1, 3, steps).astype(float),
        "oil_temp": rng.uniform(-40, 200, steps),
        "battery": rng.uniform(10, 15, steps),
    }


def test_multiplexed_outputs_hold() -> None:
    d = _mux_model()
    for b in d.blocks:
        if isinstance(b, Inport):
            b.set_param("sample_time", 0.1)
    inputs = _mux_inputs(6)
    t = np.arange(6) * 0.1
    r = simulate(d, 0.5, solver="rk4", step=0.1, inputs={k: (t, v) for k, v in inputs.items()})
    oil, volt = np.ravel(r["oil_out"]), np.ravel(r["volt_out"])
    for k in range(6):
        i = np.searchsorted(r.t, t[k])
        if inputs["page"][k] == 1:
            assert oil[i] == pytest.approx(round(inputs["oil_temp"][k]))
        else:
            assert volt[i] == pytest.approx(inputs["battery"][k], abs=0.001)
            if k and inputs["page"][k - 1] == 1:
                assert oil[i] == oil[i - 1]  # held while the other page is sent


@pytest.mark.skipif(find_compiler() is None, reason="no C compiler")
def test_fd_and_mux_codegen_bit_true(tmp_path: Path) -> None:
    d = _mux_model()
    for b in d.blocks:
        if isinstance(b, Inport):
            b.set_param("sample_time", 0.01)
    fd = d.add(Inport(port=4, value=np.zeros(32), output_type="uint8", sample_time=0.01), name="fd_frame")
    u = d.add(CanUnpack(dbc_file=str(DBC), message="WheelSpeeds"), name="wheels")
    d.chain(fd, u)
    pk = d.add(CanPack(dbc_file=str(DBC), message="WheelSpeeds"), name="wheels_tx")
    for k in range(6):
        d.connect((u, k), (pk, k))
        d.connect((u, k), d.add(Outport(port=4 + k), name=f"w{k}"))
    d.connect(pk, d.add(Outport(port=10), name="fd_out"))
    steps = 60
    inputs = _mux_inputs(steps)
    inputs["fd_frame"] = np.random.default_rng(4).integers(0, 256, (steps, 32)).astype(float)
    res = back_to_back(d, inputs, steps, tolerance=0.0, folder=tmp_path)
    assert res.passed, res.summary()


def test_fd_frames_on_the_bus(tmp_path: Path) -> None:
    can = pytest.importorskip("can")
    # Bit-rate switching: an 8-byte FD frame is faster than a classic one; 32 bytes still take < 0.25 ms.
    assert fd_frame_time(0x600, bytes(8), 500e3, 2e6) < frame_bits(0x600, bytes(8)) / 500e3
    assert fd_frame_time(0x600, bytes(32), 500e3, 2e6) < 0.25e-3
    d = Diagram()
    vals = d.add(Constant(value=88.0), name="v")
    tx = d.add(CanTransmit(dbc_file=str(DBC), message="WheelSpeeds", signals="WheelFL, WheelRR"), name="tx")
    d.connect(vals, (tx, 0))
    d.connect(vals, (tx, 1))
    rx = d.add(CanReceive(dbc_file=str(DBC), message="WheelSpeeds", signals="WheelRR"), name="rx")
    for k in range(3):
        d.connect((rx, k), d.add(Scope()))
    r = simulate(d, 0.1, solver="rk4", step=0.001)
    assert r["rx"][-1] == 88.0
    b = bus("can0")
    assert all(f.fd and len(f.data) == 32 for f in b.trace)
    msgs = list(can.ASCReader(str(b.write_asc(tmp_path / "fd.asc"))))
    assert len(msgs) == len(b.trace) and msgs[0].is_fd and len(msgs[0].data) == 32
