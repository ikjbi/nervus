"""The simulated CAN bus: frame timing, arbitration, faults, timeouts and log export."""

from pathlib import Path

import numpy as np
import pytest

from nervus import Diagram, simulate
from nervus.blocks import CanBusSetup, CanReceive, CanTransmit, Constant, Scope, Sine, ZeroOrderHold
from nervus.canbus import CanBus, bus, frame_bits

pytest.importorskip("cantools")
DBC = str(Path(__file__).parent.parent / "examples" / "data" / "vehicle.dbc")


def test_frame_length() -> None:
    # 8 data bytes: 108 bits plus the 3-bit inter-frame space, before stuffing; zeros need the most stuff bits.
    assert frame_bits(0x100, bytes(8)) > frame_bits(0x100, bytes([0x55] * 8))
    assert 111 <= frame_bits(0x100, bytes([0x55] * 8)) <= 111 + 3
    assert frame_bits(0x100, bytes(8)) <= 111 + 24  # at most one stuff bit per four bits


def test_lowest_identifier_wins() -> None:
    b = CanBus("t", bitrate=125_000)
    b.send(0.0, 0x300, bytes(8))
    b.send(0.0, 0x100, bytes(8))
    b.send(0.0, 0x200, bytes(8))
    b.receive(0.01, -1)
    assert [f.can_id for f in b.trace] == [0x100, 0x200, 0x300]
    assert b.trace[1].start == pytest.approx(b.trace[0].end)
    lat = [b.latency(i)[0] for i in (0x100, 0x200, 0x300)]
    assert lat[0] < lat[1] < lat[2]
    assert lat[0] == pytest.approx(frame_bits(0x100, bytes(8)) / 125_000)


def _diagram(**tx: object) -> Diagram:
    d = Diagram()
    src = d.add(Sine(amplitude=1000.0, bias=2000.0, frequency=1.0), name="rpm")
    t = d.add(CanTransmit(dbc_file=DBC, message="EngineData", signals="EngineSpeed", sample_time=0.01, **tx), name="tx")
    d.connect(src, t)
    rx = d.add(CanReceive(dbc_file=DBC, message="EngineData", signals="EngineSpeed", sample_time=0.01), name="rx")
    for k in range(3):
        d.connect((rx, k), d.add(Scope()))
    d.connect(d.add(CanBusSetup(bitrate=500_000.0, sample_time=0.1), name="load"), d.add(Scope()))
    return d


def test_signal_crosses_the_bus() -> None:
    r = simulate(_diagram(), 1.0, solver="rk4", step=0.001)
    # Sent at 0.48 s, on the bus for 0.25 ms, read by the receive task at 0.49 s, which outputs it from its next
    # sample (0.50 s), like a mailbox read; quantised to 0.25 rpm. (Sine frequency in rad/s.)
    rx = float(np.interp(0.505, r.t, np.ravel(r["rx"])))
    assert rx == pytest.approx(2000 + 1000 * np.sin(0.48), abs=0.25)
    assert r["rx:2"].max() <= 0.0101  # age stays below one period
    frame_time = frame_bits(0x100, bytes(8)) / 500_000
    assert r["load"][-1] == pytest.approx(10 * frame_time / 0.1, rel=0.1)  # 10 frames per 100 ms


def test_bus_off_shows_as_a_growing_age() -> None:
    r = simulate(_diagram(bus_off=True, fault_time=0.5), 1.0, solver="rk4", step=0.001)
    assert r["rx:2"][-1] == pytest.approx(0.5, abs=0.02)
    assert np.ptp(r["rx"][r.t > 0.52]) == 0.0  # the last value is held


def test_dropped_frames_and_delay() -> None:
    simulate(_diagram(drop=0.3), 1.0, solver="rk4", step=0.001)
    lost = sum(f.lost for f in bus("can0").trace)
    assert 15 <= lost <= 45
    simulate(_diagram(delay=0.003), 1.0, solver="rk4", step=0.001)
    assert min(bus("can0").latency(0x100)) == pytest.approx(0.003 + frame_bits(0x100, bytes(8)) / 500e3, abs=1e-4)


def test_on_change_sends_only_changes() -> None:
    d = Diagram()
    d.connect(d.add(Constant(value=1500.0)),
              d.add(CanTransmit(dbc_file=DBC, message="EngineData", signals="EngineSpeed", mode="on_change")))  # fmt: skip
    rx = d.add(CanReceive(dbc_file=DBC, message="EngineData", signals="EngineSpeed"), name="rx")
    for k in range(3):
        d.connect((rx, k), d.add(Scope()))
    r = simulate(d, 0.5, solver="rk4", step=0.01)
    assert len(bus("can0").trace) == 1
    assert r["rx"][-1] == 1500.0


