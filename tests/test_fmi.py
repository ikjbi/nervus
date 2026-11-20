"""FMI 2.0: export a model as an FMU, and run FMUs as blocks."""

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("fmpy")
from fmpy import read_model_description, simulate_fmu
from fmpy.validation import validate_fmu

from nervus import simulate
from nervus.blocks import FMU
from nervus.codegen.sil import find_compiler

EXAMPLES = Path(__file__).parent.parent / "examples"
pytestmark = pytest.mark.skipif(find_compiler() is None, reason="no C compiler")


def _throttle():  # type: ignore[no-untyped-def]
    import importlib.util

    spec = importlib.util.spec_from_file_location("throttle_ecu", EXAMPLES / "throttle_ecu.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_export_is_a_valid_fmu(tmp_path: Path) -> None:
    from nervus.codegen.fmu import export_fmu

    d = _throttle().build()
    fmu = export_fmu(d.block("ECU"), tmp_path / "ECU")
    assert fmu.suffix == ".fmu" and validate_fmu(str(fmu)) == []
    md = read_model_description(str(fmu))
    kinds = {v.name: v.causality for v in md.modelVariables}
    assert kinds["target_deg"] == "input" and kinds["duty_pct"] == "output" and kinds["Kp"] == "parameter"
    assert float(md.defaultExperiment.stepSize) == 0.01
    # fmpy runs it: a step of the target saturates the duty cycle at 100 %.
    t = np.arange(0, 1.0, 0.01)
    sig = np.array([(x, 60.0 if x >= 0.2 else 5.0, 5.0) for x in t],
                   dtype=[("time", float), ("target_deg", float), ("tps_deg", float)])  # fmt: skip
    r = simulate_fmu(str(fmu), stop_time=0.99, output_interval=0.01, input=sig, start_values={"Kp": 3.0})
    assert np.max(r["duty_pct"]) == 100.0 and r["duty_pct"][0] == 0.0


def test_fmu_block_replaces_the_subsystem(tmp_path: Path) -> None:
    """The ECU exported as an FMU and put back into the plant model: the same controller, but its output comes one
    communication step (10 ms) later, as in every co-simulation. During the fast tip-in the angle lags by up to
    13°; the peak and the steady state are the same."""
    from nervus.codegen.fmu import export_fmu

    m = _throttle()
    original = m.build()
    ref = simulate(original)
    fmu_path = export_fmu(original.block("ECU"), tmp_path / "ECU.fmu")
    d = m.build()
    ecu = d.block("ECU")
    block = d.add(FMU(fmu_file=str(fmu_path)), name="ecu_fmu")
    assert block.input_names() == ["target_deg", "tps_deg"] and block.period() == pytest.approx(0.01)
    for c in list(d.connections):
        if c.dst is ecu:
            d.disconnect(c)
            d.connect((c.src, c.src_port), (block, c.dst_port))
        elif c.src is ecu:
            d.disconnect(c)
            d.connect((block, c.src_port), (c.dst, c.dst_port))
    d.remove(ecu)
    res = simulate(d)
    a, b = np.ravel(ref["plate_angle"]), np.interp(ref.t, res.t, np.ravel(res["plate_angle"]))
    assert np.max(np.abs(a - b)) < 15.0 and np.max(b) == pytest.approx(np.max(a), abs=0.5)
    assert b[-1] == pytest.approx(a[-1], abs=0.05)  # the same steady state
    # Parameters set from the block: a higher gain gives a faster rise.
    block.set_param("parameters", "Kp = 3.0")
    fast = simulate(d)
    k = np.searchsorted(fast.t, 0.25)
    assert np.ravel(fast["plate_angle"])[k] > np.ravel(res["plate_angle"])[np.searchsorted(res.t, 0.25)]
    with pytest.raises(Exception, match="no parameter"):
        block.set_param("parameters", "nonsense = 1")
        block.validate_params()
