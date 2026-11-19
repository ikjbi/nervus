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

## What can be generated

Everything that is discrete-time or has no state: gains, sums, lookup tables, logic, relays, filters,
counters, delays, discrete PID, and more. Not generated: blocks with continuous states (Integrator,
Transfer Fcn, PID Controller, ...) and time-based sources (Step, Sine, ...). Keep those in the plant, outside
the subsystem. If something cannot be generated, Diagnostics lists the blocks.
