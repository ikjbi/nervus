# Architecture

```
nervus/
  core/      Block, ports, Param, SampleTime, Diagram, SimulationSettings, errors   (pure Python)
  blocks/    the block library and the registry (type_id -> class)
  sim/       compiler (diagram -> CompiledModel), simulator loop, SimResult
  solvers/   fixed-step (Euler, RK4) and variable-step (SciPy solve_ivp) integration
  io/        model file load/save, schema migration
  help.py    block help / reference generation
  gui/       (coming) PySide6 desktop editor, Model-View-Controller
```

**Rule:** nothing outside `nervus.gui` imports Qt. The engine must run headless in scripts, tests and CI.

## Data flow

```
Diagram ──compile_diagram()──▶ CompiledModel ──simulate()──▶ SimResult
 (editable)                    (sorted, sized, states        (time + logged signals)
                                allocated; executable)
```

### Compilation (`nervus.sim.compiler`)

1. `Diagram.check()`: every input connected, no dangling ports.
2. **Width propagation**: repeatedly ask each block `output_widths(input_widths)` until nothing changes.
   Blocks with state (Integrator, Unit Delay) give a provisional width so feedback loops resolve.
3. `configure(in_widths, out_widths)` on each block, which validates sizes.
4. **Sorting**: a topological sort over direct-feedthrough edges. A cycle is an algebraic loop.
5. **Sample times**: inherited (`-1`) times are resolved from the drivers.
6. **States**: the continuous states of all blocks are packed into one vector for the solver. Discrete
   states are kept per block.

The `CompiledModel` is also where C code generation will start: it holds a sorted list of blocks with known
sizes, rates and states.

### Simulation (`nervus.sim.simulator`)

The simulator owns all state. Blocks are **pure**: `outputs`, `derivatives` and `update` get the state passed
in and return new values. This lets variable-step solvers evaluate trial points and throw them away, and it
maps directly onto generated C (`model_step()` with a state struct).

Discrete rates are scheduled with integer counters (`offset + k·period`), so sample hits never drift.

## GUI (Model-View-Controller), coming in Phase 5

- **Model**: Qt adapters around `Diagram` that emit signals (`blockAdded`, `paramChanged`, ...).
- **View**: `QGraphicsScene` canvas, palette, property editor, scope windows. They render and forward input.
- **Controller**: turns user intent into `QUndoCommand`s on the model, and runs simulations in a worker
  thread.