def test_asc_and_blf_logs(tmp_path: Path) -> None:
    can = pytest.importorskip("can")
    simulate(_diagram(), 0.2, solver="rk4", step=0.001)
    b = bus("can0")
    asc = list(can.ASCReader(str(b.write_asc(tmp_path / "trace.asc"))))
    blf = list(can.BLFReader(str(b.write_blf(tmp_path / "trace.blf"))))
    assert len(asc) == len(blf) == len(b.trace) >= 19
    assert asc[3].arbitration_id == 0x100 and bytes(asc[3].data) == b.trace[3].data
    assert blf[3].timestamp == pytest.approx(b.trace[3].end, abs=1e-6)


def _e2e_run(frames: list[tuple[bytes, float]], max_delta: int = 2) -> list[int]:
    """Feed (bytes, new) samples to an E2E Check, returning the status of each."""
    from nervus.blocks import E2ECheck

    chk = E2ECheck(data_id=0x100, max_delta=max_delta)
    chk.configure([8, 1], [1, 1])
    x = chk.initial_discrete_state()
    out = []
    for data, new in frames:
        u = [np.array(list(data), dtype=float), np.array([new])]
        out.append(int(chk.outputs(0.0, u, np.zeros(0), x)[0][0]))
        x = chk.update(0.0, u, np.zeros(0), x)
    return out


def test_e2e_detects_faults() -> None:
    from nervus.blocks import E2EProtect
    from nervus.canbus import crc8_j1850

    assert crc8_j1850(b"123456789") ^ 0xFF == 0x4B  # the standard check value of CRC-8 SAE J1850
    prot = E2EProtect(data_id=0x100)
    prot.configure([8], [8])
    x = prot.initial_discrete_state()
    sent = []
    for k in range(20):
        u = [np.array([0, 0, k, 2 * k, 0, 0, 0, 7], dtype=float)]
        sent.append(bytes(int(v) for v in prot.outputs(0.0, u, np.zeros(0), x)[0]))
        x = prot.update(0.0, u, np.zeros(0), x)
    assert [b[1] & 0x0F for b in sent[:16]] == [*range(15), 0]  # the alive counter wraps after 14
    bad = bytearray(sent[3])
    bad[4] ^= 0x10
    stream = [(sent[0], 1), (sent[1], 1), (sent[1], 0), (sent[2], 1), (bytes(bad), 1), (sent[3], 1), (sent[3], 1),
              (sent[5], 1), (sent[9], 1)]  # fmt: skip
    assert _e2e_run(stream) == [0, 0, 1, 0, 2, 0, 3, 0, 4]
    assert _e2e_run([(sent[14], 1), (sent[15], 1)]) == [0, 0]  # across the wrap


def test_e2e_over_a_corrupting_bus() -> None:
    from nervus.blocks import CanPack, CanUnpack, E2ECheck, E2EProtect

    d = Diagram()
    src = d.add(Sine(amplitude=1000.0, bias=2000.0), name="rpm")
    pack = d.add(CanPack(dbc_file=DBC, message="EngineData", signals="EngineSpeed"), name="pack")
    prot = d.add(E2EProtect(data_id=0x100, crc_byte=6, counter_byte=7), name="protect")
    tx = d.add(CanTransmit(dbc_file=DBC, message="EngineData", payload="bytes", corrupt=0.2), name="tx")
    d.chain(src, d.add(ZeroOrderHold(sample_time=0.01)), pack, prot, tx)
    rx = d.add(CanReceive(dbc_file=DBC, message="EngineData", payload="bytes"), name="rx")
    chk = d.add(E2ECheck(data_id=0x100, crc_byte=6, counter_byte=7), name="check")
    d.connect((rx, 0), (chk, 0))
    d.connect((rx, 1), (chk, 1))
    d.connect((rx, 0), d.add(CanUnpack(dbc_file=DBC, message="EngineData", signals="EngineSpeed"), name="unpack"))
    for blk, n in ((chk, 2), (d.block("unpack"), 1), (rx, 3)):
        for k in range(n):
            d.connect((blk, k), d.add(Scope()))
    r = simulate(d, 2.0, solver="rk4", step=0.01)
    status = np.ravel(r["check"])
    # Status is evaluated at every 10 ms sample, one frame per sample: about 20 % of 200 frames are corrupted.
    assert 20 <= int(np.sum(status == 2)) <= 60
    # After two corrupted frames in a row the counter has jumped by 3 > max_delta: wrong sequence.
    assert 0 < int(np.sum(status == 4)) < int(np.sum(status == 2))
    valid = np.ravel(r["check:1"]) > 0.5
    rpm = np.ravel(r["unpack"])
    assert np.all((rpm[valid] > 999.0) & (rpm[valid] < 3001.0))  # valid frames carry plausible values


