"""Electric vehicle range on the WLTP cycle: drivetrain losses, regenerative braking and the winter heater.

The car of the drive-cycle tutorial, now electric: 1800 kg (the battery is heavy), 150 kW, driven over the
official WLTC class 3b cycle (30 minutes, 23.3 km). The **energy chain** from the wheels back to the battery:

* driving: the battery delivers the wheel power divided by the drivetrain efficiency (motor, inverter, gearbox:
  ``eta_drive`` = 0.88);
* braking: the motor works as a generator; ``regen_share`` of the braking power is recovered (the rest goes to the
  friction brakes) with ``eta_regen`` = 0.75 (back through gearbox, motor and inverter);
* auxiliaries: 0.3 kW for the ECUs, pumps and lights, plus the cabin heater in winter (``P_heater``).

The battery holds 60 kWh usable. The result is the consumption in kWh/100 km and the range.

Run with ``uv run python examples/ev_range.py``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import Gain, Integrator, Outport, PythonFunction
from nervus.core import Variable

HERE = Path(__file__).parent

BATTERY = '''def f(t, wheel_power):
    """Battery power [W] for a wheel power [W]: losses when driving, partial recovery when braking, and the
    auxiliaries. p = [eta_drive, eta_regen, regen_share, P_aux, P_heater]"""
    if wheel_power >= 0.0:
        drive = wheel_power / p[0]
    else:
        drive = wheel_power * p[1] * p[2]
    return drive + p[3] + p[4]
'''

CONSTANTS = {
    "eta_drive": (0.88, "-", "Battery to wheel efficiency (inverter, motor, gearbox)"),
    "eta_regen": (0.75, "-", "Wheel to battery efficiency when recovering braking energy"),
    "regen_share": (1.0, "-", "Share of the braking power recovered (0: all friction brakes)"),
    "P_aux": (300.0, "W", "ECUs, pumps, fans, lights"),
    "P_heater": (0.0, "W", "Cabin heater (about 3000 W in winter, a heat pump about 1200 W)"),
    "E_pack": (60.0, "kWh", "Usable battery energy"),
}


def _drive_cycle():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("drive_cycle", HERE / "drive_cycle.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build() -> Diagram:
    d = _drive_cycle().build("wltc3b")
    d.name = "ev_range"
    ws = d.workspace
    ws["m"] = 1800.0
    ws["P_max"] = 150e3
    ws["F_max"] = 6000.0
    for name, (value, unit, desc) in CONSTANTS.items():
        ws.add(Variable(name, value, desc, unit))
    vehicle = d.block("vehicle")
    batt = d.add(PythonFunction(code=BATTERY, num_inputs=1,
                                parameters="[eta_drive, eta_regen, regen_share, P_aux, P_heater]"),
                 name="battery_power_W")  # fmt: skip
    energy = d.add(Integrator(), name="battery_energy_J")
    kwh = d.add(Gain(gain=1 / 3.6e6), name="battery_kWh")
    d.connect(vehicle.out_port(3), batt)
    d.chain(batt, energy, kwh)
    d.connect(kwh, d.add(Outport(port=1), name="energy_kwh"))
    d.connect(vehicle.out_port(1), d.add(Outport(port=2), name="distance_m"))
    d.connect(batt, d.add(Outport(port=3), name="battery_W"))
    for name, (x, y) in {"battery_power_W": (820, 420), "battery_energy_J": (960, 420), "battery_kWh": (1100, 420),
                         "energy_kwh": (1240, 420), "distance_m": (1240, 500), "battery_W": (960, 520)}.items():  # fmt: skip
        d.block(name).meta["position"] = [float(x), float(y)]
    return d


def consumption(res: SimResult, d: Diagram) -> dict[str, float]:
    km = float(np.ravel(res["distance_m"])[-1]) / 1000
    kwh = float(np.ravel(res["energy_kwh"])[-1])
    per100 = kwh / km * 100
    return {"km": km, "kwh": kwh, "kwh_per_100km": per100, "range_km": d.workspace["E_pack"] / per100 * 100}


def main() -> dict[str, SimResult]:
    d = build()
    save(d, HERE / "ev_range.nervus")
    cases = {"summer": {}, "no regeneration": {"regen_share": 0.0}, "winter, heater": {"P_heater": 3000.0},
             "winter, heat pump": {"P_heater": 1200.0}}  # fmt: skip
    out = {}
    for label, params in cases.items():
        res = simulate(d, params=params)
        c = consumption(res, d)
        out[label] = res
        print(f"{label:18s} {c['kwh_per_100km']:5.1f} kWh/100 km, range {c['range_km']:4.0f} km")
    return out


if __name__ == "__main__":
    main()
