"""A small vehicle network: two CAN buses, a gateway, E2E protection and a lost ECU.

* **Powertrain CAN** (500 kbit/s): the engine ECU (ECM) sends ``EngineData`` every 10 ms, protected with an
  E2E CRC and alive counter (bytes 6 and 7). The ECUs that are not modelled (here the ``GATEWAY`` node's
  ``VehicleData``) come from a **rest-bus** simulation of the DBC file.
* **Gateway**: routes both messages to the **body CAN** (125 kbit/s).
* **Instrument cluster** on the body CAN: receives ``EngineData``, checks it with **E2E Check** and shows the
  engine speed. A frame that fails the check is ignored (the needle holds its last good value). When no
  valid frame has arrived for 100 ms, a Diagnostic Monitor sets **U0100** ("lost communication with the
  ECM") and the needle drops to 0.

The faults (fault injection on the ECM's CAN Transmit): from 1 s, 20 % of the frames get a flipped bit (a
fault behind the CAN CRC, e.g. in the gateway's memory); at 3 s the ECM goes **bus-off**.

Run with ``uv run python examples/can_network.py``; after a run in the app, Tools ▸ CAN Bus Trace shows the
frames.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import (
    Bias,
    CanBusSetup,
    CanGateway,
    CanPack,
    CanReceive,
    CanRestBus,
    CanTransmit,
    CanUnpack,
    CompareToConstant,
    Constant,
    DiagnosticMonitor,
    E2ECheck,
    E2EProtect,
    Inport,
    Outport,
    Scope,
    Sine,
    Subsystem,
    Switch,
    UnitDelay,
    ZeroOrderHold,
)
from nervus.core import Check, TestCase, Variable

HERE = Path(__file__).parent
DBC = "data/vehicle.dbc"  # relative to the model file
TS = 0.01
E2E = {"data_id": 0x100, "crc_byte": 6, "counter_byte": 7}


def _diagram(name: str) -> Diagram:
    """A diagram that resolves the relative DBC path like the saved model file will."""
    d = Diagram(name)
    d.source_path = str(HERE / "can_network.nervus")
    return d


def _place(d: Diagram, positions: dict[str, tuple[int, int]]) -> None:
    for name, (x, y) in positions.items():
        d.block(name).meta["position"] = [float(x), float(y)]


def build_ecm() -> Subsystem:
    """Engine ECU: packs the engine speed and coolant temperature, protects the frame, sends it every 10 ms."""
    s = _diagram("ecm")
    rpm = s.add(Inport(port=1), name="engine_rpm")
    temp = s.add(Inport(port=2), name="coolant_temp")
    pack = s.add(CanPack(dbc_file=DBC, message="EngineData", signals="EngineSpeed, CoolantTemp"), name="pack")
    prot = s.add(E2EProtect(**E2E), name="e2e_protect")
    tx = s.add(CanTransmit(dbc_file=DBC, message="EngineData", bus="powertrain", payload="bytes", node="ECM",
                           corrupt="corrupt_rate", fault_time="corrupt_from", bus_off="ecm_bus_off",
                           sample_time=TS), name="can_tx")  # fmt: skip
    s.connect(rpm, (pack, 0))
    s.connect(temp, (pack, 1))
    s.chain(pack, prot, tx)
    _place(s, {"engine_rpm": (0, 0), "coolant_temp": (0, 80), "pack": (160, 30), "e2e_protect": (320, 30),
               "can_tx": (480, 30)})  # fmt: skip
    return Subsystem(system=s, sample_time=TS)


def build_cluster() -> Subsystem:
    """Instrument cluster: E2E check, hold the last good value; after 100 ms without a valid frame the needle
    drops to 0 and the U0100 monitor fails."""
    s = _diagram("cluster")
    rx = s.add(CanReceive(dbc_file=DBC, message="EngineData", bus="body", payload="bytes", sample_time=TS),
               name="can_rx")  # fmt: skip
    chk = s.add(E2ECheck(**E2E, sample_time=TS), name="e2e_check")
    unpack = s.add(CanUnpack(dbc_file=DBC, message="EngineData", signals="EngineSpeed"), name="unpack")
    hold = s.add(Switch(threshold=0.5), name="use_if_valid")
    last = s.add(UnitDelay(initial=0.0, sample_time=TS), name="last_good")
    # Time since the last valid frame: 0 on a valid frame, else the previous value + one period.
    since = s.add(Switch(threshold=0.5), name="since_valid")
    since_prev = s.add(UnitDelay(initial=0.0, sample_time=TS), name="since_prev")
    plus = s.add(Bias(bias=TS), name="plus_period")
    zero = s.add(Constant(value=0.0), name="zero")
    lost = s.add(CompareToConstant(operator=">=", constant="comm_timeout"), name="timeout")
    dem = s.add(DiagnosticMonitor(dtc="U0100", threshold=1.0, sample_time=TS), name="U0100")
    needle = s.add(Switch(threshold=0.5), name="needle")
    s.connect((rx, 0), (chk, 0))
    s.connect((rx, 1), (chk, 1))
    s.connect((rx, 0), unpack)
    s.connect(unpack, (hold, 0))
    s.connect((chk, 1), (hold, 1))
    s.connect(last, (hold, 2))
    s.chain(hold, last)
    s.connect(zero, (since, 0))
    s.connect((chk, 1), (since, 1))
    s.chain(since_prev, plus)
    s.connect(plus, (since, 2))
    s.chain(since, since_prev)
    s.chain(since, lost, dem)
    s.connect(zero, (needle, 0))
    s.connect(lost, (needle, 1))
    s.connect(hold, (needle, 2))
    s.connect(needle, s.add(Outport(port=1), name="rpm_display"))
    s.connect((chk, 0), s.add(Outport(port=2), name="e2e_status"))
    s.connect(lost, s.add(Outport(port=3), name="comm_lost"))
    s.connect((dem, 1), s.add(Outport(port=4), name="u0100_pending"))
    _place(s, {"can_rx": (0, 40), "e2e_check": (180, 0), "unpack": (180, 120), "use_if_valid": (360, 60),
               "last_good": (360, 200), "zero": (180, -120), "since_valid": (360, -100), "since_prev": (360, -220),
               "plus_period": (220, -220), "timeout": (520, -100), "U0100": (680, -180), "needle": (680, 60),
               "rpm_display": (840, 60), "e2e_status": (360, -300), "comm_lost": (840, -60),
               "u0100_pending": (840, -180)})  # fmt: skip
    return Subsystem(system=s, sample_time=TS)


def build() -> Diagram:
    d = _diagram("can_network")
    d.settings.t_final = 4.0
    d.settings.solver = "rk4"
    d.settings.step = 0.001
    ws = d.workspace
    ws.add(Variable("corrupt_rate", 0.2, "Share of ECM frames with a flipped bit (fault injection)", "-"))
    ws.add(Variable("corrupt_from", 1.0, "When the ECM faults start", "s"))
    ws.add(Variable("comm_timeout", 0.1, "No valid EngineData for this long: communication lost", "s"))
    ws.add(Variable("ecm_bus_off", 0.0, "1: the ECM goes bus-off at corrupt_from", "-"))
    rpm = d.add(Sine(amplitude=800.0, bias=2500.0, frequency=3.0), name="engine_rpm")
    temp = d.add(Sine(amplitude=0.0, bias=90.0), name="coolant_temp")
    ecm = d.add(build_ecm(), name="ECM")
    d.connect(d.add(ZeroOrderHold(sample_time=TS), name="rpm_sensor"), (ecm, 0))
    d.connect(rpm, d.block("rpm_sensor"))
    d.connect(temp, (ecm, 1))
    d.add(CanRestBus(dbc_file=DBC, nodes="GATEWAY", values="VehicleSpeed=50", bus="powertrain"), name="rest_bus")
    d.add(CanGateway(from_bus="powertrain", to_bus="body", ids="0x100, 0x200", sample_time=0.001), name="gateway")
    pt = d.add(CanBusSetup(bus="powertrain", bitrate=500_000.0), name="powertrain_can")
    body = d.add(CanBusSetup(bus="body", bitrate=125_000.0), name="body_can")
    cluster = d.add(build_cluster(), name="cluster")
    scope = d.add(Scope(num_inputs=2), name="rpm_scope")
    d.connect(rpm, (scope, 0))
    d.connect((cluster, 0), (scope, 1))
    outs = (((cluster, 0), "rpm_display"), ((cluster, 1), "e2e_status"), ((cluster, 2), "comm_lost"),
            ((cluster, 3), "u0100"),
            ((pt, 0), "powertrain_load"), ((body, 0), "body_load"), ((rpm, 0), "rpm"))  # fmt: skip
    for k, (src, name) in enumerate(outs):
        d.connect(src, d.add(Outport(port=k + 1), name=name))
    _place(d, {"engine_rpm": (0, 0), "rpm_sensor": (140, 0), "coolant_temp": (0, 90), "ECM": (300, 20),
               "rest_bus": (300, 160), "gateway": (500, 90), "powertrain_can": (500, 220), "body_can": (680, 220),
               "cluster": (680, 20), "rpm_scope": (900, -80), "rpm_display": (900, 0), "e2e_status": (900, 60),
               "comm_lost": (900, 120), "u0100": (900, 180), "powertrain_load": (680, 320), "body_load": (900, 320),
               "rpm": (140, -90)})  # fmt: skip
    d.tests = [
        TestCase(
            "the cluster follows the engine",
            "Without faults the needle is at most 2 samples (+ the bus and gateway latency) behind the engine",
            stop_time=1.0,
            checks=[Check("bounds", "comm_lost", {"lower": 0.0, "upper": 0.0})],
        ),
        TestCase(
            "corrupted frames are rejected",
            "With 20 % corrupted frames the E2E check rejects them; the needle never shows a corrupted value",
            stop_time=3.0,
            checks=[
                Check("bounds", "rpm_display", {"lower": 1650.0, "upper": 3350.0, "t_from": 0.1}),
                Check("bounds", "comm_lost", {"lower": 0.0, "upper": 0.0}),
            ],
        ),
        TestCase(
            "bus-off: U0100 and the needle drops",
            "The ECM goes bus-off at 3 s: after 100 ms without a valid frame the needle drops to 0 and U0100 is pending",
            stop_time=4.0,
            parameters={"ecm_bus_off": 1.0, "corrupt_rate": 0.0, "corrupt_from": 3.0},
            checks=[
                Check("bounds", "comm_lost", {"lower": 0.0, "upper": 0.0, "t_to": 3.09}),
                Check("bounds", "u0100", {"lower": 1.0, "upper": 1.0, "t_from": 3.2}),
                Check("bounds", "rpm_display", {"lower": 0.0, "upper": 0.0, "t_from": 3.2}),
            ],
        ),
    ]
    return d


def main() -> SimResult:
    from nervus.canbus import bus
    from nervus.testing import run_tests

    d = build()
    save(d, HERE / "can_network.nervus")
    for r in run_tests(d):
        print(r.summary())
    res = simulate(d)
    body = bus("body")
    lat = np.array(body.latency(0x100))
    print(f"powertrain load {100 * np.mean(res['powertrain_load'][res.t > 0.2]):.1f} %, "
          f"body load {100 * np.mean(res['body_load'][res.t > 0.2]):.1f} %")  # fmt: skip
    print(f"gateway: {len(body.trace)} frames routed, latency on the body bus {1000 * lat.mean():.2f} ms")
    status = np.ravel(res["e2e_status"])
    print(f"E2E: {np.sum(status == 2)} wrong CRC, {np.sum(status == 4)} wrong sequence")
    return res


if __name__ == "__main__":
    main()
