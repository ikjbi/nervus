"""Exchanging models with FMI: export the throttle ECU as an FMU, run it elsewhere, and bring an FMU into a model.

1. The ECU subsystem of ``throttle_ecu.nervus`` is exported as ``examples/generated/ECU.fmu``: an FMI 2.0
   co-simulation FMU with the generated C code, compiled for this computer, and its sources.
2. The FMU runs without Nervus, in fmpy (as it would in Simulink's FMU block, Dymola, CANoe, ...).
3. ``fmi_plant.nervus`` is the throttle plant with the FMU in place of the ECU subsystem: the **FMU** block.

Run with ``uv run python examples/fmi_exchange.py`` (needs ``uv sync --extra fmi`` and a C compiler).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

from nervus import Diagram, SimResult, save, simulate
from nervus.blocks import FMU

HERE = Path(__file__).parent
FMU_PATH = HERE / "generated" / "ECU.fmu"


def _throttle():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("throttle_ecu", HERE / "throttle_ecu.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def export() -> Path:
    from nervus.codegen.fmu import export_fmu

    return export_fmu(_throttle().build().block("ECU"), FMU_PATH, description="Throttle position controller")


def run_in_fmpy(fmu: Path) -> np.ndarray:
    """The FMU on its own: a step of the target angle from 5° to 60° at 0.2 s, the measured angle held at 5°."""
    from fmpy import simulate_fmu

    t = np.arange(0.0, 0.5, 0.01)
    sig = np.array([(x, 60.0 if x >= 0.2 else 5.0, 5.0) for x in t],
                   dtype=[("time", float), ("target_deg", float), ("tps_deg", float)])  # fmt: skip
    return simulate_fmu(str(fmu), stop_time=0.49, output_interval=0.01, input=sig)  # type: ignore[no-any-return]


def build_plant_with_fmu() -> Diagram:
    """The throttle model with the ECU subsystem replaced by the FMU block (same ports)."""
    d = _throttle().build()
    d.name = "fmi_plant"
    d.source_path = str(HERE / "fmi_plant.nervus")
    ecu = d.block("ECU")
    block = d.add(FMU(fmu_file="generated/ECU.fmu"), name="ECU_fmu")
    for c in list(d.connections):
        if c.dst is ecu:
            d.disconnect(c)
            d.connect((c.src, c.src_port), (block, c.dst_port))
        elif c.src is ecu:
            d.disconnect(c)
            d.connect((block, c.src_port), (c.dst, c.dst_port))
    block.meta["position"] = list(ecu.meta.get("position", [0.0, 0.0]))
    d.remove(ecu)
    d.tests = [t for t in d.tests if t.name == "tip-in, baseline calibration"]
    return d


def main() -> dict[str, SimResult]:
    fmu = export()
    print(f"exported {fmu.name} ({fmu.stat().st_size // 1024} kB)")
    r = run_in_fmpy(fmu)
    print(f"in fmpy: duty cycle {r['duty_pct'][19]:.0f} % before the step, {r['duty_pct'][21]:.0f} % after it")
    d = build_plant_with_fmu()
    save(d, HERE / "fmi_plant.nervus")
    with_fmu, original = simulate(d), simulate(_throttle().build())
    lag = np.max(np.abs(np.interp(original.t, with_fmu.t, np.ravel(with_fmu["plate_angle"]))
                        - np.ravel(original["plate_angle"])))  # fmt: skip
    print(f"plate angle with the FMU: peak {np.max(with_fmu['plate_angle']):.1f}° (subsystem: "
          f"{np.max(original['plate_angle']):.1f}°), largest difference {lag:.1f}° during the tip-in")  # fmt: skip
    return {"fmu": with_fmu, "subsystem": original}


if __name__ == "__main__":
    main()
