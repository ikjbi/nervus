# Diagnostics

## Diagnostic Monitor

`diagnostics.monitor` · Diagnostics

A diagnostic monitor with a trouble code (DTC), like the diagnostic event manager of an engine ECU.

![A misfire monitor: debouncing, pending and confirmed DTC, MIL](../images/blocks/diagnostic_monitor.png)

Input **fault** is the raw test result of a monitor (≥ 0.5 = the test failed this sample), e.g.
``rpm_variation > limit`` for a misfire monitor. It is **debounced** with a counter, so a short glitch does
not set a code:

$$ c_k = \begin{cases} \min(c_{k-1} + \mathrm{fail\_step},\ T) & \text{fault} \\ \max(c_{k-1} - \mathrm{pass\_step},\ -T) & \text{no fault} \end{cases} $$

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

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `dtc` | `'P0300'` |  | Trouble code, e.g. P0171 (system too lean) |
| `threshold` | `10.0` |  | Debounce threshold T: failed at +T, passed at -T |
| `fail_step` | `1.0` |  | Counter step up for each failed sample |
| `pass_step` | `1.0` |  | Counter step down for each passed sample |
| `jump_down` | `True` |  | A failure after passing restarts counting from 0 |
| `confirm_cycles` | `2` |  | Operation cycles in a row with a failure to confirm |
| `heal_cycles` | `3` |  | Passed cycles in a row before the MIL goes off |
| `mil` | `True` |  | A confirmed code switches the MIL on |
| `enable_input` | `False` |  | Add an input: the test conditions are met |
| `cycle_input` | `False` |  | Add an input: a rising edge starts a new operation cycle |
| `clear_input` | `False` |  | Add an input: a rising edge clears the code (mode 04) |
| `sample_time` | `0.01` | s | Sample period |

*Direct feedthrough:* no

---
