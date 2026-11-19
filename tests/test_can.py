from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("cantools")

import cantools

from nervus import Diagram, ParameterError, load, save, simulate
from nervus.blocks import CanPack, CanUnpack, Constant, Inport, Outport, Scope, ZeroOrderHold
from nervus.can import load_dbc, pack, unpack
from nervus.codegen.sil import back_to_back, find_compiler

DBC = Path(__file__).parent.parent / "examples" / "data" / "vehicle.dbc"


def test_unpack_matches_cantools() -> None:
    msgs = load_dbc(DBC)
    db = cantools.database.load_file(str(DBC))
    rng = np.random.default_rng(3)
    for m in msgs.values():
        for _ in range(200):
            data = rng.integers(0, 256, 8)
            ref = db.decode_message(m.frame_id, bytes(data.tolist()), decode_choices=False)
            for s in m.signals:
                assert unpack(s, data) == pytest.approx(ref[s.name], abs=1e-9)


def test_pack_roundtrip_and_saturation() -> None:
    m = load_dbc(DBC)["EngineData"]
    data = pack(m, {"EngineSpeed": 812.3, "CoolantTemp": 90.4, "EngineTorque": -55.25, "MIL_On": 1})
    assert unpack(m.signal("EngineSpeed"), data) == 812.25  # 0.25 rpm resolution
    assert unpack(m.signal("CoolantTemp"), data) == 90.0
    assert unpack(m.signal("EngineTorque"), data) == -55.5  # -55.25 / 0.5 = -110.5 rounds away from zero
    assert unpack(m.signal("MIL_On"), data) == 1.0
    sat = pack(m, {"CoolantTemp": 500.0})
    assert unpack(m.signal("CoolantTemp"), sat) == 215.0


def _model(signals: str = "") -> Diagram:
    d = Diagram("can")
    rpm = d.add(Constant(value=1500.0), name="rpm")
    temp = d.add(Constant(value=85.0), name="temp")
    p = d.add(CanPack(dbc_file=str(DBC), message="EngineData", signals="EngineSpeed, CoolantTemp"), name="pack")
    u = d.add(CanUnpack(dbc_file=str(DBC), message="EngineData", signals=signals), name="unpack")
    d.connect(rpm, (p, 0))
    d.connect(temp, (p, 1))
    d.chain(p, u)
    for k in range(u.num_outputs()):
        d.connect((u, k), d.add(Scope()))
    return d


def test_blocks_roundtrip_in_simulation(tmp_path) -> None:  # type: ignore[no-untyped-def]
    d = _model("CoolantTemp, EngineSpeed")
    r = simulate(d, 0.0)
    assert r["unpack:0"][-1] == 85.0 and r["unpack:1"][-1] == 1500.0
    assert r["pack"].shape == (1, 8)
    # Relative DBC path resolved against the model file.
    d2 = _model()
    d2.block("pack").set_param("dbc_file", "vehicle.dbc")
    d2.block("unpack").set_param("dbc_file", "vehicle.dbc")
    (tmp_path / "vehicle.dbc").write_text(DBC.read_text())
    save(d2, tmp_path / "m")
    again = load(tmp_path / "m.nervus")
    assert again.block("unpack").num_outputs() == 5
    assert simulate(again, 0.0)["unpack:1"][-1] == 85.0


def test_errors() -> None:
    d = Diagram()
    u = d.add(CanUnpack(dbc_file=str(DBC), message="Nope"), name="u")
    d.chain(d.add(Constant(value=np.zeros(8))), u, d.add(Scope()))
    with pytest.raises(Exception, match=r"not in vehicle\.dbc"):
        simulate(d, 0.0)
    with pytest.raises(ParameterError, match="signals not in"):
        CanUnpack(dbc_file=str(DBC), message="EngineData", signals="Bogus").selected()


@pytest.mark.skipif(find_compiler() is None, reason="no C compiler")
def test_can_codegen_bit_true(tmp_path) -> None:  # type: ignore[no-untyped-def]
    d = Diagram("canio")
    frame = d.add(Inport(port=1, value=np.zeros(8), output_type="uint8"), name="rx_frame")
    z = d.add(ZeroOrderHold(sample_time=0.01), name="z")
    u = d.add(CanUnpack(dbc_file=str(DBC), message="VehicleData"), name="rx")
    d.chain(frame, z, u)
    p = d.add(CanPack(dbc_file=str(DBC), message="EngineData"), name="tx")
    for k in range(5):
        src = d.add(Inport(port=k + 2), name=f"sig{k}")
        zk = d.add(ZeroOrderHold(sample_time=0.01))
        d.chain(src, zk)
        d.connect(zk, (p, k))
    for k in range(4):
        d.connect((u, k), d.add(Outport(port=k + 1), name=f"rx_{k}"))
    d.connect(p, d.add(Outport(port=5), name="tx_frame"))
    rng = np.random.default_rng(11)
    steps = 100
    inputs = {"rx_frame": rng.integers(0, 256, (steps, 8)).astype(float)}
    for k, (lo, hi) in enumerate([(0, 9000), (-60, 260), (-5, 110), (-1100, 1100), (0, 1)]):
        inputs[f"sig{k}"] = rng.uniform(lo, hi, steps)
    res = back_to_back(d, inputs, steps, tolerance=0.0, folder=tmp_path)
    assert res.passed, res.summary()
