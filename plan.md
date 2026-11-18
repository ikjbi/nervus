# Nervus — Project Plan

> **Nervus** — Latin for "nerve". GitHub: `ikjbi/nervus`, Python package: `nervus`.

An open-source, Python-based block-diagram modeling and simulation tool (a Simulink alternative). The goal is
model-based design of control software for cars and trucks: model it, simulate it, test it, then generate C code
for an ECU.

Check items off (`- [x]`) as they are done. Add new items and phases whenever we find something we need.

---

## Guiding principles

- **Headless engine first.** The simulation engine is pure Python with no Qt imports, so it can be used from
  scripts, tests, Jupyter and CI. The GUI sits on top of it.
- **MVC in the GUI.**
  - **Model:** the diagram domain model (blocks, ports, connections, parameters) plus the simulation results.
    It emits change notifications and knows nothing about Qt widgets.
  - **View:** PySide6 widgets and the `QGraphicsScene` canvas. It renders the model and forwards user input.
    It holds no business logic.
  - **Controller:** turns user intent into model changes as undoable commands (`QUndoStack`), and runs
    simulations.
- **Correctness is verified.** Every block and solver is tested against analytical solutions or reference data.
- **Built with codegen in mind.** Blocks have a clear `outputs` / `update` / `derivatives` split, explicit sample
  times, explicit data types and no hidden state. These are the same properties C code generation needs later.
- **Readable, git-friendly model files.** Models are JSON with a schema version, so diffs and code review work.
- **Documented as we go.** Every user-visible feature ships with docs and in-app help. Every change is committed
  and pushed.

## Proposed layout

```
src/nervus/
  core/        # Block base class, ports, signals, diagram graph, sample times, data types
  solvers/     # Fixed-step (Euler, RK4) and variable-step (scipy) solvers, zero-crossing detection
  sim/         # Simulator: sorting, algebraic loop detection, execution loop, logging/results
  blocks/      # Block library (sources, sinks, math, continuous, discrete, lookup, logic, ...)
  io/          # Model file (JSON) load/save, schema versioning and migration
  codegen/     # (later) C code generation
  gui/
    models/       # Qt-facing model adapters / signals around core diagram
    views/        # Main window, canvas, palette, property editor, scope windows
    controllers/  # Commands (undo/redo), simulation controller, file controller
    resources/    # Icons, stylesheets (light/dark theme)
docs/          # User guide, block reference, developer docs (MkDocs)
examples/      # Example models (.json) and scripts
tests/
```

---

## Phase 0 – Project setup
- [x] Choose the project name (**Nervus**), then rename the folder and create the private GitHub repo `ikjbi/nervus`
- [x] `git init`, `.gitignore`, MIT `LICENSE`, first commit and push
- [x] `pyproject.toml` (src layout, Python ≥ 3.11) with `uv` for environments
- [x] Tooling: `ruff` (lint and format), `mypy`, `pytest`, `pre-commit`
- [x] GitHub Actions CI: lint, type-check and tests on every push and PR
- [x] `README.md` (what it is, install, quick start), `CONTRIBUTING.md`, `CHANGELOG.md`
- [x] Docs skeleton with MkDocs Material
- [ ] Publish the docs to GitHub Pages (once the repo is public, or on a paid plan)

## Phase 1 – Core simulation engine (headless)
- [x] `Block` base class: input and output ports, parameters, states, `outputs()`, `update()` (discrete),
      `derivatives()` (continuous), direct-feedthrough flag, sample time
- [x] Signals: scalar and vector (NumPy), with basic data types (`double` first)
- [x] `Diagram`: blocks plus connections, with validation (unconnected ports, fan-in, type and size mismatch)
- [x] Execution ordering: topological sort over direct-feedthrough dependencies
- [x] Algebraic loop detection, with clear error messages
- [x] Fixed-step solvers: forward Euler, RK4
- [x] Variable-step solver via `scipy.integrate.solve_ivp` (RK45 / LSODA)
- [x] Sample times: continuous, discrete (period/offset), inherited, constant; multi-rate scheduling
- [x] Simulation results: logged signals, time vector, export to NumPy / pandas / CSV
- [x] Python API: build and run a diagram entirely in code

