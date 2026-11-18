# Running simulations

Press **▶ Run** (⌘R / Ctrl+R / F5). While a simulation runs, the diagram is locked and **■ Stop** ends the
run early; the data up to that point is kept.

## Stop time and solver

The stop time is in the toolbar. **Simulation → Simulation Settings…** (⌘E) has the rest:

| Solver | Use for |
|---|---|
| **auto / RK45** | The default. Picks its own step size. |
| **RK23**, **DOP853** | Lower / higher accuracy than RK45. |
| **Radau**, **BDF**, **LSODA** | *Stiff* models, with very fast and very slow dynamics together. |
| **rk4** (fixed step) | Models that will become ECU code. Every step has the same size. |
| **euler** (fixed step) | The simplest method. |

Variable-step solvers stop exactly at discontinuities that blocks announce (the time of a Step, the edges
of a Pulse). Fixed-step solvers need a step that divides every discrete sample time; leave it empty and
Nervus chooses one.

## Sample times

Discrete blocks (Unit Delay, Zero-Order Hold, Discrete PID, ...) have a **sample_time** in seconds: they
compute a new output every *T* seconds and hold it in between, just like a task on an ECU. `-1` means
*inherit from the input*, `0` means continuous.

## Scopes

Every Scope opens after the first run. Each input gets its own colour, always in the same order. Hover over
the plot to read values at that time. Drag to pan, scroll to zoom, and press *Autoscale* to reset.
*Show samples* marks the computed points, which is useful for discrete signals.

## When something is wrong

Problems appear in **Diagnostics** and the blocks involved get a red outline. Common ones:

- **"input 0 of 'X' is not connected"**: every input needs a line. Use a *Constant* with value 0 if you
  really want zero.
- **Algebraic loop**: a feedback loop made only of blocks whose output depends directly on their input
  (Gain, Sum, ...). Put an *Integrator* (continuous) or *Unit Delay* (discrete) in the loop.
- **"needs a discrete sample time"**: a Unit Delay that inherits from a continuous signal. Give it a
  sample time, or put a Zero-Order Hold in front.
- **"fixed step does not divide the sample time"**: choose a step such as 0.001 for a 0.01 s controller.