@pytest.mark.skipif(__import__("nervus.codegen.sil", fromlist=["x"]).find_compiler() is None, reason="no C compiler")
def test_e2e_codegen_bit_true(tmp_path: Path) -> None:
    from nervus.blocks import E2ECheck, E2EProtect, Inport, Outport, Sum
    from nervus.codegen.sil import back_to_back

    d = Diagram("e2e")
    frame = d.add(Inport(port=1, value=np.zeros(8)), name="payload")
    noise = d.add(Inport(port=2, value=np.zeros(8)), name="bit_errors")
    new = d.add(Inport(port=3), name="new")
    prot = d.add(E2EProtect(data_id=0x1A5, crc_byte=0, counter_byte=1, sample_time=0.01), name="protect")
    d.chain(frame, prot)
    bad = d.add(Sum(signs="++"), name="channel")
    d.connect(prot, (bad, 0))
    d.connect(noise, (bad, 1))
    chk = d.add(E2ECheck(data_id=0x1A5, crc_byte=0, counter_byte=1, sample_time=0.01), name="check")
    d.connect(bad, (chk, 0))
    d.connect(new, (chk, 1))
    d.connect(prot, d.add(Outport(port=1), name="protected"))
    d.connect((chk, 0), d.add(Outport(port=2), name="status"))
    d.connect((chk, 1), d.add(Outport(port=3), name="valid"))
    rng = np.random.default_rng(5)
    steps = 200
    errors = np.zeros((steps, 8))
    errors[rng.random(steps) < 0.1, 5] = 1.0  # a bit error in byte 5 (byte 5 is 0, so +1 stays a byte)
    inputs = {
        "payload": np.c_[np.zeros((steps, 2)), rng.integers(0, 256, (steps, 6))].astype(float),
        "bit_errors": errors,
        "new": (rng.random(steps) < 0.8).astype(float),
    }
    inputs["payload"][:, 5] = 0.0
    res = back_to_back(d, inputs, steps, tolerance=0.0, folder=tmp_path)
    assert res.passed, res.summary()


def test_rest_bus_and_gateway() -> None:
    from nervus.blocks import CanGateway, CanRestBus

    d = Diagram()
    d.add(CanRestBus(dbc_file=DBC, nodes="GATEWAY", values="VehicleSpeed=50, AccelPedal=20"), name="rest")
    d.add(CanGateway(from_bus="can0", to_bus="body", ids="0x200", sample_time=0.005), name="gw")
    rx = d.add(CanReceive(dbc_file=DBC, message="VehicleData", signals="VehicleSpeed", bus="body"), name="rx")
    for k in range(3):
        d.connect((rx, k), d.add(Scope()))
    r = simulate(d, 0.2, solver="rk4", step=0.001)
    assert r["rx"][-1] == 50.0
    powertrain, body = bus("can0"), bus("body")
    assert {f.can_id for f in powertrain.trace} == {0x200}  # only the GATEWAY node's message
    assert len(powertrain.trace) == 10  # every 20 ms (GenMsgCycleTime) in 0.2 s
    assert len(body.trace) == 10 and all(f.sender == "gateway can0" for f in body.trace)
    lat = [b.end - a.end for a, b in zip(powertrain.trace, body.trace, strict=False)]
    assert min(lat) > 0 and max(lat) < 0.005 + 0.0003  # one gateway period + one frame


def test_real_hardware_through_python_can() -> None:
    can = pytest.importorskip("can")
    d = _diagram()
    d.block("load").set_param("interface", "virtual")
    d.block("load").set_param("channel", "nervus_test")
    other = can.Bus(interface="virtual", channel="nervus_test")  # "another ECU" on the same wire
    try:
        simulate(d, 0.05, solver="rk4", step=0.001)
        got = []
        while (m := other.recv(timeout=0.0)) is not None:
            got.append(m)
        assert len(got) == 5 and all(m.arbitration_id == 0x100 for m in got)
    finally:
        other.shutdown()
        bus("can0").disconnect_hardware()
