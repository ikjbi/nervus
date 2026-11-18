# Using the editor

## Window layout

| Area | What it does |
|---|---|
| **Library** (left) | All blocks, grouped by category. Type in the search box to filter. Drag a block onto the canvas or double-click it. Hover for a short description. |
| **Canvas** (centre) | The diagram. |
| **Properties** (right) | Parameters of the selected block. Press **?** for the block's help. |
| **Model Workspace** (bottom, tab) | Named parameters that blocks can use. See *Workspace and calibrations*. |
| **Diagnostics** (bottom) | Problems in the model, such as unconnected inputs or algebraic loops. Click an entry to select the blocks involved. |

Panels can be moved, closed and reopened from the **View** menu.

## Blocks

- **Select**: click, or drag a rectangle on empty canvas. Shift-click adds to the selection.
- **Move**: drag. Blocks snap to a 10-pixel grid.
- **Rename**: edit *Name* in the Properties panel. Names must be unique.
- **Delete**: Delete or Backspace.
- **Copy / cut / paste**: ⌘C / ⌘X / ⌘V (Ctrl on Windows and Linux). Lines between copied blocks are
  copied too.
- **Double-click**: opens the Properties panel, or the plot window for a Scope.

## Lines (signals)

- Drag from an **output port** (right side, ▸) to an **input port** (left side). You can also start from an
  input and drag backwards to an output.
- An output can feed many inputs (a dot marks the branch). An input has exactly one source. Connecting a
  new line to an input that is already used replaces the old line.
- Click a line to select it; Delete removes it.

## Editing parameters

Numeric fields accept:

| You type | Meaning |
|---|---|
| `0.5`, `-1e-3` | numbers |
| `2*pi`, `1/0.05`, `sqrt(2)` | arithmetic; `pi`, `e`, `inf` are known |
| `[1 2 3]` or `[1, 2, 3]` | vectors |
| `[1 2; 3 4]` | matrices (rows separated by `;`, as in MATLAB) |
| `Kp`, `1/tau`, `2*Kp` | workspace variables and expressions of them |

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

## Themes

**View → Theme** switches between light and dark, or follows the system setting.
