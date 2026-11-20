# Ports & Subsystems

## FMU

`fmi.fmu` · Ports & Subsystems

Runs an **FMU** (Functional Mock-up Unit, FMI 2.0 co-simulation) from another tool: Simulink, Dymola,
OpenModelica, SimulationX, AMESim, CANoe, or Nervus itself (``Code ▸ Export FMU``). The block's ports are the
FMU's real-valued inputs and outputs, in the order of its model description.

The FMU is a **co-simulation** slave: every *sample_time* (the communication step; 0 = the FMU's default step)
the block sets the inputs, lets the FMU advance by one step, and reads the outputs, which it holds until the
next step. The outputs therefore lag the inputs by one communication step, as in every co-simulation.
*parameters* sets the FMU's parameters before it starts, e.g. ``Kp = 2.0, Ki = 30``. Needs fmpy
(``uv sync --extra fmi``).

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `fmu_file` | `''` |  | FMU file (relative paths are relative to the model file) |
| `parameters` | `''` |  | Parameter values for the FMU, e.g. Kp = 2.0, Ki = 30 |
| `sample_time` | `0.0` | s | Communication step; 0 = the FMU's default step |

*Direct feedthrough:* no

---

## Connection Port

`ports.connection_port` · Ports & Subsystems

A physical port of the subsystem it is in: what is linked to it inside is linked to whatever is linked
to the subsystem's port of the same name outside. Use it to put a motor, a battery or a heat path into a
subsystem. The ports appear on the subsystem in the order of *port*; *domain* must match the links.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `port` | `1` |  | Position among the subsystem's physical ports |
| `domain` | `'electrical'` |  | Physical domain — one of `electrical`, `rotational`, `thermal`, `hydraulic` |

*Direct feedthrough:* yes · no inputs, no outputs

---

## In

`ports.inport` · Ports & Subsystems

An input port.

Inside a subsystem it is the subsystem's input number *port*. At the top level of a model it is an
external input: during simulation it outputs *value*; in generated C code it is a field of the inputs
struct.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `port` | `1` |  | Port number (1, 2, ...) |
| `value` | `0.0` |  | Value used when simulating the model on its own (top level) |
| `sample_time` | -1 (inherited) | s | Sample time of the external input (-1 = inherit) |
| `output_type` | `'double'` |  | Output data type: inherit, double, single, boolean, int8…uint32, fixdt(signed, bits, fraction) |

*Direct feedthrough:* yes · no inputs

---

## Out

`ports.outport` · Ports & Subsystems

An output port. Inside a subsystem it is the subsystem's output number *port*; at the top level it is an
external output of the model (logged in the results, and a field of the outputs struct in generated C).

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `port` | `1` |  | Port number (1, 2, ...) |

*Direct feedthrough:* yes · no outputs

---

## Subsystem

`ports.subsystem` · Ports & Subsystems

A block that contains its own diagram. Double-click it in the editor to open it.

A subsystem can be **masked**: it then has its own parameters (e.g. ``displacement``) that the blocks inside
use in their expressions, so several copies of the same component can have different values.

A subsystem can have **variants**: alternative implementations with the same inputs and outputs, e.g. a
petrol and a diesel engine model. Each variant can have a condition such as ``ENGINE == 2`` on workspace
variables; the one whose condition is true is simulated and turned into C code.

With a *sample_time* the subsystem is an **atomic task**, like one task of an ECU's operating system: every
block inside that inherits its sample time runs at that period. Its inputs are sampled at the start of each
period and its outputs held until the next one. Blocks with continuous states are not allowed inside.

With *enable_port* the subsystem gets an extra last input, **enable**. While it is ≤ 0 nothing inside
runs: outputs and discrete states are held and continuous states stop. With *when_enabled* = ``reset``
the discrete states return to their initial values each time the subsystem is enabled again.

With *trigger* the subsystem gets a last input, **trigger**, and runs only when that signal has an edge
(``rising``: from ≤ 0 to > 0, ``falling``: from > 0 to ≤ 0, or ``either``). Between triggers its outputs
and states are held. The trigger is checked each time the blocks inside would execute, so drive it with a
discrete signal of the same rate. Blocks with continuous states are not allowed inside.

With *trigger* = ``function_call`` the subsystem runs once every time the trigger value **changes**. A State
Chart (or any logic) calls it by incrementing a counter output, e.g. ``calls = calls + 1`` in a state's entry
action: the subsystem then runs in the same time step, after the chart.

Its inputs and outputs are the In and Out blocks inside, in the order of their *port* numbers. Subsystems
structure a model the way functions structure code: one subsystem per ECU function (e.g. "idle control",
"fuel", "ignition"). Parameters inside can use the model workspace.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `sample_time` | -1 (inherited) | s | Task period for the blocks inside that inherit theirs (-1 = no own rate) |
| `enable_port` | `False` |  | Add an enable input: the subsystem only runs while it is > 0 |
| `when_enabled` | `'held'` |  | Discrete states when the subsystem is enabled again — one of `held`, `reset` |
| `trigger` | `'none'` |  | Add a trigger input: the subsystem only runs when it has this kind of edge — one of `none`, `rising`, `falling`, `either`, `function_call` |

*Direct feedthrough:* yes

---
