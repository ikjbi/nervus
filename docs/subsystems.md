# Subsystems

A **subsystem** is a block that contains its own diagram. Subsystems structure a model the way functions
structure code. In ECU work, each subsystem is typically one software function (throttle control, fuel,
ignition), and the generated C code will follow that structure.

Here the throttle example is grouped so that everything running on the ECU (sensor sampling, error and
PI controller) is inside one subsystem:

![The throttle model with an ECU subsystem](images/subsystem-outer.png)

Double-click it to open it. The breadcrumb bar shows the path back to the model:

![Inside the ECU subsystem](images/subsystem-inner.png)

## In the editor

| Action | How |
|---|---|
| Group blocks into a subsystem | select them, **Edit → Create Subsystem from Selection** (⌘G / Ctrl+G) |
| Open a subsystem | double-click it |
| Go back up | click a breadcrumb, or **View → Up to Parent** (⌘↑ / Ctrl+Up) |
| Add an empty subsystem | **Library → Ports & Subsystems → Subsystem** |

Lines crossing the selection boundary become **In**/**Out** ports. Undo works across levels and opens the
subsystem where the change is undone.

## In Python

```python
from nervus import Diagram, simulate
from nervus.blocks import Gain, Inport, Integrator, Outport, Scope, Step, Subsystem, Sum

plant = Diagram("plant")
u = plant.add(Inport(port=1), name="u")
e = plant.add(Sum(signs="+-"), name="e")
k = plant.add(Gain(gain="1/tau"), name="k")      # uses the model workspace
y = plant.add(Integrator(), name="y")
plant.connect(u, (e, 0))
plant.connect(y, (e, 1))
plant.chain(e, k, y, plant.add(Outport(port=1), name="y_out"))

model = Diagram("model")
model.workspace["tau"] = 0.5
sub = model.add(Subsystem(system=plant), name="plant")
model.chain(model.add(Step(time=0.0)), sub, model.add(Scope()))

res = simulate(model, 2.0)
res["plant/y"]            # blocks inside subsystems are named by path
```

## How it works

Before simulation, the compiler **flattens** the hierarchy. The In and Out blocks inside subsystems become
identity nodes, so sorting, signal widths and sample times work across subsystem boundaries exactly as in a
flat model. Every block keeps its path name for results and error messages.

In model files, a subsystem block carries its diagram in a nested `"system"` entry (schema version 3).
