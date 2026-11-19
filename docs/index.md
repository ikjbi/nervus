# Nervus

Nervus is an open-source block-diagram modeling and simulation tool written in Python, as an alternative to
Simulink. It is aimed at control engineering, and especially at engine and vehicle control units (ECUs).

!!! warning "Pre-alpha"
    Nervus is in early development. APIs may change.

## What Nervus can do

| Area | Features | Guide |
|---|---|---|
| Editor | block library, drag and drop, wires, undo, copy/paste, right-click menus, flip blocks, auto layout, light/dark theme, F1 help for every block | [Editor](editor.md) |
| Simulation | continuous, discrete and multirate models; fixed-step and variable-step solvers; zero-crossing detection; stop and assertion blocks | [Concepts](concepts.md) |
| Parameters | model workspace with units and limits, expressions, parameter sets (`.nervcal`), parameter sweeps from Python | [Workspace](workspace.md) |
| Structure | subsystems, masks, enabled/triggered subsystems, atomic tasks with their own period, variants, component libraries | [Subsystems](subsystems.md), [Libraries](libraries.md) |
| Logic | State Chart block (states, transitions, guards, timers) | [State machines](statecharts.md) |
| ECU code | C code generation (multirate, calibratable parameters, A2L file, HTML report), fixed-point data types, software-in-the-loop check | [C code](codegen.md), [Data types](datatypes.md) |
| Testing | test cases stored with the model, Test Manager, Data Inspector, results files, model coverage, Model Advisor | [Testing](testing.md), [Verification](verification.md) |
| Analysis | linearisation, trim, Bode, stability margins, step response | [Analysis](analysis.md) |
| Vehicle networks | CAN Pack/Unpack with DBC files; OBD-II live data and trouble codes from a real car | [CAN](can.md), [OBD-II](obd.md) |
| Learning | examples and tutorials: idle speed control, lambda control and fuel trims, a car on a drive cycle | [Tutorials](tutorials/idle-speed-control.md) |

## Where to start

- [Getting started](getting-started.md): install Nervus and build your first model in Python.
- [Concepts](concepts.md): signals, sample times, solvers and algebraic loops.
- [Coming from Simulink](coming-from-simulink.md): how Simulink terms and blocks map to Nervus.
- [Block reference](blocks/index.md): every block, its equations and parameters.
