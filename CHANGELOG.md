# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- Out blocks could be scheduled before the block driving them, so generated C output last step's value.
- Generated C for 2-point lookup axes compared an unsigned value with 0 (rejected by GCC with -Werror).
- A Transfer Fcn without dynamics (e.g. `3/2`) failed to build its state-space form.
- 1-D lookup with `nearest` interpolation and linear extrapolation rounded halves to even.
- An empty diagram passed to the editor model or a Subsystem was replaced by a default one.
- Discrete blocks with an inherited sample time used −1 as their period (Rate Limiter, Discrete Filter, ...).

### Added
- Linear analysis (`nervus.analysis`): linearize between In and Out blocks around initial or trimmed
  states, transfer function, poles, DC gain, Bode, gain/phase margins, step response; Analysis → Linear
  Analysis dialog (Ctrl+L).
- Example and tutorial: idle speed control on a mean-value engine model (throttle flow, manifold, cylinder
  flow, torque, crankshaft) with PI control, AC feed-forward, requirement tests and C code.
- A2L (ASAM MCD-2 MC) file with every C code generation: parameters as CHARACTERISTICs with units/limits from
  the workspace, signals as MEASUREMENTs; `fill_addresses()` resolves addresses from the built binary.
- State Chart block: state machines with entry/during/exit actions, prioritised transitions with guards and
  actions, local variables, `after(n)` and `t_in_state`; written in a small text language, evaluated safely,
  and generated as C.
- Zero-crossing detection for variable-step solvers: discontinuous blocks freeze their mode during
  integration and events are located exactly; a chattering guard reports a warning. A clamped continuous PID
  that took 33 s now takes 0.1 s. Toggle with `settings.zero_crossing`.
- Stop Simulation and Assertion blocks.
- Test cases saved with the model (schema version 4): input signals for top-level In blocks, parameter
  overrides or a parameter-set file, stop time, and checks (`bounds`, `final_value`, `reaches`, `max`, `min`,
  `baseline`). `nervus.testing.run_tests()` runs them.
- `simulate(..., inputs={...})` drives top-level In blocks with `Signal`s (steps, ramps, CSV).
- Results: `SimResult.save()/load()` (`.nervres`), `to_mat()`, and `compare_results()`.
- Editor: Test Manager panel (background test runs, pass/fail, undoable edits) and Data Inspector (overlay and
  compare runs, differences, save/load/export).
- The throttle_ecu example stores three requirement test cases.
- C code generation (`nervus.codegen.generate_c`) for models and subsystems: `<name>.h`/`<name>.c` with
  `_initialize()`/`_step()`, static memory, input/output/parameter/state structs, shared calibration
  parameters for workspace variables, base-rate multi-rate scheduling, a `main_example.c` template and an
  HTML report with block-to-code traceability. Templates for 38 block types.
- Software-in-the-loop back-to-back testing (`nervus.codegen.sil`): compiles the generated code and compares
  it with the Python model step by step; tested for every block template.
- Editor: Code → Generate C Code (Ctrl+B) with a code viewer, SIL check, save and report.
- Example `throttle_ecu.py` with its generated code committed in `examples/generated/ECU`.
- Subsystems: Subsystem, In and Out blocks; hierarchies are flattened at compile time; results and errors use
  path names (`ECU/throttle_pi`); model file schema version 3 stores nested systems.
- Editor: open subsystems by double-click, breadcrumb navigation, Up to Parent, Create Subsystem from
  Selection (Ctrl+G), Auto Layout (Ctrl+Shift+L); undo works across levels.
- ECU block library: 1-D and 2-D Lookup Tables (linear/nearest/flat, clip/linear extrapolation), Relational
  Operator, Compare To Constant, Logical Operator, Dead Zone, Quantizer, Relay (hysteresis), Rate Limiter,
  Integer Delay, Counter, Edge Detect, Debounce, Discrete Filter (PT1), Moving Average, MinMax, Bias, Ground,
  each with equations, figures and help.
- Example: radiator fan control with sensor filtering, hysteresis and a lookup table.
- Model workspace: named variables (value, unit, min/max, description) stored in the model; block
  parameters can be expressions of them (`Gain(gain="Kp")`, `"1/tau"`, `sample_time="Ts"`).
- Parameter sets (`.nervcal`): save, load and apply calibrations; `simulate(..., params={...})` overrides.
- Model Workspace panel in the editor, with undo and parameter-set load/save.
- Model file schema version 2 (adds `workspace`); version 1 files are migrated automatically.
- Desktop editor (`nervus` command), built with PySide6 in a Model–View–Controller structure: canvas with
  drag-and-drop blocks and wires, block library with search, property editor with expressions and MATLAB-style
  matrices, undo/redo for every edit, copy/paste, diagnostics panel, threaded simulation with progress and stop,
  scope windows with hover readout, simulation settings dialog, recent files, light and dark themes.
- In-app help: user guide pages and the full block reference (F1 on a selected block), with typeset LaTeX
  equations and explanatory figures.
- Block figures (`scripts/gen_figures.py`) and editor screenshots (`scripts/screenshots.py`) for the docs.
- LaTeX equations in every block's documentation.
- Automatic left-to-right layout for diagrams without block positions.
- Simulation engine: block base class, diagrams, width propagation, execution ordering, algebraic loop
  detection, sample-time inheritance, multi-rate discrete scheduling.
- Solvers: fixed-step Euler and RK4; variable-step RK45, RK23, DOP853, Radau, BDF and LSODA (via SciPy).
  Variable-step solvers stop exactly at discontinuities declared by blocks.
- Simulation results with access by block name, CSV and pandas export.
- Model files (`.nervus`, JSON) with schema versioning and migrations; simulation settings stored per diagram.
- Examples: PID control of a mass-spring-damper, electronic throttle control with a discrete PI.
- Documentation: getting started, concepts, coming from Simulink, model files, architecture, writing blocks,
  and a block reference generated from the code.
- Block library (30 blocks): Constant, Step, Ramp, Sine Wave, Pulse Generator, Clock, From Workspace, Gain,
  Sum, Product, Abs, Saturation, Math Function, Integrator, Derivative, Transfer Fcn, State-Space, Unit Delay,
  Zero-Order Hold, Discrete-Time Integrator, Discrete Transfer Fcn, PID Controller, Discrete PID Controller,
  Scope, To Workspace, Terminator, Mux, Demux, Switch, Python Function.
- Project setup: packaging (uv/hatchling), linting (ruff), type checking (mypy), tests (pytest), CI, docs skeleton.
