# Getting started

Nervus models a system as a **block diagram**: blocks are small dynamic systems (a gain, an integrator, a
PID controller), and the lines between them carry signals.

## Build your first model in 5 steps

1. **Add blocks.** Drag a block from the **Library** (left) onto the canvas, or double-click it in the
   library. Add a *Step*, a *Transfer Fcn* and a *Scope*.
2. **Connect them.** Press on a block's **output port** (the small triangle on its right side) and drag to
   another block's **input port** (left side). Releasing on the body of a block connects to its first free
   input.
3. **Set parameters.** Select a block and edit its parameters in the **Properties** panel (right).
   Values accept expressions like `2*pi`, `1/0.05` and matrices like `[1 2; 3 4]`.
4. **Run.** Press **▶ Run** (⌘R / Ctrl+R or F5). The stop time is in the toolbar.
5. **Look at the result.** Scope windows open after the first run. Double-click a Scope block to reopen
   it. Hover over the plot to read values.

## What Nervus can do

Every feature has a page in this Help window (the list on the left):

| Area | Features | Help page |
|---|---|---|
| Editor | block library, wires, undo, copy/paste, right-click menus, flip blocks, auto layout, themes | Using the editor, Keyboard shortcuts |
| Simulation | continuous, discrete and multirate models, solvers, zero crossings, stop and assertion blocks | Running simulations, Concepts |
| Parameters | model workspace, expressions, parameter sets (`.nervcal`) | Workspace and calibrations |
| Structure | subsystems, masks, enabled/triggered subsystems, atomic tasks, variants, component libraries | Subsystems, Component libraries |
| Logic | State Chart block | State machines |
| ECU code | C code, A2L file, fixed-point data types, software-in-the-loop check | C code generation, Data types and fixed point |
| Testing | test cases, Test Manager, Data Inspector, coverage, Model Advisor | Test cases and the Data Inspector, Coverage and Model Advisor |
| Analysis | linearisation, trim, Bode, margins | Linear analysis |
| Vehicle networks | CAN with DBC files; OBD-II live data and trouble codes | CAN communication, OBD-II live data |
| Simulink users | how Simulink names map to Nervus | Coming from Simulink |
| Files | what is stored in a `.nervus` file | Model files |

## Where to go next

- **Using the editor**: selecting, moving, copying and undoing.
- **Running simulations**: solvers, sample times and what to do when something goes wrong.
- **Block reference**: every block, its equation and parameters (below the guides in the list on the left).
  Select a block and press **F1** to jump to its page.
- **Tutorials**: idle speed control, lambda control and fuel trims, and a car on a drive cycle.

The `examples` folder in the repository has complete models you can open with **File → Open**:

| Example | What it shows |
|---|---|
| `throttle_pi.nervus` | an electronic throttle controller running as a 10 ms ECU task |
| `throttle_ecu.nervus` | the same controller as an ECU subsystem, with generated C and A2L |
| `mass_spring_damper_pid.nervus` | continuous PID position control with actuator limits |
| `idle_speed_control.nervus` | idle speed control on a mean-value engine model (tutorial) |
| `coolant_fan.nervus` | radiator fan control with hysteresis and a lookup table |
| `fixed_point_sensor.nervus` | a sensor signal path in fixed-point data types |
| `engine_comparison.nervus` | two engines from one library component |
| `lambda_control.nervus` | lambda control with short- and long-term fuel trims (tutorial) |
| `drive_cycle.nervus` | a car with a driver model on the ECE-15 drive cycle (tutorial) |
| `engine_modes.nervus` | engine operating modes as a State Chart: crank, idle, run, fuel cut-off, stall |
| `gear_shift.nervus` | gear-shift logic of an automatic gearbox on a car with a hill (tutorial) |
| `obd_ecu.nervus` | an engine ECU with trouble codes that answers OBD-II tools (`python -m nervus.obd simulate`) |
