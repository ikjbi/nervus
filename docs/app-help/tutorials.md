# Tutorials

Each tutorial uses a finished model in `examples/`: open it in the editor, run it, read why it behaves as it
does, then change it. Every tutorial has the same parts:

- **At a glance**: what you will learn, what to do first, and how long it takes.
- **Follow along**: which model to open, and what to run and look at.
- **Experiments**: changes to try, each with the effect you should see.
- **Next**: where to go from there.

New to Nervus? Start with **Tutorial 1**, which builds a model from scratch in the editor, step by step with a
screenshot for each step. After that, follow the path that interests you; the *Before this* line of each
tutorial says what it builds on.

## Learning path

| # | Tutorial | Level | Time | You will learn |
|---|---|---|---|---|
| 1 | *Your first model: cruise control* | beginner | 30 min | the editor, blocks and wires, workspace variables, scopes, Data Inspector, PI control and windup |
| 2 | *Idle speed control* | beginner | 45 min | an engine model, feed-forward, test cases, C code |
| 3 | *Lambda control and fuel trims* | intermediate | 45 min | closed-loop fuel control, fuel trims, ECU tasks |
| 4 | *Ignition timing and knock control* | intermediate | 30 min | 2-D maps, knock control, noisy sensors |
| 5 | *Wall wetting and learned fuel trims* | intermediate | 30 min | fuel film dynamics, adaptive maps |
| 6 | *A car on a drive cycle* | beginner | 40 min | vehicle dynamics, driver model, WLTP and FTP-75 |
| 7 | *Gear-shift logic* | intermediate | 60 min | State Charts, shift schedules, hysteresis |
| 8 | *Tyre slip and traction control* | intermediate | 30 min | tyre models, slip control |
| 9 | *A truck on a mountain road* | intermediate | 30 min | automated gearbox, exhaust brake |
| 10 | *Starter motor and electronic throttle* | intermediate | 45 min | physical modelling: circuits, shafts, springs |
| 11 | *Electronic circuits* | advanced | 45 min | LTspice-style circuit simulation, SPICE netlists |
| 12 | *A vehicle network (CAN)* | advanced | 40 min | CAN buses, gateways, E2E protection, fault injection |

## Paths by interest

- **Engine control**: 1 → 2 → 3 → 4 → 5
- **Vehicle and driveline**: 1 → 6 → 7 → 8 → 9
- **Electrics and electronics**: 1 → 10 → 11
- **ECU communication**: 1 → 12, then *OBD-II* and *XCP calibration*

## Tips for every tutorial

- **Running the Python version**: each model is built by a script, e.g. `uv run python examples/truck.py`. It
  runs the model's tests and prints the key numbers quoted in the tutorial.
- **Getting lost**: **File ▸ Open** the example again to start over; your changes are only saved if you save.
- **Looking inside**: double-click a subsystem to open it, **Ctrl+↑** to go back up. Press **F1** on any
  block for its help page with the equations.
- **Comparing**: every run is kept in the **Data Inspector** (Ctrl+I). Tick two runs and a signal to overlay
  them.
- **Scripting**: the **Console** tab runs Python on the open model, e.g. `res["speed"].max()`.
