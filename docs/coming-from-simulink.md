# Coming from Simulink

Nervus uses the same ideas as Simulink, and most defaults match, so moving between the two is easy.

## Concepts

| Simulink | Nervus |
|---|---|
| model (`.slx`) | `Diagram`, saved as a `.nervus` JSON file |
| Model Configuration Parameters | `diagram.settings` (`SimulationSettings`) |
| `sim('model')` | `simulate(diagram)` |
| `out.logsout`, To Workspace | `SimResult`: `res["block"]`, `ToWorkspace(variable=...)` |
| sample time `-1`, `0`, `inf`, `[T, o]` | the same |
| ode45 / ode23 / ode15s | `RK45` / `RK23` / `BDF` or `LSODA` |
| ode4 / ode1 (fixed step) | `rk4` / `euler` |
| MATLAB Function block | Python Function block |
| S-Function | a Python `Block` subclass ([Writing blocks](developer/custom-blocks.md)) |
| Simulink Coder / Embedded Coder | planned: C code generation |

## Blocks

| Simulink | Nervus | Notes |
|---|---|---|
| Constant, Step, Ramp, Sine Wave, Pulse Generator, Clock | same names | Sine frequency in rad/s, as in Simulink |
| From Workspace | From Workspace | arrays or a CSV file |
| Gain, Sum, Product, Abs, Saturation, Math Function | same names | Sum signs as `"+-"`, Product ops as `"*/"` |
| Integrator, Derivative, Transfer Fcn, State-Space | same names | Derivative is filtered (see its help) |
| Unit Delay, Zero-Order Hold, Discrete-Time Integrator, Discrete Transfer Fcn | same names | |
| PID Controller (continuous/discrete) | PID Controller, Discrete PID Controller | parallel form, filter coefficient N |
| Scope, To Workspace, Terminator | same names | |
| Mux, Demux, Switch | same names | Switch control input is the middle port |
| 1-D / 2-D Lookup Table (n-D with 1 or 2 dims) | 1-D Lookup Table, 2-D Lookup Table | interpolation `linear`/`nearest`/`flat`; extrapolation `clip`/`linear` |
| Relational Operator, Logical Operator, Compare To Constant | same names | booleans are 1.0 / 0.0 |
| Relay, Dead Zone, Rate Limiter, Quantizer | same names | Relay and Rate Limiter run at a discrete rate |
| Delay / Integer Delay, Counter Limited, Detect Rise/Fall | Integer Delay, Counter, Edge Detect | |
| Discrete Filter / Transfer Fcn first order | Discrete Filter (PT1) | parameterised by time constant |
| MinMax, Bias, Ground | same names | |
| Model Workspace, `Simulink.Parameter` | Model Workspace variables | unit, min, max, description |

## Differences

- **Unconnected inputs are errors**, not warnings. Simulink silently treats them as zero; Nervus makes you
  decide (use a Constant 0).
- **Everything is logged.** Every block output is available in the result; Scopes just mark what the GUI
  should plot.
- **Models are text.** `.nervus` files are JSON and diff well in git.