## Phase 2 – Core block library (~15 blocks)
- [x] Sources: Constant, Step, Ramp, Sine, Pulse, Clock, From Workspace (array or CSV)
- [x] Math: Gain, Sum (configurable signs), Product, Abs, Saturation, Math Function
- [x] Continuous: Integrator (with limits and reset), Derivative, Transfer Function, State-Space
- [x] Discrete: Unit Delay, Zero-Order Hold, Discrete Integrator
- [x] Control: PID (continuous and discrete; anti-windup by clamping or back-calculation)
- [x] Sinks: Scope (logging), To Workspace, Terminator
- [x] Routing: Mux, Demux, Switch
- [x] Python Function block (user-defined code, the equivalent of MATLAB Function)

## Phase 3 – Model file format
- [x] JSON schema: blocks, parameters, positions, connections, solver settings, schema version
- [x] Save and load round-trip tests
- [x] Schema migration hook for future versions
- [x] Block registry so files reference blocks by type id

## Phase 4 – Verification and first example
- [x] Tests against analytical solutions (first and second order systems, integrator, step responses)
- [x] Solver accuracy and convergence tests
- [x] Example: PID-controlled mass-spring-damper (script and `.json` model)
- [x] Example: first-order throttle actuator with a discrete PI controller (10 ms ECU task)

## Phase 5 – GUI MVP (PySide6, MVC)
- [x] App shell: main window, menus, toolbar, status bar, modern light and dark theme (follows the system)
- [x] Canvas (`QGraphicsView`): place, move, select and delete blocks; zoom and pan (wheel, pinch, trackpad,
      Space+drag); grid snapping; automatic layout for models without positions
