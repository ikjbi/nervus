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
- [ ] Obstacle-avoiding automatic wire routing (wires currently may pass behind blocks)
- [x] Auto Layout command (left-to-right by signal flow), undoable
- [x] Flip blocks (Ctrl+Shift+F) for feedback paths; the wire router handles flipped ports
- [ ] Rotate blocks (vertical signal flow), resize blocks, nudge with arrow keys
- [x] Show data types on the canvas (View → Show Data Types)
- [ ] Show signal widths and sample-time colours on the canvas (like Simulink's "port data types" / "sample time colors")
- [x] Right-click context menus on blocks, wires and the canvas

## Phase 6 – Documentation and in-app help
- [x] User guide (Python API): getting started, concepts, coming from Simulink, model files
- [x] User guide (GUI): the editor, with screenshots generated by `scripts/screenshots.py`
- [x] Block reference, generated from block docstrings and parameter metadata
- [x] In-app help: F1 or the "?" button on a block opens its reference page; tooltips on parameters
- [x] Typeset LaTeX equations in the in-app help (matplotlib mathtext) and in the docs (MathJax)
- [x] Explanatory block figures (`scripts/gen_figures.py`), shown in the app and in the docs
- [x] Developer docs: architecture (engine and MVC), how to write a custom block
- [ ] Tutorials that follow the examples

## Phase 7 – Parameters, model workspace and calibration data
*ECU software is "code + calibration". Parameters must live outside the blocks, as named, tunable values.*
- [x] Model workspace: named variables (`Kp = 1.5`, `fuel_map = [...]`) stored in the model file
- [x] Block parameters can be expressions using workspace variables (`Kp`, `2*Kp`, `1/tau`)
- [x] Variables carry metadata: description, unit, min/max (for calibration and A2L later)
- [x] Parameter sets ("calibrations"): save/load named sets of variable values as separate files and switch
      between them (e.g. `petrol.nervcal.json` vs `diesel.nervcal.json`)
- [x] GUI: Model Workspace panel to add/edit/delete variables; parameter fields accept and show expressions
- [ ] Autocomplete variable names in parameter fields; "find usages" of a variable
- [x] Python API: `diagram.workspace["Kp"] = 2.0`, `simulate(d, params={...})` overrides

## Phase 8 – ECU block library
*The blocks that real engine/vehicle control software is built from.*
- [x] Lookup tables: 1-D and 2-D (n-D later) with linear / nearest / hold interpolation and clip/linear
      extrapolation. Calibration maps (fuel, ignition, boost) are 2-D tables
- [x] Relational Operator (`<`, `<=`, `==`, `!=`, `>=`, `>`), Logical Operator (AND, OR, NOT, XOR, NAND, NOR),
      Compare To Constant
- [x] Relay (hysteresis), Dead Zone, Rate Limiter (discrete), Quantizer, Sign, MinMax, Bias
- [x] Integer Delay (z⁻ⁿ), Memory, Counter (free-running / limited), Edge Detect (rising/falling/either),
      Debounce (signal must hold for N samples), Discrete Filter (first-order low-pass), Moving Average
- [x] Ground, MinMax, Bias
- [ ] Initial Condition, Data Type Conversion (once Phase 13 lands), n-D lookup tables, Prelookup + Interpolation
- [x] Figures, equations and help for every new block

## Phase 9 – Hierarchy: subsystems, masks, conditional execution, variants
- [x] Subsystem block with Inport/Outport blocks; flattened at compile time
- [x] GUI: double-click to open a subsystem, breadcrumb navigation, "Create Subsystem from Selection"
- [x] Atomic subsystems with their own sample time (one ECU task = one atomic subsystem)
- [x] Masks: parameter dialog and icon text for a subsystem; mask parameters as local workspace (nested, C code)
- [x] Enabled subsystems (held or reset states; C code)
- [x] Triggered subsystems (rising/falling/either edge, combined with enable; C code)
- [ ] Function-call subsystems (task scheduling from a chart or scheduler block)
- [x] Variant subsystems (conditions on workspace variables, default variant, Variants dialog, C code of the active variant)
- [x] Reusable component libraries (`.nervlib` files, linked subsystems updated on load, per-instance mask values)

## Phase 10 – Test cases, scenarios and results
*"Save/load cases": reproducible simulations you can rerun and compare.*
- [x] Test case = name + input scenario + parameter set + stop time + checks, saved with the model
- [ ] Export/import test suites as separate files
- [x] Scenario inputs: piecewise signals (hold/linear), CSV replay
- [ ] Graphical signal editor (Signal Builder-like)
- [x] Save/load simulation results (`.nervres`, compressed NPZ) and export CSV / MAT
- [ ] Import/export ASAM MDF4 (`.mf4`, via `asammdf`), the format of INCA/CANape vehicle logs
- [x] Run several cases in batch
- [ ] Parameter sweeps and Monte Carlo runs; HTML test report
- [x] Simulation Data Inspector: overlay and compare runs, with differences and tolerance checks
- [x] GUI: Test Manager panel (create, run, pass/fail), compare-runs window
- [x] Python API for all of the above (usable from pytest for regression tests)

## Phase 11 – C code generation
- [x] Restrict to fixed-step, discrete-time models (clear errors otherwise; continuous plants stay in
      simulation)
- [x] Generate `model.h` / `model.c` with `model_initialize()` and `model_step()`, static memory only, no malloc
- [x] Structs for inputs, outputs, states and parameters; parameters as `const` or as calibratable globals
- [x] Per-block C templates for all discrete/stateless blocks, including lookup tables
- [x] Multi-rate: a base-rate scheduler with rate counters
- [ ] Multi-rate: one step function per rate (for RTOS tasks), with rate transition blocks
- [x] Software-in-the-loop (SIL): compile the generated C, run it via ctypes, and compare it with the Python
      simulation (back-to-back test)
- [x] Code generation report (HTML): block-to-code traceability, memory use
- [ ] Generated code follows MISRA C guidelines (checked with cppcheck's MISRA addon); compiles with
      `-Wall -Wextra -Werror -pedantic` already
- [ ] Generate code for blocks with offsets exactly like the simulation's first step
- [ ] Optional `const` parameters (ROM) instead of calibratable RAM
- [ ] Reusable functions for subsystems instead of inlining
- [x] GUI: Code → Generate C Code, with a report and "run SIL comparison"
- [x] Example: an ECU-style project folder with a `main.c` that calls `model_step()` every 10 ms

## Phase 12 – Zero crossings, events and solver robustness
- [x] Zero-crossing detection with frozen modes (Saturation, Switch, Abs, Dead Zone, comparisons, Integrator
      limits, PID limits/clamping), direction-aware events and a chattering (Zeno) guard
- [ ] Integrator external reset and saturation ports
- [ ] Algebraic loop solver (optional), with warnings
- [ ] Investigate: a clamped continuous PID with D = 0 chatters (Zeno guard, 30 s) when its unused derivative
      filter state is frozen, but not when it moves: make the sliding mode at the limit robust
- [x] Simulation stop block and assertions
- [x] First performance pass: precomputed execution tables, scalar fast paths (~25 % faster)
- [ ] Performance: avoid per-step Python overhead (vectorised execution, Numba, or simulate the generated C:
      "accelerator mode")

## Phase 13 – Data types and fixed-point (required for ECU code)
- [x] Integer types (int8/16/32, uint8/16/32), boolean, single
- [x] Fixed-point with slope and bias scaling, overflow and saturation modes, rounding
- [x] Data type propagation and checking across the diagram
- [x] Simulation that matches the integer behaviour of the generated code bit for bit
- [ ] Data dictionary: signal and parameter objects with type, unit, range, description
- [ ] Integer-only arithmetic in generated code (no floating point between conversions), for targets without
      an FPU
- [ ] Typed parameters (e.g. int16 calibration maps) and typed A2L characteristics

## Phase 14 – State machines
- [x] State chart block (a Stateflow-like subset): states, transitions, guards, entry/during/exit actions,
      locals, `after(n)`, `t_in_state`, defined in a small text language
- [ ] Hierarchical (nested) and parallel states, events, history junctions
- [ ] Graphical state-chart editor
- [x] C code generation for charts (back-to-back tested with zero tolerance)
- [ ] Example: gear-shift logic, engine operating modes (crank, idle, run, fuel cut-off)

## Phase 15 – Automotive and ECU learning library
- [x] Mean-value engine model: throttle and intake manifold, air mass flow, torque production, crank dynamics
      (example `idle_speed_control.py`)
- [x] Turn the engine model into reusable library subsystems (`examples/library/engine_parts.nervlib`)
- [x] Fuel control: injector model, lambda (AFR) closed-loop control, short and long term fuel trim
      (`examples/lambda_control.py`, tutorial)
- [ ] Fuel control, more: wall wetting (x-tau), narrow-band switching sensor, LTFT maps per load/speed cell
- [ ] Ignition timing from speed/load maps, knock retard
- [x] Idle speed control (PI + base opening + AC feed-forward), with tutorial
- [ ] Electronic throttle control (DC motor, return spring, PID)
- [x] Vehicle longitudinal dynamics: aero and rolling resistance, force and power limits, brakes
      (`examples/drive_cycle.py`)
- [ ] Vehicle dynamics, more: driveline with gearbox and shift logic, tire slip, road grade, engine efficiency map
- [x] Driver model and the ECE-15 drive cycle (tutorial); other cycles from CSV files
- [ ] Bundled WLTP / FTP-75 tables (from the official sources) and a drive-cycle block
- [ ] Sensor and actuator models: quantisation, noise, delay, faults
- [ ] Truck-specific models: heavy-duty diesel, exhaust brake, AMT gearbox
- [ ] Tutorial series: "Learn engine control with Nervus" (first: idle speed control)

## Phase 16 – Control design and analysis tools
- [x] Linearise a model around an operating point (state-space / transfer function)
- [x] Trim: find steady states
- [x] Bode and step plots; poles, DC gain, stability margins
- [ ] Nyquist and pole-zero plots, root locus, closed-loop analysis from the model
- [ ] PID auto-tuning against a linearised plant
- [ ] Scripting console in the GUI (Python, with the model and results in scope)

## Phase 17 – ECU integration and calibration
- [x] CAN: read DBC files (`cantools`), CAN Pack / CAN Unpack blocks, Intel and Motorola, bit-exact C code
- [ ] CAN FD, multiplexed signals, value tables, DBC signals as workspace variables
- [x] A2L file generation for calibration tools (measurements and characteristics), addresses from `nm`
- [ ] XCP-on-CAN basics for live measurement and calibration
- [ ] Target: a development board (e.g. STM32 or ESP32 with CAN), as a scheduler template and HAL stubs
- [ ] Processor-in-the-loop (PIL) testing
- [ ] Hardware-in-the-loop (HIL): run the plant model in real time against a real ECU

## Phase 18 – Interoperability
- [ ] FMI 2.0/3.0: import FMUs as blocks (`fmpy`), export models as FMUs
- [ ] Import a subset of Simulink `.slx`/`.mdl` (useful for comparing against work models)
- [ ] Export results to MAT files (`scipy.io`) for MATLAB users

## Phase 19 – Quality, testing and release
- [x] Model coverage: decision outcomes of switches, comparisons, limits, lookups and charts; HTML report;
      shown in the Test Manager
- [ ] Condition/MC-DC coverage for logic, coverage of generated C (gcov)
- [ ] Requirements traceability (link requirements to blocks and tests)
- [x] Model Advisor: 10 rules (float equality, division, anti-windup, implicit sampling, chart reachability, ...)
- [ ] Packaging: PyPI release, standalone installers (PyInstaller / Briefcase) for macOS, Windows and Linux
- [ ] Versioned docs, release notes; publish docs to GitHub Pages

## Phase 20 – Electrical and physical modelling
*Acausal (equation-based) components connected by physical wires, like Simscape Electrical.*
- [ ] Electrical network solver: components with pins, Kirchhoff's laws assembled automatically (modified nodal
      analysis), solved together with the block diagram (DAE)
- [ ] Basic components: resistor, capacitor, inductor, voltage and current sources (controlled by signals),
      ground, ideal switch, diode
- [ ] Sensors: voltage and current measurement as signals
- [ ] Automotive electrics: battery (open-circuit voltage map + internal resistance), DC motor, H-bridge with PWM
      (averaged), solenoid / injector, relay coil, glow plug, alternator
- [ ] Throttle body and electronic throttle with a real DC motor and H-bridge instead of a first-order lag
- [ ] Other physical domains on the same solver: rotational mechanics (inertia, spring, damper, gear), thermal
      (heat capacity, conduction, convection), hydraulic/fluid basics
- [ ] Editor: physical ports and wires drawn differently from signal lines; component library; examples and
      tutorials (battery + starter motor, electronic throttle)

## Phase 21 – CAN bus networks
*Several ECUs exchanging messages over a simulated bus.*
- [ ] CAN bus block: frames with IDs, periods and DLC from DBC files; arbitration by priority; bit timing and bus
      load; transmission delay
- [ ] ECU nodes as subsystems with CAN Rx/Tx ports; periodic and event-triggered transmission
- [ ] Rest-bus simulation: generate the messages of ECUs that are not modelled, from the DBC file
- [ ] Gateways between buses (e.g. powertrain and body CAN)
- [ ] Fault injection: lost frames, delays, wrong values, bus-off; checksums and alive counters (AUTOSAR E2E
      style) with C code
- [ ] Bus trace view (frames over time) and export to standard log formats (ASC/BLF)
- [ ] Connect to real hardware through `python-can` (PEAK, Kvaser, Vector, SocketCAN) for HIL-style tests

## Phase 22 – OBD-II: read data from a real car
*Record live data and trouble codes from a vehicle's OBD-II port and use them in models and tests.*
- [x] Decode standard SAE J1979 mode 01 PIDs (rpm, speed, temperatures, MAF, MAP, throttle, load, fuel trims, ...)
- [x] ELM327 adapter client (USB/Bluetooth serial): initialise, query supported PIDs, poll PIDs
- [x] Record a drive into a result file (`.nervres`) / CSV: replay as test inputs, compare with models in the
      Data Inspector
- [x] Read diagnostic trouble codes (stored 03, pending 07, permanent 0A), freeze frame (02), VIN (09);
      clearing (04) deliberately left out: it resets the emissions readiness monitors
- [ ] OBD over a CAN interface (`python-can`, ISO-TP / ISO 15765-4) without an ELM327
- [ ] Editor: Tools → Record from OBD-II… with live plots
- [ ] OBD responder in models: a simulated ECU that answers OBD requests (to test diagnostic tools)
- [ ] Diagnostic logic in models: DTC setting/debouncing, MIL lamp, readiness monitors

## Safety note

Nervus only *reads* from vehicles over OBD-II; it never writes to ECUs. Code generated by this tool is for learning, bench and off-road experiments. Do not run it on a vehicle on public
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
