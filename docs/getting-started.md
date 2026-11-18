# Getting started

## Install

Nervus needs Python 3.11 or newer. The project uses [uv](https://docs.astral.sh/uv/):

```bash
git clone git@github.com:ikjbi/nervus.git
cd nervus
uv sync                       # the engine
uv sync --extra gui           # + the desktop editor (PySide6)
uv sync --extra plot          # + matplotlib for the example plots
```

## The editor

`uv run nervus` starts the desktop editor; see [The editor](editor.md). The rest of this page builds a model
in Python.

## Your first model

A model is a **diagram** of **blocks** connected by **signal lines**. This builds the first-order system
$\tau \dot y = u - y$ with $\tau = 0.5$ s:

```python
from nervus import Diagram, simulate
from nervus.blocks import Gain, Integrator, Scope, Step, Sum

d = Diagram("first_order")
u = d.add(Step(time=0.0, final=1.0), name="u")
err = d.add(Sum(signs="+-"), name="err")  # err = u - y
k = d.add(Gain(gain=1 / 0.5), name="1/tau")
y = d.add(Integrator(), name="y")
scope = d.add(Scope(num_inputs=2), name="scope")

d.connect(u, err.in_port(0))
d.connect(y, err.in_port(1))  # feedback
d.chain(err, k, y)  # err -> 1/tau -> y
d.connect(u, scope.in_port(0))
d.connect(y, scope.in_port(1))

res = simulate(d, t_final=3.0)
print(res.t[-1], res["y"][-1])
```

- `d.add(block, name=...)` adds a block. Names must be unique; one is generated if you leave it out.
- `d.connect(src, dst)` draws a line. A block on its own means port 0; use `block.in_port(i)` /
  `block.out_port(i)` (or a `(block, i)` tuple) for other ports.
- `d.chain(a, b, c)` connects `a → b → c` through port 0.

## Results

`simulate` returns a `SimResult`:

```python
res.t  # time points
res["y"]  # output of block "y"  (shape (N,) for scalars, (N, width) for vectors)
res["demux:1"]  # output port 1 of block "demux"
res.inputs("scope")  # the signals going into the scope
res.to_csv("out.csv")
res.to_dataframe()  # needs pandas
```

## Saving and loading

```python
from nervus import load, save

save(d, "first_order.nervus")
d2 = load("first_order.nervus")
```

Model files are plain JSON. See [Model files](model-files.md).

## Simulation settings

Each diagram stores its own settings, which `simulate` uses unless you override them:

```python
d.settings.t_final = 5.0
d.settings.solver = "rk4"  # fixed step
d.settings.step = 1e-3
res = simulate(d)
res = simulate(d, t_final=1.0, solver="LSODA")  # one-off override
```

See [Concepts](concepts.md#solvers) for how to choose a solver.

## Examples

The [`examples/`](https://github.com/ikjbi/nervus/tree/main/examples) folder has complete models:

- `mass_spring_damper_pid.py`: continuous PID position control with actuator limits.
- `throttle_pi.py`: electronic throttle control with a 10 ms discrete PI controller, as on an ECU, with its
  gains as workspace variables and a second calibration file.
- `coolant_fan.py`: radiator fan on/off control with a filtered sensor, a hysteresis relay and a lookup table.
