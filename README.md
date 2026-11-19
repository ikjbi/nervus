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
| Editor | block library, drag and drop, wires, undo, copy/paste, right-click menus, flip blocks, auto layout, light/dark theme, F1 help for every block | [Editor](docs/editor.md) |
| Simulation | continuous, discrete and multirate models; fixed-step and variable-step solvers; zero-crossing detection; stop and assertion blocks | [Concepts](docs/concepts.md) |
| Parameters | model workspace with units and limits, expressions, parameter sets (`.nervcal`), parameter sweeps from Python | [Workspace](docs/workspace.md) |
| Structure | subsystems, masks, enabled/triggered subsystems, atomic tasks with their own period, variants, component libraries | [Subsystems](docs/subsystems.md), [Libraries](docs/libraries.md) |
| Logic | State Chart block (states, transitions, guards, timers) | [State machines](docs/statecharts.md) |
| ECU code | C code generation (multirate, calibratable parameters, A2L file, HTML report), fixed-point data types, software-in-the-loop check | [C code](docs/codegen.md), [Data types](docs/datatypes.md) |
| Testing | test cases stored with the model, Test Manager, Data Inspector, results files, model coverage, Model Advisor | [Testing](docs/testing.md), [Verification](docs/verification.md) |
| Analysis | linearisation, trim, Bode, stability margins, step response | [Analysis](docs/analysis.md) |
| Vehicle networks | CAN Pack/Unpack with DBC files; OBD-II live data and trouble codes from a real car | [CAN](docs/can.md), [OBD-II](docs/obd.md) |
| Learning | examples and tutorials: idle speed control, lambda control and fuel trims, a car on a drive cycle, gear-shift logic | [Tutorials](docs/tutorials/idle-speed-control.md) |

## Installation (development)

Nervus uses [uv](https://docs.astral.sh/uv/) to manage the environment.

```bash
git clone git@github.com:ikjbi/nervus.git
cd nervus
uv sync                 # engine + dev tools
uv sync --extra gui     # also install the desktop editor (PySide6, pyqtgraph, matplotlib)
```

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
