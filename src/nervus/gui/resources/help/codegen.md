# C code generation

Nervus turns the **discrete-time** part of a model into plain C code for an ECU.

## Steps

1. Put the ECU software in a **subsystem**. Its In/Out blocks are the interface: sensors in, actuators out.
2. Give the controller blocks a **sample time** (e.g. the workspace variable `Ts = 0.01`).
3. Select the subsystem and choose **Code → Generate C Code…** (⌘B / Ctrl+B). With nothing selected, the
   whole model is generated.
4. Press **Run SIL check**. The code is compiled and run side by side with the model on the same inputs,
   and the largest difference is shown. It should be about 1e-15.
5. **Save to folder…** writes the files; **Open report** shows which lines belong to which block.

## Using the code

Call `<name>_initialize()` once, then every `<NAME>_BASE_PERIOD` seconds:

1. write the inputs into `<name>_U`,
2. call `<name>_step()`,
3. read the outputs from `<name>_Y`.

`main_example.c` shows the pattern. Only `<name>.h` and `<name>.c` go into the ECU project.

## Calibration

Parameters are in the struct `<name>_P`. A parameter written as a workspace variable (`Kp`) becomes one
shared field `<name>_P.Kp` that a calibration tool can change while the code runs.

## Calibration file (A2L)

The code generator also writes `<name>.a2l`, the file calibration tools such as INCA or CANape read. It
lists the tunable parameters, with units and limits from the model workspace, and the block signals for
measurement.

## One function per task (RTOS)

On a real ECU an operating system (an RTOS, e.g. AUTOSAR OS or FreeRTOS) runs the software in periodic
tasks, and a faster task interrupts a slower one. Tick **One function per task (for an RTOS)** in the
Generate C dialog (or `generate_c(model, tasks=True)`) to get one function per rate:

```c
void ecu_task_10ms(void);   /* call every 10 ms, highest priority */
void ecu_task_100ms(void);  /* call every 100 ms */
```

`main_example.c` then shows one OS task per rate, with the priorities to use. `ecu_step()` still exists:
called every base period, it runs the due tasks fastest first, which is what the SIL check compares with the
simulation.

**Signals between tasks need a Rate Transition block.** If the 10 ms task read the 100 ms task's output
directly, it would see the old or the new value depending on whether the slow task had finished, so the
result would depend on timing. A Rate Transition makes the transfer deterministic, in the simulation and on
the target:

![Rate Transition between a 10 ms and a 100 ms task](figures/rate_transition.png)

| Direction | Set | Behaviour |
|---|---|---|
| `fast_to_slow` | *sample_time* = the slow rate | the slow task gets the fast signal as it was at the start of its period |
| `slow_to_fast` | *sample_time* = the slow rate, *output_sample_time* = the fast rate | the fast task gets the slow signal one slow period later |

The code generator checks the model: a signal that goes from one task to another without a Rate Transition
is reported with both block names. Blocks that get the model's In ports directly must have a rate of their
own: sample the inputs with a Zero-Order Hold, or put each task in an
atomic subsystem (see *Subsystems*) with its own *sample_time*.

## What can be generated

Everything that is discrete-time or has no state: gains, sums, lookup tables, logic, relays, filters,
counters, delays, discrete PID, and more. Not generated: blocks with continuous states (Integrator,
Transfer Fcn, PID Controller, ...) and time-based sources (Step, Sine, ...). Keep those in the plant, outside
the subsystem. If something cannot be generated, Diagnostics lists the blocks.
