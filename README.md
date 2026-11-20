# Nervus

**Open-source block-diagram modeling and simulation in Python — an alternative to Simulink.**

*Nervus* is Latin for *nerve*. An engine control unit (ECU) is a vehicle's nervous system, and Nervus aims to be a
tool for designing, simulating and eventually generating C code for that kind of control software.

![The Nervus editor](docs/images/editor.png)

> **Status: pre-alpha.** The simulation engine and core blocks are under active development. See
> [`plan.md`](plan.md) for the roadmap.

## Goals

- A **headless simulation engine** in pure Python (NumPy/SciPy) that can be scripted, tested and run in CI.
- A **clean, modern desktop editor** built with PySide6 (Qt), using a Model–View–Controller architecture.
- A **block library** for control engineering, with automotive blocks such as engine and vehicle dynamics models,
  lookup tables and state machines.
- **C code generation** for embedded targets (ECUs), verified against the Python simulation (working:
  see below).
- **Git-friendly model files**: plain JSON that can be diffed and reviewed.

## What Nervus can do

| Area | Features | Guide |
|---|---|---|
| Editor | block library with search, drag and drop, wires that route around blocks, undo, copy/paste, subsystems, flip/rotate/resize, auto layout, light and dark theme, F1 help with equations for every block, a Python **console** with the model in scope | [Editor](docs/editor.md) |
| Simulation | continuous, discrete and multirate models; fixed-step and variable-step solvers (also stiff: BDF); zero-crossing detection; an algebraic loop solver; real-time pacing; live scopes | [Concepts](docs/concepts.md) |
| Parameters and data | model workspace with units, limits and data types; expressions; calibration sets (`.nervcal`); a **data dictionary** of signal objects (type, unit, range) bound to named wires | [Workspace](docs/workspace.md) |
| Structure | subsystems, masks, enabled/triggered/function-call subsystems, atomic ECU tasks with their own period, variants, linked component libraries | [Subsystems](docs/subsystems.md), [Libraries](docs/libraries.md) |
| Logic | State Chart block: nested and parallel states, history, events, guards, timers, calibration parameters | [State machines](docs/statecharts.md) |
| Physical modelling | electrical, rotational, thermal and hydraulic networks connected like real parts; batteries, motors, solenoids, injectors, relays, alternator, glow plugs | [Physical modelling](docs/physical.md) |
| Electronics | LTspice-style circuit simulation: diodes, BJTs, MOSFETs, op-amps, switches; operating point and DC sweeps; SPICE netlist import and export | [Physical modelling](docs/physical.md), [Tutorial 11](docs/tutorials/circuits.md) |
| Automotive models | mean-value engine, vehicle and driveline, tyres (magic formula), automatic and automated gearboxes, sensor and actuator models, diagnostic monitors with DTCs, adaptive maps, the official **WLTC and FTP-75 drive cycles** | [Tutorials](docs/tutorials/index.md) |
| ECU code | C code generation (multirate, calibratable parameters, A2L file, HTML report), fixed-point data types, software-in-the-loop check | [C code](docs/codegen.md), [Data types](docs/datatypes.md) |
| Vehicle networks | CAN Pack/Unpack with DBC files (also **CAN FD**, multiplexed signals, value tables); **simulated CAN buses** with arbitration, bus load, gateways, rest-bus simulation, fault injection and E2E protection; bus trace with ASC/BLF export; real CAN adapters through python-can | [CAN](docs/can.md) |
| Measurement and calibration | **XCP on CAN**: calibrate a running model from INCA/CANape or Python, or a real ECU from Python; **MDF4** (`.mf4`) import and export | [CAN: XCP](docs/can.md#xcp-live-measurement-and-calibration), [Testing](docs/testing.md) |
| OBD-II | live data and trouble codes from a real car (ELM327 or CAN), and a simulated ECU to practise with | [OBD-II](docs/obd.md) |
| Testing | test cases stored with the model, Test Manager, Data Inspector, parameter sweeps and Monte Carlo runs, model coverage, **requirements traceability**, Model Advisor | [Testing](docs/testing.md), [Verification](docs/verification.md) |
| Analysis | linearisation, trim, Bode, Nyquist, root locus, stability margins, step response, PID tuning | [Analysis](docs/analysis.md) |
| Learning | 12 tutorials from your first model to CAN networks, each with a finished example model | [Tutorials](docs/tutorials/index.md) |

## Installation (development)

Nervus uses [uv](https://docs.astral.sh/uv/) to manage the environment.

```bash
git clone git@github.com:ikjbi/nervus.git
cd nervus
uv sync                 # engine + dev tools
uv sync --extra gui     # also install the desktop editor (PySide6, pyqtgraph, matplotlib)
uv sync --all-extras    # everything: editor, CAN/DBC (cantools), OBD-II (pyserial), MDF4 (asammdf)
```

## Learn Nervus

Start with [Tutorial 1: your first model](docs/tutorials/first-model.md): you build a cruise control in the
editor step by step, tune it, and meet integrator windup. Then pick a path in the
[tutorial overview](docs/tutorials/index.md):

| Path | Tutorials |
|---|---|
| Engine control | idle speed, lambda control and fuel trims, ignition and knock, wall wetting |
| Vehicle and driveline | drive cycles (WLTP, FTP-75), gear-shift logic, traction control, a truck on a mountain road |
| Electrics and electronics | starter motor and electronic throttle, electronic circuits |
| ECU communication | a vehicle network on CAN, OBD-II, XCP calibration |

Coming from MATLAB/Simulink? See [Coming from Simulink](docs/coming-from-simulink.md).

## The editor

```bash
uv run nervus examples/throttle_pi.nervus
```

Drag blocks from the library, connect ports, edit parameters, press **▶ Run** and look at the scopes. Press
**F1** on any block for its help page, with equations and figures. See [docs/editor.md](docs/editor.md).

<img src="docs/images/scope.png" width="600" alt="A scope window">

## C code for the ECU

Select the controller subsystem and choose **Code → Generate C Code**. You get `model.h`/`model.c` with
`model_initialize()` and `model_step()`, static memory only, and calibratable parameters. A
software-in-the-loop check compiles the code and compares it with the model step by step. See
[docs/codegen.md](docs/codegen.md) and the generated example in
[examples/generated/ECU](examples/generated/ECU).

## Test cases

Test cases are saved with the model: input scenarios, calibrations and pass/fail checks. Run them from the
**Test Manager** and compare runs in the **Data Inspector**, or from Python and pytest. See
[docs/testing.md](docs/testing.md).

## Quick start (Python)

```python
from nervus import Diagram, simulate
from nervus.blocks import Step, Sum, Gain, Integrator, Scope

# First-order system: dy/dt = (u - y) / tau
d = Diagram("first_order")
u = d.add(Step(time=0.0, final=1.0), name="u")
err = d.add(Sum(signs="+-"), name="err")
k = d.add(Gain(gain=1 / 0.5), name="1/tau")
y = d.add(Integrator(), name="y")
scope = d.add(Scope(num_inputs=2), name="scope")

d.connect(u, err.in_port(0))
d.connect(y, err.in_port(1))
d.chain(err, k, y)
d.connect(u, scope.in_port(0))
d.connect(y, scope.in_port(1))

res = simulate(d, t_final=3.0)
print(res["y"][-1])  # ≈ 1 - exp(-6)
```

More examples are in [`examples/`](examples/).

## Documentation

The user guide and block reference are in [`docs/`](docs/). To build them locally:

```bash
uv run --group docs mkdocs serve
```

## Development

```bash
uv run pytest          # tests
uv run ruff check .    # lint
uv run ruff format .   # format
uv run mypy            # type check
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Safety

Code generated by Nervus is for learning, bench testing and off-road experiments. **Do not run it on a vehicle on
public roads.** Production automotive software requires ISO 26262 processes, qualified tools and certified code.

## License

[MIT](LICENSE)
