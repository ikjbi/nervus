# Ports & Subsystems

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

With *enable_port* the subsystem gets an extra last input, **enable**. While it is ≤ 0 nothing inside
runs: outputs and discrete states are held and continuous states stop. With *when_enabled* = ``reset``
the discrete states return to their initial values each time the subsystem is enabled again.

Its inputs and outputs are the In and Out blocks inside, in the order of their *port* numbers. Subsystems
structure a model the way functions structure code: one subsystem per ECU function (e.g. "idle control",
"fuel", "ignition"). Parameters inside can use the model workspace.

### Parameters

| Name | Default | Unit | Description |
|---|---|---|---|
| `enable_port` | `False` |  | Add an enable input: the subsystem only runs while it is > 0 |
| `when_enabled` | `'held'` |  | Discrete states when the subsystem is enabled again — one of `held`, `reset` |

*Direct feedthrough:* yes

---
