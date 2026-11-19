# Model workspace and calibrations

Engine control software is *code plus calibration*. Nervus keeps the two apart: block parameters can refer
to named **workspace variables**, and the values of those variables can be saved and loaded as **parameter
sets** (`.nervcal` files).

![The Model Workspace panel](images/workspace-panel.png)

## Variables

Each variable has a name, a value, and optional unit, minimum, maximum and description. A value can be:

- a number: `1.5`
- a vector or matrix: `[1 2 3]`, `[1 2; 3 4]` (MATLAB style) or `[[1, 2], [3, 4]]`
- an expression of variables defined **above** it: `Kp / Ti`, `2*pi*f_c`

Values outside `[min, max]` are reported as warnings in Diagnostics. These ranges will also go into the A2L
calibration file once that exists (see the [roadmap](https://github.com/ikjbi/nervus/blob/main/plan.md)).

## Block parameters as expressions

Any numeric parameter (numbers, vectors, matrices, sample times) can be an expression of workspace
variables:

```python
from nervus import Diagram
from nervus.blocks import DiscretePID, Gain, ZeroOrderHold
from nervus.core import Variable

d = Diagram()
d.workspace.add(Variable("Kp", 1.5, "Proportional gain", "%/°", min=0))
d.workspace["Ti"] = 0.04
d.workspace["Ts"] = 0.01
pid = d.add(DiscretePID(P="Kp", I="Kp/Ti", sample_time="Ts"))
```

Expressions are stored in the model file exactly as written and evaluated every time the model is compiled.
In the editor, the canvas shows the expression (e.g. `Kp`) instead of the number:

![The throttle example: blocks refer to workspace variables](images/workspace.png)

Expressions may use `+ - * / ** %`, the functions `sqrt`, `exp`, `log`, `sin`, `cos`, `abs` and the
constants `pi`, `e`, `inf`, `true` and `false`. Comparisons (`==`, `!=`, `<`, `<=`, `>`, `>=`) and `and`, `or`, `not` give 1 (true)
or 0 (false), so `Kp * (MODE == 2)` works. The MATLAB spellings `~=`, `&&`, `||` and `~` are accepted too.

## Calibration maps over shared axes

ECU software is full of curves and maps over the same few axes: engine speed, load, coolant temperature.
For one map, use a **1-D** or **2-D Lookup Table**. When several maps share an axis, use a **Prelookup**
block per axis and an **Interpolation using Prelookup** block per map: the breakpoint search runs once, and
every map reuses its result (index *k* and fraction *f*).

![Prelookup and Interpolation](images/blocks/prelookup.png)

Put the axes and tables in the workspace, so they can be calibrated and swapped with parameter sets:

```python
d.workspace["speed_axis"] = [800, 1500, 3000, 6000]  # rpm
d.workspace["load_axis"] = [0.2, 0.5, 1.0]
d.workspace["ign_map"] = [[10, 8, 5], [20, 16, 10], [30, 25, 18], [35, 30, 22]]  # ° before TDC
speed = d.add(Prelookup(breakpoints="speed_axis"))
load = d.add(Prelookup(breakpoints="load_axis"))
ign = d.add(Interpolation(dimensions=2, table="ign_map"))  # inputs: k1, f1, k2, f2
```

The result is identical to a 2-D Lookup Table with linear interpolation, in the simulation and in the
generated C. Hover over the Interpolation block's ports to see which input is which.

## Parameter sets

```python
from nervus import ParameterSet, load, simulate

d = load("examples/throttle_pi.nervus")
ParameterSet.from_workspace(d.workspace, "baseline").save("baseline.nervcal")

d.workspace.apply(ParameterSet.load("examples/throttle_tight.nervcal").values)
res = simulate(d)

res = simulate(d, params={"Kp": 2.0})  # temporary override for a single run
```

A `.nervcal` file is plain JSON:

```json
{
  "format": "nervus-parameters",
  "schema_version": 1,
  "name": "tight",
  "description": "Higher gains: less overshoot",
  "values": {"Kp": 3.0, "Ki": 80.0}
}
```

In the editor, use **Load set…** / **Save set…** in the Model Workspace panel. Loading is a single undo step.
