"""Diagnostic monitors: debouncing, pending/confirmed DTCs over operation cycles, MIL, readiness, clear."""

import numpy as np
import pytest

from nervus import Diagram, simulate
from nervus.blocks import DiagnosticMonitor, Inport, Outport
from nervus.blocks.diagnostics import CONFIRMED, PENDING, WARNING_INDICATOR
from nervus.core.errors import ParameterError

TS = 0.01


def _model(**params) -> Diagram:  # type: ignore[no-untyped-def]
    d = Diagram("dem")
    mon = d.add(DiagnosticMonitor(dtc="P0301", cycle_input=True, clear_input=True, sample_time=TS, **params), name="m")
    for k, name in enumerate(("fault", "cycle", "clear")):
        d.connect(d.add(Inport(port=k + 1), name=name), (mon, k))
    for k, name in enumerate(("mil", "pending", "confirmed", "ready", "status")):
        d.connect((mon, k), d.add(Outport(port=k + 1), name=name))
    return d


def _run(d: Diagram, fault, cycle, clear=None):  # type: ignore[no-untyped-def]
    n = len(fault)
    t = np.arange(n) * TS
    clear = np.zeros(n) if clear is None else clear
    inputs = {"fault": (t, np.asarray(fault, float)), "cycle": (t, np.asarray(cycle, float)), "clear": (t, clear)}
    for v in inputs.values():
        v[1].shape = (n, 1)
    return simulate(d, t[-1], solver="rk4", step=TS, inputs={k: (v[0], v[1]) for k, v in inputs.items()})


def _cycles(n_per_cycle: int, faults: list[bool]):  # type: ignore[no-untyped-def]
    """Operation cycles of n samples each (the cycle input high for the first sample, after one low)."""
    fault, cycle = [], []
    for f in faults:
        cyc = np.zeros(n_per_cycle)
        cyc[1:3] = 1.0  # key on
        fault += [1.0 if f else 0.0] * n_per_cycle
        cycle += cyc.tolist()
    return fault, cycle


def test_glitch_is_debounced() -> None:
    d = _model(threshold=10.0)
    fault = [0.0] * 5 + [1.0] * 5 + [0.0] * 40  # 5 samples of fault: below the threshold of 10
    r = _run(d, fault, [0.0] * 50)
    assert r["pending"].max() == 0.0 and r["mil"].max() == 0.0
    assert r["ready"][-1] == 1.0  # the test passed: the monitor has completed


def test_two_trip_detection_mil_and_healing() -> None:
    d = _model(threshold=5.0, confirm_cycles=2, heal_cycles=3)
    faults = [True, True, False, False, False, False]
    fault, cycle = _cycles(30, faults)
    r = _run(d, fault, cycle)
    status = r["status"].astype(int)
    per_cycle = [status[30 * k + 25] for k in range(len(faults))]  # late in each cycle
    assert per_cycle[0] & PENDING and not per_cycle[0] & CONFIRMED  # first trip: pending only
    assert per_cycle[1] & CONFIRMED and per_cycle[1] & WARNING_INDICATOR  # second trip: confirmed, MIL on
    assert per_cycle[2] & WARNING_INDICATOR  # passing cycles: the MIL stays on for 3 cycles
    assert per_cycle[4] & WARNING_INDICATOR and not per_cycle[5] & WARNING_INDICATOR  # off after 3 passed cycles
    assert per_cycle[5] & CONFIRMED and not per_cycle[5] & PENDING  # still stored for the workshop


def test_one_failed_cycle_is_forgotten() -> None:
    d = _model(threshold=5.0)
    fault, cycle = _cycles(30, [True, False, True, False])  # never two in a row
    r = _run(d, fault, cycle)
    assert r["confirmed"].max() == 0.0 and r["mil"].max() == 0.0
    assert r["pending"][30 * 1 + 25] == 1.0  # still pending during the passing cycle ...
    assert r["pending"][30 * 2 + 2] == 0.0  # ... cleared when it ended without failure


def test_clear_resets_code_and_readiness() -> None:
    d = _model(threshold=3.0, confirm_cycles=1)
    fault = [1.0] * 20 + [0.0] * 30
    clear = np.zeros(50)
    clear[30:32] = 1.0  # mode 04
    r = _run(d, fault, [0.0] * 50, clear)
    assert r["mil"][25] == 1.0 and r["ready"][25] == 1.0
    assert r["mil"][-1] == 0.0 and r["confirmed"][-1] == 0.0
    assert r["ready"][31] == 0.0  # readiness "not complete" right after the clear
    assert r["ready"][-1] == 1.0  # ... until the test has passed again


def test_invalid_dtc() -> None:
    with pytest.raises(ParameterError, match="trouble code"):
        DiagnosticMonitor(dtc="X123")
    assert DiagnosticMonitor(dtc="p0171").params["dtc"] == "P0171"


def test_monitor_codegen(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from nervus.codegen.sil import back_to_back, find_compiler

    if find_compiler() is None:
        pytest.skip("no C compiler")
    d = _model(threshold=4.0, fail_step=2.0, pass_step=0.5, confirm_cycles=2, heal_cycles=2)
    fault, cycle = _cycles(25, [True, True, False, True, False, False, False])
    rng = np.random.default_rng(3)
    noisy = np.where(rng.random(len(fault)) < 0.15, 1.0 - np.asarray(fault), fault)  # glitches both ways
    clear = np.zeros(len(fault))
    clear[150:152] = 1.0
    res = back_to_back(d, {"fault": noisy, "cycle": cycle, "clear": clear}, len(fault), tolerance=0.0, folder=tmp_path)
    assert res.passed, res.summary()
    assert res.python["mil"].max() == 1.0  # the scenario exercises the MIL
