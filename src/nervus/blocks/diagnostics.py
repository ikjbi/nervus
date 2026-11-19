"""On-board diagnostics in the model: fault debouncing, trouble codes, the MIL lamp and readiness."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from nervus.blocks.registry import register
from nervus.core.block import Block, Width
from nervus.core.errors import ParameterError
from nervus.core.params import Param, ParamKind
from nervus.core.types import Array

CATEGORY = "Diagnostics"

# UDS (ISO 14229) DTC status bits.
TEST_FAILED = 0x01
FAILED_THIS_CYCLE = 0x02
PENDING = 0x04
CONFIRMED = 0x08
NOT_COMPLETED_SINCE_CLEAR = 0x10
FAILED_SINCE_CLEAR = 0x20
NOT_COMPLETED_THIS_CYCLE = 0x40
WARNING_INDICATOR = 0x80
STATUS_AFTER_CLEAR = NOT_COMPLETED_SINCE_CLEAR | NOT_COMPLETED_THIS_CYCLE

# State vector of a monitor: debounce counter, status byte, consecutive failed cycles, consecutive passed
# cycles (healing), previous operation-cycle input, previous clear input.
COUNTER, STATUS, FAILED_CYCLES, PASSED_CYCLES, PREV_CYCLE, PREV_CLEAR = range(6)

_DTC = re.compile(r"^[PCBU][0-3][0-9A-F]{3}$")


@register
class DiagnosticMonitor(Block):
    """A diagnostic monitor with a trouble code (DTC), like the diagnostic event manager of an engine ECU.

    ![A misfire monitor: debouncing, pending and confirmed DTC, MIL](figures/diagnostic_monitor.png)

    Input **fault** is the raw test result of a monitor (≥ 0.5 = the test failed this sample), e.g.
    ``rpm_variation > limit`` for a misfire monitor. It is **debounced** with a counter, so a short glitch does
    not set a code:

    $$ c_k = \\begin{cases} \\min(c_{k-1} + \\mathrm{fail\\_step},\\ T) & \\text{fault} \\\\ \\max(c_{k-1} - \\mathrm{pass\\_step},\\ -T) & \\text{no fault} \\end{cases} $$

    The test has **failed** when the counter reaches *T* (*threshold*) and **passed** when it reaches −*T*.
    Like OBD-II, the code is then handled over **operation cycles** (drive cycles):

    - the first failure makes the code **pending** at once;
    - after *confirm_cycles* operation cycles in a row with a failure (2: "two-trip" detection) it is
      **confirmed**, and the **MIL** (check-engine lamp) comes on if *mil* is set;
    - after *heal_cycles* cycles in a row that passed without failure, the MIL goes off again (the code stays
      stored as confirmed, so a workshop can still read it); a cycle without failure also clears *pending*.

    Optional inputs (parameters): **enable** (the test conditions are met, e.g. engine warm; the counter
    holds while it is 0), **cycle** (a rising edge starts a new operation cycle, e.g. key on), and **clear**
    (a rising edge clears the code like OBD mode 04: also the readiness).

    Outputs: **mil**, **pending**, **confirmed**, **ready** (the monitor has completed, passed or failed,
    since the code was last cleared: the OBD *readiness* of this monitor) and **status**: the UDS status
    byte (bit 0 test failed, 1 failed this cycle, 2 pending, 3 confirmed, 4 not completed since clear,
    5 failed since clear, 6 not completed this cycle, 7 warning indicator). Outputs change one sample after
    the input that causes them. Runs at its sample time.
    """

    type_id = "diagnostics.monitor"
    label = "Diagnostic Monitor"
    category = CATEGORY
    DIRECT_FEEDTHROUGH = False
    PARAMS = (
        Param("dtc", "P0300", ParamKind.STR, "Trouble code, e.g. P0171 (system too lean)"),
        Param("threshold", 10.0, ParamKind.FLOAT, "Debounce threshold T: failed at +T, passed at -T", min=1e-9),
        Param("fail_step", 1.0, ParamKind.FLOAT, "Counter step up for each failed sample", min=1e-9),
        Param("pass_step", 1.0, ParamKind.FLOAT, "Counter step down for each passed sample", min=1e-9),
        Param("jump_down", True, ParamKind.BOOL, "A failure after passing restarts counting from 0"),
        Param("confirm_cycles", 2, ParamKind.INT, "Operation cycles in a row with a failure to confirm", min=1),
        Param("heal_cycles", 3, ParamKind.INT, "Passed cycles in a row before the MIL goes off", min=1),
        Param("mil", True, ParamKind.BOOL, "A confirmed code switches the MIL on"),
        Param("enable_input", False, ParamKind.BOOL, "Add an input: the test conditions are met"),
        Param("cycle_input", False, ParamKind.BOOL, "Add an input: a rising edge starts a new operation cycle"),
        Param("clear_input", False, ParamKind.BOOL, "Add an input: a rising edge clears the code (mode 04)"),
        Param("sample_time", 0.01, ParamKind.SAMPLE_TIME, "Sample period", "s"),
    )
    NUM_OUTPUTS = 5

    def validate_params(self) -> None:
        code = str(self.params["dtc"]).strip().upper()
        if not _DTC.match(code):
            raise ParameterError(f"dtc {self.params['dtc']!r} is not a trouble code like P0171 or U0100")
        self.params["dtc"] = code

    def _ports(self) -> list[str]:
        p = self.params
        return ["fault"] + [n for n, on in (("enable", p["enable_input"]), ("cycle", p["cycle_input"]),
                                            ("clear", p["clear_input"])) if on]  # fmt: skip

    def num_inputs(self) -> int:
        return len(self._ports())

    def input_names(self) -> list[str]:
        return self._ports()

    def output_widths(self, in_widths: list[Width]) -> list[Width]:
        return [1] * 5

    def initial_discrete_state(self) -> Array:
        return np.array([0.0, float(STATUS_AFTER_CLEAR), 0.0, 0.0, 0.0, 0.0])

    def outputs(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> list[Array]:
        status = int(xd[STATUS])
        mil = float(bool(status & WARNING_INDICATOR))
        return [
            np.array([mil]),
            np.array([float(bool(status & PENDING))]),
            np.array([float(bool(status & CONFIRMED))]),
            np.array([float(not status & NOT_COMPLETED_SINCE_CLEAR)]),
            np.array([float(status)]),
        ]

    def update(self, t: float, u: Sequence[Array], xc: Array, xd: Array) -> Array:
        names = self._ports()
        get = {n: float(np.ravel(v)[0]) for n, v in zip(names, u, strict=True)}
        return step_monitor(
            xd,
            get["fault"] >= 0.5,
            get.get("enable", 1.0) >= 0.5,
            get.get("cycle", 0.0) >= 0.5,
            get.get("clear", 0.0) >= 0.5,
            self.params,
        )


def step_monitor(x: Array, fault: bool, enable: bool, cycle: bool, clear: bool, p: Mapping[str, Any]) -> Array:
    """One sample of a diagnostic monitor (the same logic as the generated C code)."""
    x = np.array(x, dtype=float)
    counter, status = float(x[COUNTER]), int(x[STATUS])
    failed_cycles, passed_cycles = int(x[FAILED_CYCLES]), int(x[PASSED_CYCLES])
    if clear and x[PREV_CLEAR] < 0.5:  # mode 04: forget everything, readiness back to "not completed"
        counter, status, failed_cycles, passed_cycles = 0.0, STATUS_AFTER_CLEAR, 0, 0
    elif cycle and x[PREV_CYCLE] < 0.5:  # a new operation cycle: judge the one that ended
        if status & FAILED_THIS_CYCLE:
            passed_cycles = 0
        elif not status & NOT_COMPLETED_THIS_CYCLE:  # completed, and passed
            failed_cycles = 0
            passed_cycles += 1
            status &= ~PENDING
            if passed_cycles >= int(p["heal_cycles"]):
                status &= ~WARNING_INDICATOR
        status = (status & ~(FAILED_THIS_CYCLE | TEST_FAILED)) | NOT_COMPLETED_THIS_CYCLE
        counter = 0.0
    if enable:
        threshold = float(p["threshold"])
        if fault:
            if counter < 0 and p["jump_down"]:
                counter = 0.0
            counter = min(counter + float(p["fail_step"]), threshold)
        else:
            counter = max(counter - float(p["pass_step"]), -threshold)
        if counter >= threshold and not status & FAILED_THIS_CYCLE:  # failed: first time in this cycle
            failed_cycles += 1
            status |= TEST_FAILED | FAILED_THIS_CYCLE | PENDING | FAILED_SINCE_CLEAR
            status &= ~(NOT_COMPLETED_THIS_CYCLE | NOT_COMPLETED_SINCE_CLEAR)
            if failed_cycles >= int(p["confirm_cycles"]):
                status |= CONFIRMED
                if p["mil"]:
                    status |= WARNING_INDICATOR
                    passed_cycles = 0
        elif counter >= threshold:
            status |= TEST_FAILED
        elif counter <= -threshold:
            status &= ~(TEST_FAILED | NOT_COMPLETED_THIS_CYCLE | NOT_COMPLETED_SINCE_CLEAR)
    return np.array([counter, float(status), float(failed_cycles), float(passed_cycles), float(cycle), float(clear)])
