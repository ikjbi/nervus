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

## Parameters

Blocks inside subsystems can use the model workspace variables, just like blocks at the top level.
