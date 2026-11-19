# Subsystems

A **subsystem** is a block that contains its own diagram, the way a function contains code. Use one per
ECU function ("idle control", "fuel", "ignition") or to keep a plant model tidy.

## Creating a subsystem

- **From a selection**: select blocks and choose **Edit → Create Subsystem from Selection** (⌘G / Ctrl+G).
  Lines that cross the selection boundary become the subsystem's **In** and **Out** ports automatically.
  This is one undo step.
- **From the library**: drag **Ports & Subsystems → Subsystem** onto the canvas. It starts with one In
  connected to one Out.

## Opening and navigating

- **Double-click** a subsystem to open it.
- The **breadcrumb bar** above the canvas shows where you are (`model › ECU › ...`). Click a level to
  go back, or use **View → Up to Parent** (⌘↑ / Ctrl+Up).
- Undo and redo work across levels. Undoing a change inside a subsystem opens that subsystem.

## Ports

The **In** and **Out** blocks inside a subsystem are its ports, ordered by their *port* parameter
(1, 2, ...). Their names are shown inside the subsystem block on the canvas. Port numbers must be
1, 2, 3, ... without gaps; Diagnostics reports problems.

At the **top level** of a model, In and Out blocks are the model's external inputs and outputs. When
simulating, a top-level In block outputs its *value* parameter. In generated C code they become the input
and output structs.

## Names in results and diagnostics

Blocks inside subsystems are named by their path: `ECU/throttle_pi`, `ECU/fuel/map`. Use those names to
read results (`res["ECU/throttle_pi"]`). Clicking a diagnostic opens the subsystem and selects the block. A
subsystem that contains an error is outlined in red.

## Enabled subsystems

Tick *enable_port* in a subsystem's Properties to give it an extra last input, **⏻ enable**. While the
enable is ≤ 0 nothing inside runs: outputs and discrete states are held, and continuous states stop. Use it for
functions that only run in some operating mode, e.g. idle speed control only while the engine idles. With
*when_enabled* = `reset`, the discrete states (counters, delays, integrators) restart from their initial
values each time the subsystem is enabled again. The enable is checked once per time step, and the
generated C code wraps the subsystem's blocks in `if (enabled)`.

## Masks: reusable components with parameters

A **masked** subsystem has its own parameters, like a function's arguments. The blocks inside use them in
their expressions, and each copy of the subsystem can have different values. This is how you build
reusable components such as an engine model with a `displacement` parameter.

Select a subsystem and press **Create Mask…** (or **Edit Mask…**) in the Properties panel:



- **Mask parameters**: name, value, unit and description. Values can be numbers, vectors, or expressions of
  model workspace variables (`3 * base`).
- **Icon text**: shown on the block; `\n` starts a new line.
- **Description**: shown in the Properties panel.

The parameters then appear in the Properties panel of the subsystem, like the parameters of any block:



Names are looked up from the inside out: a block sees the parameters of the nearest mask first, then those
of outer masks, then the model workspace. In generated C, mask parameters are per-instance values. Only bare
**model workspace** variables become shared calibration parameters.

```python
from nervus.core import Variable

engine = Subsystem(system=engine_diagram)
engine.mask.add(Variable("displacement", 1.6e-3, "Swept volume", "m³"))
engine.mask_icon = "Engine\\n1.6 l"
```

## Parameters

Blocks inside subsystems can use the model workspace variables, just like blocks at the top level.