- [x] Wiring: drag from port to port (either direction), orthogonal routing, branch dots on fan-out
- [x] Block palette (library browser) with search, drag and drop onto the canvas
- [x] Property editor panel for block parameters, with validation and expressions (`2*pi`, `[1 2; 3 4]`)
- [x] Undo and redo for every edit (`QUndoStack` commands in controllers); copy / cut / paste
- [x] Run, stop and solver settings dialog; simulation runs off the UI thread
- [x] Scope windows with post-run plots (pyqtgraph), hover readout
- [ ] Live scope updates while the simulation runs
- [x] File: new, open, save, save as, recent files
- [x] Error and diagnostics panel (algebraic loops, unconnected ports), with click to highlight the block
- [ ] Manual wire routing (drag segments, waypoints) and draggable branch points
- [ ] Rotate / flip blocks, resize blocks, nudge with arrow keys
- [ ] Show signal widths and sample-time colours on the canvas (like Simulink's "port data types" / "sample time colors")
- [ ] Right-click context menus on blocks, wires and the canvas

## Phase 6 – Documentation and in-app help
- [x] User guide (Python API): getting started, concepts, coming from Simulink, model files
- [x] User guide (GUI): the editor, with screenshots generated by `scripts/screenshots.py`
- [x] Block reference, generated from block docstrings and parameter metadata
- [x] In-app help: F1 or the "?" button on a block opens its reference page; tooltips on parameters
- [x] Typeset LaTeX equations in the in-app help (matplotlib mathtext) and in the docs (MathJax)
- [x] Explanatory block figures (`scripts/gen_figures.py`), shown in the app and in the docs
- [x] Developer docs: architecture (engine and MVC), how to write a custom block
- [ ] Tutorials that follow the examples

## Phase 7 – Modeling features needed for real control software
- [ ] Subsystems (hierarchical), with Inport and Outport blocks; open a subsystem by double-clicking
- [ ] Masks: custom parameter dialog and icon for a subsystem
- [ ] Enabled and triggered subsystems
- [ ] Lookup tables: 1-D, 2-D and n-D with interpolation and extrapolation modes. These are critical for ECU
      calibration maps (fuel, ignition, boost)
- [ ] Logic and relational blocks: AND/OR/NOT, compare, relay (hysteresis), rate limiter, dead zone
- [ ] Zero-crossing and event detection for discontinuities (Saturation, Switch, Abs, Integrator limits,
      PID clamping). Without it, clamping in a continuous PID chatters under variable-step solvers
- [ ] Buses (named, structured signals)
- [ ] Goto/From, data stores
- [ ] Model workspace / parameter files (calibration data separate from the model)
- [ ] Reusable libraries and linked blocks

## Phase 8 – Automotive and ECU learning library
- [ ] Mean-value engine model: throttle and intake manifold, air mass flow, torque production, crank dynamics
- [ ] Fuel control: injector model, lambda (AFR) closed-loop control, short and long term fuel trim
- [ ] Ignition timing from speed/load maps, knock retard
- [ ] Idle speed control
- [ ] Electronic throttle control (DC motor, return spring, PID)
- [ ] Vehicle longitudinal dynamics: driveline, gearbox, tire slip, aero and rolling resistance
- [ ] Driver model and drive cycles (WLTP, NEDC, FTP-75)
- [ ] Sensor and actuator models: quantization, noise, delay, faults
- [ ] Truck-specific models: heavy-duty diesel, exhaust brake, AMT gearbox
- [ ] Tutorial series: "Learn engine control with nervus"

## Phase 9 – Data types and fixed-point (required for ECU code)
- [ ] Integer types (int8/16/32, uint8/16/32), boolean, single
- [ ] Fixed-point with slope and bias scaling, overflow and saturation modes, rounding
- [ ] Data type propagation and checking across the diagram
- [ ] Simulation that matches the integer behavior of the generated code bit for bit

## Phase 10 – State machines
- [ ] State chart block (a Stateflow-like subset): states, transitions, guards, entry/during/exit actions
- [ ] Graphical state-chart editor
- [ ] Example: gear-shift logic, engine operating modes (crank, idle, run, fuel cut-off)

## Phase 11 – C code generation
- [ ] Restrict to fixed-step, discrete models (with a check and clear errors otherwise)
- [ ] Generate `model.h` / `model.c` with `model_init()` and `model_step()`, static memory only, no malloc
- [ ] Per-block code templates; parameters as `const` or as calibratable globals
- [ ] Generated code follows MISRA C guidelines (checked with cppcheck's MISRA addon)
- [ ] Software-in-the-loop (SIL): compile the generated C, run it via ctypes/cffi, and compare it with the Python
      simulation in tests
- [ ] Code generation report (HTML): block-to-code traceability
- [ ] Multi-rate tasks (one step function per rate)

## Phase 12 – ECU integration and calibration
- [ ] CAN: import DBC files (`cantools`), CAN receive and transmit blocks, signal packing
- [ ] A2L file generation for calibration tools (measurements and characteristics)
- [ ] XCP-on-CAN basics for live measurement and calibration
- [ ] Target: a development board (e.g. STM32 or ESP32 with CAN), as a scheduler template and HAL stubs
- [ ] Processor-in-the-loop (PIL) testing
- [ ] Hardware-in-the-loop (HIL): run the plant model in real time against a real ECU

## Phase 13 – Interoperability
- [ ] FMI 2.0/3.0: import FMUs as blocks (`fmpy`), export models as FMUs
- [ ] Import a subset of Simulink `.slx`/`.mdl` (useful for comparing against work models)
- [ ] Export results to MAT files (`scipy.io`) for MATLAB users

## Phase 14 – Quality, testing and release
- [ ] Model-level test harness: test cases, expected outputs, coverage of blocks and states
- [ ] Requirements traceability (link requirements to blocks and tests)
- [ ] Performance: vectorized execution, optional Numba for hot paths
- [ ] Packaging: PyPI release, standalone installers (PyInstaller / Briefcase) for macOS, Windows and Linux
- [ ] Versioned docs, release notes

---

## Safety note

Code generated by this tool is for learning, bench and off-road experiments. Do not run it on a vehicle on public
roads. Production ECU software needs ISO 26262 processes, qualified tools and certified code.

## Decisions log

| Date       | Decision                                                               |
|------------|------------------------------------------------------------------------|
| 2026-11-18 | Python engine + PySide6 desktop GUI, MVC architecture                  |
| 2026-11-18 | MIT license                                                            |
| 2026-11-18 | Headless engine before GUI; JSON model files                           |
| 2026-11-18 | Long-term goal: C code generation for car/truck ECUs                   |
| 2026-11-18 | Blocks are pure functions (outputs/derivatives/update); simulator owns all state |
| 2026-11-18 | Discrete block outputs are computed only at sample hits and held in between |
| 2026-11-18 | Variable-step solvers stop exactly at block breakpoints (Step, Pulse, ...) |
| 2026-11-18 | Frequencies in rad/s and most defaults follow Simulink, to ease moving between the two |
| 2026-11-18 | CI runs on Ubuntu only while the repo is private, to save Actions minutes |
| 2026-11-18 | Every feature ships with in-app help and GitHub docs, with figures/screenshots where useful |
| 2026-11-18 | Block docstrings are the single source for the in-app help and the docs reference |
| 2026-11-18 | Nervus clears the macOS "hidden" flag on Qt plugins at startup (uv/.venv issue) |
