"""Live calibration over XCP on CAN: tune the cruise control while the car drives.

The cruise control of the first tutorial, with an **XCP Slave** block: a calibration tool (INCA, CANape, or
``examples/xcp_tool.py``) can read the speed and the engine force, and change two calibration values while the
simulation runs:

* ``set_speed_cal``: the set speed [km/h] (starts at 100),
* ``gain_trim``: a factor on the controller gain (starts at 1; it scales the speed error before the PI controller,
  so it scales both the P and the I term).

The CAN bus is python-can's ``udp_multicast`` interface: a virtual CAN bus shared by all programs on this
computer. The model runs in real time, so a tool in another terminal can connect (``examples/xcp_tool.py``); with
a real CAN adapter, set the interface of the **can** block instead.

Run ``uv run python examples/xcp_calibration.py`` for a scripted session (model and tool in one process, at 8×
real time), or follow the tutorial to run the model and the tool separately.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import CanBusSetup, Clock, Outport, Product, XcpSlave
from nervus.core import Variable

HERE = Path(__file__).parent
CHANNEL = "239.74.163.2"  # a UDP multicast group: a virtual CAN bus shared by programs on this computer


def build(interface: str = "udp_multicast") -> Diagram:
    import importlib.util

    spec = importlib.util.spec_from_file_location("cruise_control", HERE / "cruise_control.py")
    assert spec is not None and spec.loader is not None
    cruise = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cruise)
    d = cruise.build()
    d.name = "xcp_calibration"
    d.settings.t_final = 60.0
    d.settings.pacing = 1.0  # real time, so a calibration tool can follow
    d.tests = []
    ws = d.workspace
    ws.add(Variable("set_speed_cal", 100.0, "Set speed (calibrated over XCP)", "km/h", 0.0, 180.0))
    ws.add(Variable("gain_trim", 1.0, "Factor on the controller gain (calibrated over XCP)", "-", 0.0, 10.0))
    # The XCP slave: measurements in, calibration values out.
    xcp = d.add(XcpSlave(measurements="speed, force, time", calibrations="set_speed_cal, gain_trim",
                         sample_time=0.01), name="xcp")  # fmt: skip
    d.add(CanBusSetup(interface=interface, channel=CHANNEL), name="can")
    # The set speed now comes from the calibration value, switched on at 1 s like the driver's button.
    step = d.block("set_speed")
    step.set_param("final", 1.0)
    target = d.add(Product(ops="**"), name="set_speed_kmh")
    for c in [c for c in d.connections if c.src is step]:
        d.disconnect(c)
        d.connect(target, (c.dst, c.dst_port))
    d.connect(step, (target, 0))
    d.connect((xcp, 0), (target, 1))
    # The gain trim scales the error before the controller.
    err, ctrl = d.block("error"), d.block("cruise_control")
    trimmed = d.add(Product(ops="**"), name="trimmed_error")
    d.disconnect(next(c for c in d.connections if c.src is err and c.dst is ctrl))
    d.connect(err, (trimmed, 0))
    d.connect((xcp, 1), (trimmed, 1))
    d.connect(trimmed, ctrl)
    d.connect(d.block("speed"), (xcp, 0))
    d.connect(ctrl, (xcp, 1))
    d.connect(d.add(Clock(), name="ecu_time"), (xcp, 2))
    d.connect(d.block("speed"), d.add(Outport(port=1), name="speed_kmh"))
    d.connect((xcp, 0), d.add(Outport(port=2), name="set_speed_used"))
    d.connect((xcp, 1), d.add(Outport(port=3), name="gain_trim_used"))
    for name, (x, y) in {"xcp": (590, 250), "can": (900, 250), "set_speed_kmh": (100, 80),
                         "trimmed_error": (220, 80), "speed_kmh": (1050, 10), "set_speed_used": (760, 330),
                         "gain_trim_used": (760, 400), "ecu_time": (420, 330)}.items():  # fmt: skip
        d.block(name).meta["position"] = [float(x), float(y)]
    return d


def session(a2l: Path, log: list[tuple[float, str, float]], deadline: float = 120.0, interface: str = "udp_multicast"
            ) -> None:  # fmt: skip
    """A scripted calibration session, as an engineer would do it with a tool. It follows the ECU's clock
    (the ``time`` measurement): at 20 s it raises the set speed, at 40 s it quadruples the controller gain."""
    import can

    from nervus.xcp import CanTransport, XcpError, XcpMaster

    bus = can.Bus(interface=interface, channel=CHANNEL, **({"fd": False} if interface == "udp_multicast" else {}))
    actions = [(20.0, "set_speed_cal", 120.0), (35.0, "gain_trim", 3.0), (40.0, "set_speed_cal", 100.0)]
    end = time.monotonic() + deadline
    try:
        tool = XcpMaster(CanTransport(bus), a2l=a2l, timeout=0.5)
        while time.monotonic() < end:
            try:
                tool.connect()
                break
            except XcpError:  # the model is not running yet
                time.sleep(0.1)
        while time.monotonic() < end:
            t = float(tool.read("time"))  # type: ignore[arg-type]
            log.append((t, "speed", float(tool.read("speed"))))  # type: ignore[arg-type]
            while actions and t >= actions[0][0]:
                _, name, value = actions.pop(0)
                tool.write(name, value)
                log.append((t, name, value))
            if t >= 59.0:
                break
            time.sleep(0.05)
        tool.disconnect()
    finally:
        bus.shutdown()


def main(speedup: float = 8.0, interface: str = "udp_multicast") -> SimResult:
    d = build(interface)
    save(d, HERE / "xcp_calibration.nervus")
    simulate(d, 0.0)  # compile once, so the XCP block knows its namespace
    a2l = d.block("xcp").write_a2l(HERE / "xcp_calibration.a2l", name="cruise")  # type: ignore[attr-defined]
    d.settings.pacing = speedup
    log: list[tuple[float, str, float]] = []
    tool = threading.Thread(target=session, args=(a2l, log, 120.0, interface))
    tool.start()
    try:
        res = simulate(d)
    finally:
        tool.join(10)
        from nervus.canbus import bus

        bus("can0").disconnect_hardware()
    for t, what, value in log:
        if what != "speed":
            print(f"t = {t:4.1f} s: the tool writes {what} = {value:g}")
    v = np.ravel(res["speed_kmh"])
    print(f"speed read by the tool: {len([x for x in log if x[1] == 'speed'])} times; final speed {v[-1]:.1f} km/h")
    return res


if __name__ == "__main__":
    main()
