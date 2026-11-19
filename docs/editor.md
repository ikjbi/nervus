# The editor

Start the desktop editor with:

```bash
uv sync --extra gui
uv run nervus                         # empty model
uv run nervus examples/throttle_pi.nervus
```

![The Nervus editor with the throttle-control example](images/editor.png)

| Area | What it does |
|---|---|
| **Toolbar** | New / open / save, undo / redo, fit to window, **▶ Run** and **■ Stop**, the stop time, and the simulation settings. |
| **Library** (left) | All blocks by category, with search. Drag a block onto the canvas or double-click it. |
| **Canvas** (centre) | The diagram. Drag from an output port (▸ on the right of a block) to an input port to draw a line. |
| **Properties** (right) | Parameters of the selected block. Fields accept expressions (`2*pi`) and MATLAB-style matrices (`[1 2; 3 4]`). |
| **Model Workspace** (bottom, tab) | Named parameters (calibration data) that block parameters can use, and parameter sets. See [Workspace and calibrations](workspace.md). |
| **Test Manager** (bottom, tab) | Test cases saved with the model; run them and see pass/fail. See [Test cases and results](testing.md). |
| **Diagnostics** (bottom) | Problems such as unconnected inputs or algebraic loops. Click one to select the blocks involved; they also get a red outline. |

Dark mode follows the system setting, or choose it under **View → Theme**:

![The editor in dark mode](images/editor-dark.png)

## Blocks

- **Select**: click, or drag a rectangle on empty canvas. Shift-click adds to the selection.
- **Move**: drag. Blocks snap to a 10-pixel grid.
- **Rename**: edit *Name* in the Properties panel, or right-click → *Rename…*. Names must be unique.
- **Delete**: Delete or Backspace.
- **Copy / cut / paste**: ⌘C / ⌘X / ⌘V (Ctrl on Windows and Linux). Lines between copied blocks are
  copied too.
- **Double-click**: opens a subsystem, the plot window of a Scope, or the Properties panel for other blocks.
- **Flip**: Ctrl+Shift+F swaps the input and output sides (see below).

## Lines (signals)

- Drag from an **output port** (right side, ▸) to an **input port** (left side). You can also start from an
  input and drag backwards to an output.
- An output can feed many inputs (a dot marks the branch). An input has exactly one source. Connecting a
  new line to an input that is already used replaces the old line.
- Click a line to select it; Delete (or right-click → *Delete Wire*) removes it.
- **Hover over a port** to see which input it is, e.g. *input 2: reset (rising)* on a Discrete-Time
  Integrator with an external reset, or *k1*, *f1* on an Interpolation block.

## Editing parameters

Numeric fields accept:

| You type | Meaning |
|---|---|
| `0.5`, `-1e-3` | numbers |
| `2*pi`, `1/0.05`, `sqrt(2)` | arithmetic; `pi`, `e`, `inf` are known |
| `[1 2 3]` or `[1, 2, 3]` | vectors |
| `[1 2; 3 4]` | matrices (rows separated by `;`, as in MATLAB) |
| `Kp`, `1/tau`, `2*Kp` | workspace variables and expressions of them |
| `Kp * (MODE == 2)`, `A > 1 && B ~= 0` | comparisons and logic give 1 or 0 (MATLAB `~=`, `&&`, `\|\|`, `~` work too) |

Press Enter or leave the field to apply. If a value is invalid the field turns red and the old value is
kept.

## Tidying up

**Edit → Auto Layout** (⇧⌘L / Ctrl+Shift+L) arranges the blocks of the shown diagram from left to right
in signal-flow order. It can be undone like any other edit.

## Undo

Every change, including moves, can be undone with ⌘Z and redone with ⇧⌘Z (Ctrl+Z / Ctrl+Y).

## Zoom and pan

- **Zoom**: ⌘/Ctrl + mouse wheel, trackpad pinch, or ⌘+ / ⌘−. **Fit to window**: ⌘0.
- **Pan**: two-finger scroll on a trackpad, the middle mouse button, or hold **Space** and drag.

## Right-click menus

Right-click a block, a wire or the empty canvas for the actions that fit it:

![The right-click menu of a subsystem](images/context-menu.png)

| On | Actions |
|---|---|
| a block | Rename, help, cut / copy / delete, create a subsystem from the selection; *Open Scope* for scopes |
| a subsystem | also *Open Subsystem*, *Edit Mask…*, *Variants…*, *Save Subsystem to Library…*, *Generate C Code…* (or *Break Library Link* when it is linked) |
| a wire | *Delete Wire* |
| the canvas | paste, select all, auto layout, fit to window, up to the parent system |

Right-clicking a block that is part of a selection keeps the selection, so *Delete* or *Create Subsystem*
act on all selected blocks.

## Flipping blocks for feedback paths

Feedback paths, such as a sensor signal going back to the controller, are easier to read when they run from
right to left. Select blocks and press **Ctrl+Shift+F** (**Edit → Flip Block**, or right-click → *Flip Block*):
their inputs move to the right side and their outputs to the left. Flipping only changes the drawing, and
it is saved with the model.

![The lambda sensor path drawn right to left with flipped blocks](images/lambda-model.png)

In Python, set `block.meta["flipped"] = True`.

## Running a simulation

Press **▶ Run** (⌘R / Ctrl+R / F5). The simulation runs in the background, so the window stays responsive,
and **■ Stop** ends it early. Every Scope opens after the first run. Hover over a plot to read the values
at that time:

![A scope window showing the throttle-control response](images/scope.png)

Solver, step size and tolerances are under **Simulation → Simulation Settings…** (⌘E):

![The simulation settings dialog](images/settings.png)

## Built-in help

**Help → Nervus Help** opens the guide and the full block reference inside the app. Select a block and press
**F1** (or **?** in the Properties panel) to jump straight to its page. Equations are typeset, and many blocks
have explanatory figures:

![Block help for the Gain block](images/help-gain.png)

The in-app guide pages are also available here:
[Getting started](app-help/getting_started.md) ·
[Using the editor](app-help/editor.md) ·
[Running simulations](app-help/simulation.md) ·
[Workspace and calibrations](app-help/workspace.md) ·
[Keyboard shortcuts](app-help/shortcuts.md)

## Troubleshooting

**"Could not find the Qt platform plugin"** on macOS: some tools mark every file inside `.venv` as *hidden*,
and Qt skips hidden plugin files. Nervus clears that flag automatically when it starts. If you start Qt some
other way, run `chflags -R nohidden .venv`.
