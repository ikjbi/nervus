# State machines

Operating modes, start sequences and fault handling are naturally described as **state machines**. In
Simulink they are Stateflow charts; in Nervus they are **State Chart** blocks
(**Library → State Machines → State Chart**).

![An engine operating-mode chart](figures/chart_engine_modes.png)

## Writing a chart

Select the block and edit its *definition* in the Properties panel, then press **Apply code**:

```
# Engine operating modes
input rpm, key
output mode = 0, fuel = 0
local starts = 0

state off
  entry: mode = 0; fuel = 0

state cranking
  entry: mode = 1; starts += 1
  during: fuel = 1

state running
  entry: mode = 2; fuel = 1

transition off -> cranking: key > 0.5
transition cranking -> running: rpm > 600
transition cranking -> off: after(300) / fuel = 0
transition running -> off: key < 0.5 or rpm < 300
```

| Line | Meaning |
|---|---|
| `input a, b` | input ports, in this order |
| `output y = 0, z = 1` | output ports with initial values |
| `local n = 0` | variables kept between steps, not visible outside |
| `state NAME` | a state; the first one is the initial state (or write `initial NAME`) |
| `  entry: ...` | actions when the state is entered |
| `  during: ...` | actions every period the state stays active |
| `  exit: ...` | actions when the state is left |
| `transition A -> B: guard / action` | leave A for B when *guard* is true; the action is optional |

Actions are assignments separated by `;` (`y = 1; n += 1`). Guards and actions can use `+ - * / **`,
comparisons, `and or not`, `abs min max sqrt exp log sin cos floor ceil`, `pi` and `e`.

### Timing

- `after(n)` is true once the state has been active for **n sample periods**.
- `t_in_state` is the time in seconds since the state was entered. One period has passed at the first step
  after entering.

### Semantics

The chart runs at its sample time (set *sample_time*, or let it inherit a discrete rate). Every period:

1. The transitions leaving the active state are checked **in the order they are written**. The first with a
   true guard fires: the source's `exit` actions run, then the transition action, then the target's `entry`
   actions.
2. If none fires, the active state's `during` actions run.

With *state_output* on, an extra last output gives the active state's number (0, 1, 2, ... in the order the
states are written). It's handy for plotting.

## Calibration parameters in a chart

Thresholds and times in an ECU's mode logic are calibrated like any other value. Declare them with
**`param`**: the chart reads them, but cannot change them, and their values come from the model workspace (or
from the mask of a subsystem around the chart):

```text
input rpm, pedal
output fuel = 1
param rpm_cut_on, rpm_cut_off          # model workspace variables

state run
state fuel_cut
  entry: fuel = 0
  exit: fuel = 1

transition run -> fuel_cut: pedal < 1 and rpm > rpm_cut_on
transition fuel_cut -> run: pedal > 2 or rpm < rpm_cut_off
```

Change `rpm_cut_on` in the Model Workspace (or in a parameter set or test case) and the chart follows. In
generated C, `param` names become calibration parameters in `<model>_P`, with the variable's data type, and they
appear in the A2L file.

## Example: engine operating modes

`examples/engine_modes.py` is the mode logic of an engine ECU: **off**, **crank** (starter on, with a 3 s
starter protection into **crank_fail**), **idle** (idle speed control on), **run**, **fuel_cut** (overrun fuel
cut-off while coasting) and **stalled** (no automatic restart). All thresholds are `param`s. Four test cases
drive the key, engine speed and pedal with scenarios: a normal start, a failed start, fuel cut-off, and a stall.

![The fuel cut-off scenario](figures/engine_modes.png)

Coasting from 3000 rpm with the pedal released, the chart switches the fuel off (no fuel is needed: the car's
momentum turns the engine) and back on at 1100 rpm, before the engine could stall, and goes to idle control.

## Example: gear-shift logic

`examples/gear_shift.py` has one state per gear. Each transition compares the vehicle speed with the shift
speed read from a map for the current gear and pedal, `speed > up_speed and after(min_gear_time)`; the minimum
time in a gear and the hysteresis between the up- and downshift maps keep it from hunting. See
**Tutorial: gear-shift logic** in the help contents.

## C code

Charts are generated as a `switch` over the states, so they can be part of the ECU code. A back-to-back test
in the test suite checks the generated chart against the simulation sample by sample, with zero tolerance.

## Planned

A graphical chart editor, hierarchical (nested) and parallel states, and events are on the
roadmap.
