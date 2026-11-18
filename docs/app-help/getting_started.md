# Getting started

Nervus models a system as a **block diagram**: blocks are small dynamic systems (a gain, an integrator, a
PID controller), and the lines between them carry signals.

## Build your first model in 5 steps

1. **Add blocks.** Drag a block from the **Library** (left) onto the canvas, or double-click it in the
   library. Add a *Step*, a *Transfer Fcn* and a *Scope*.
2. **Connect them.** Press on a block's **output port** (the small triangle on its right side) and drag to
   another block's **input port** (left side). Releasing on the body of a block connects to its first free
   input.
3. **Set parameters.** Select a block and edit its parameters in the **Properties** panel (right).
   Values accept expressions like `2*pi`, `1/0.05` and matrices like `[1 2; 3 4]`.
4. **Run.** Press **▶ Run** (⌘R / Ctrl+R or F5). The stop time is in the toolbar.
5. **Look at the result.** Scope windows open after the first run. Double-click a Scope block to reopen
   it. Hover over the plot to read values.

## Where to go next

- **Using the editor**: selecting, moving, copying and undoing.
- **Running simulations**: solvers, sample times and what to do when something goes wrong.
- **Block reference**: every block, its equation and parameters. Select a block and press **F1** to
  jump to its page.

The `examples` folder in the repository has complete models you can open with **File → Open**, for
example `throttle_pi.nervus`, an electronic throttle controller running as a 10 ms ECU task.
